# -*- coding: utf-8 -*-
"""
file_finder 回收站逻辑
======================
- 删除 = 物理移动到 <root>/.ff_trash/（保留相对路径结构）+ 标记 trashed=1 + 移除收藏快照
- 回收站列表 = trashed=1 的索引记录（含原路径与删除时间）
- 恢复 = 移回原位置（目标冲突时报错）；清理 = 物理删除 + 从索引移除
- 索引扫描排除 .ff_trash，回收站记录在增量扫描中不会被当作“磁盘缺失”删除
"""
import os
import shutil
import time
import concurrent.futures
from typing import Any, Dict, List, Optional

TRASH_DIR = ".ff_trash"


class TrashLogic:
    def __init__(self, ctx):
        self.ctx = ctx
        self.db = ctx.plugins["db_v2"]
        self.db_path = str(ctx.data.get_path("file_finder.db"))
        self.log = ctx.plugins["logger"].get_logger(ctx.service_name)

    @staticmethod
    def _src_abs(root_path: str, rel_path: str) -> str:
        root = root_path.rstrip("\\/")
        return os.path.join(root, *rel_path.split("/"))

    @staticmethod
    def _trash_abs(root_path: str, rel_path: str) -> str:
        root = root_path.rstrip("\\/")
        return os.path.join(root, TRASH_DIR, *rel_path.split("/"))

    async def _load_rows(self, ids: List[int]) -> List[Dict[str, Any]]:
        if not ids:
            return []
        rows = await self.db.fetch_all(
            self.db_path,
            "SELECT f.id, f.root_id, f.rel_path, f.name, f.is_dir, f.size, f.mtime, "
            "r.path AS root_path, r.display_name AS root_name "
            "FROM files f JOIN roots r ON r.id = f.root_id "
            f"WHERE f.id IN ({','.join('?' * len(ids))})",
            tuple(ids),
        )
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # 删除 → 回收站
    # ------------------------------------------------------------------
    def _move_one(self, row: Dict[str, Any], now: float):
        """单个条目物理移动到回收站（在线程池中执行，网络 IO 并行）
        返回 (ok, err)：ok=True 移动成功；err='missing' 源不存在；否则为错误信息"""
        rel = row["rel_path"]
        src = self._src_abs(row["root_path"], rel)
        dst = self._trash_abs(row["root_path"], rel)
        # 目标已存在（同名文件曾删除）→ 追加时间戳后缀避免覆盖
        if os.path.lexists(dst):
            base, ext = os.path.splitext(rel)
            dst = self._trash_abs(row["root_path"], f"{base}~{int(now)}{ext}")
        try:
            if os.path.lexists(src):
                # 目录已在 move_to_trash 预创建（并发 makedirs 同一目录在 Windows 上有锁争用）
                shutil.move(src, dst)
                return True, None
            return False, "missing"
        except OSError as e:
            return False, str(e)

    async def move_to_trash(self, ids: List[int]) -> Dict[str, Any]:
        """批量移入回收站：物理移动（线程池并行）+ 标记 trashed + 移除收藏快照（支持目录递归）

        性能关键：
        - 移动是网络 IO，串行逐个移动会让网络延迟累加 → 8 线程并行重叠延迟
        - db_v2 的 execute() 每次自动 commit（磁盘 fsync）→ 全部 DB 写收敛到
          一个事务（async with db.transaction）内批量执行，fsync 从 O(N) 降到 O(1)
        """
        _t0 = time.time()
        rows = await self._load_rows(ids)
        _t1 = time.time()
        now = time.time()
        # 预创建全部目标目录（去重一次）。注意：Windows 上多线程并发
        # os.makedirs(同一目录, exist_ok=True) 有严重锁争用（实测 100 文件
        # 8 线程逐文件 makedirs 3.1s vs 串行直接 move 0.13s），因此目录
        # 创建收敛到一次串行完成，移动阶段不再做任何 makedirs。
        try:
            for d in {os.path.dirname(self._trash_abs(r["root_path"], r["rel_path"])) for r in rows}:
                os.makedirs(d, exist_ok=True)
        except OSError as e:
            self.log.warning(f"预创建回收站目录失败：{e}")
        moved_rows: List[Dict[str, Any]] = []
        missing = 0
        errors: List[Dict[str, Any]] = []
        if rows:
            for row in rows:
                ok, err = self._move_one(row, now)
                if ok:
                    moved_rows.append(row)
                elif err == "missing":
                    missing += 1  # 源已被外部删除：仍记录回收，清理时只删索引
                else:
                    errors.append({"rel_path": row["rel_path"], "error": err})
                    # 移动失败不标记，文件仍在原位
        _t2 = time.time()
        self.log.info(f"[perf] ids={len(ids)} load={_t1-_t0:.3f}s move={_t2-_t1:.3f}s")
        if moved_rows:
            files = [r for r in moved_rows if not r["is_dir"]]
            dirs = [r for r in moved_rows if r["is_dir"]]
            async with self.db.transaction(self.db_path) as tx:
                # 文件：一条 UPDATE 批量标记 + 一条 DELETE 批量移除收藏
                if files:
                    fids = [r["id"] for r in files]
                    await tx.execute(
                        "UPDATE files SET trashed=1, trashed_at=? WHERE id IN (%s)"
                        % ",".join("?" * len(fids)),
                        (now, *fids),
                    )
                    pairs = [(r["root_id"], r["rel_path"]) for r in files]
                    ors = " OR ".join(["(root_id=? AND rel_path=?)"] * len(pairs))
                    flat = [v for pr in pairs for v in pr]
                    await tx.execute(f"DELETE FROM favorites WHERE {ors}", tuple(flat))
                # 目录：递归标记（含子树），目录数量少逐条执行
                for d in dirs:
                    await tx.execute(
                        "UPDATE files SET trashed=1, trashed_at=? WHERE root_id=? "
                        "AND (rel_path=? OR rel_path LIKE ? ESCAPE '\\')",
                        (now, d["root_id"], d["rel_path"], d["rel_path"] + "/%"),
                    )
                    await tx.execute(
                        "DELETE FROM favorites WHERE root_id=? "
                        "AND (rel_path=? OR rel_path LIKE ? ESCAPE '\\')",
                        (d["root_id"], d["rel_path"], d["rel_path"] + "/%"),
                    )
        _t3 = time.time()
        self.log.info(f"[perf] db={_t3-_t2:.3f}s total={_t3-_t0:.3f}s | 移入回收站 {len(moved_rows)} 项（缺失 {missing}，失败 {len(errors)}）")
        return {"moved": len(moved_rows), "missing": missing, "errors": errors[:50]}

    # ------------------------------------------------------------------
    # 回收站列表
    # ------------------------------------------------------------------
    async def list_trash(
        self,
        root_id: Optional[int] = None,
        q: str = "",
        sort: str = "trashed_at",
        order: str = "desc",
        page: int = 1,
        page_size: int = 300,
    ) -> Dict[str, Any]:
        where: List[str] = ["f.trashed = 1"]
        params: List[Any] = []
        if root_id is not None:
            where.append("f.root_id = ?")
            params.append(root_id)
        q = (q or "").strip()
        if q:
            esc = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            like = f"%{esc}%"
            where.append("(f.name LIKE ? ESCAPE '\\' OR f.rel_path LIKE ? ESCAPE '\\')")
            params.extend([like, like])
        where_sql = " AND ".join(where)
        sort_col = {
            "trashed_at": "f.trashed_at", "name": "f.name", "size": "f.size",
            "mtime": "f.mtime", "rel_path": "f.rel_path",
        }.get(sort, "f.trashed_at")
        order_sql = "DESC" if str(order).lower() == "desc" else "ASC"
        page = max(1, int(page))
        page_size = max(1, min(2000, int(page_size)))
        total = await self.db.fetch_val(
            self.db_path, f"SELECT COUNT(*) FROM files f WHERE {where_sql}",
            tuple(params), default=0,
        )
        rows = await self.db.fetch_all(
            self.db_path,
            "SELECT f.id, f.root_id, f.rel_path, f.name, f.parent_dir, f.ext, "
            "f.size, f.mtime, f.is_dir, f.trashed_at, "
            "r.path AS root_path, r.display_name AS root_name "
            "FROM files f JOIN roots r ON r.id = f.root_id "
            f"WHERE {where_sql} ORDER BY {sort_col} {order_sql}, f.id DESC LIMIT ? OFFSET ?",
            tuple(params + [page_size, (page - 1) * page_size]),
        )
        items = [
            {
                "id": r["id"], "root_id": r["root_id"], "root_path": r["root_path"],
                "root_name": r["root_name"], "rel_path": r["rel_path"], "name": r["name"],
                "parent_dir": r["parent_dir"], "ext": r["ext"], "size": r["size"],
                "mtime": r["mtime"], "is_dir": bool(r["is_dir"]), "trashed_at": r["trashed_at"],
            }
            for r in rows
        ]
        return {
            "total": int(total or 0), "page": page, "page_size": page_size,
            "has_more": page * page_size < int(total or 0), "items": items,
        }

    # ------------------------------------------------------------------
    # 恢复 / 清理
    # ------------------------------------------------------------------
    async def restore(self, ids: List[int]) -> Dict[str, Any]:
        """从回收站恢复：移回原位置（目标已存在则跳过并报错）"""
        rows = await self._load_rows(ids)
        restored = 0
        errors: List[Dict[str, Any]] = []
        for row in rows:
            rel = row["rel_path"]
            src = self._trash_abs(row["root_path"], rel)
            dst = self._src_abs(row["root_path"], rel)
            if os.path.lexists(dst):
                errors.append({"rel_path": rel, "error": "目标位置已存在同名文件"})
                continue
            try:
                if os.path.lexists(src):
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.move(src, dst)
                if row["is_dir"]:
                    await self.db.execute(
                        self.db_path,
                        "UPDATE files SET trashed=0, trashed_at=0 WHERE root_id=? "
                        "AND (rel_path=? OR rel_path LIKE ? ESCAPE '\\')",
                        (row["root_id"], rel, rel + "/%"),
                    )
                else:
                    await self.db.execute(
                        self.db_path, "UPDATE files SET trashed=0, trashed_at=0 WHERE id=?",
                        (row["id"],),
                    )
                restored += 1
            except OSError as e:
                errors.append({"rel_path": rel, "error": str(e)})
        return {"restored": restored, "errors": errors[:50]}

    async def purge(self, ids: List[int]) -> Dict[str, Any]:
        """彻底删除：物理删除回收站文件 + 从索引移除（目录递归）"""
        rows = await self._load_rows(ids)
        purged = 0
        errors: List[Dict[str, Any]] = []
        for row in rows:
            rel = row["rel_path"]
            tpath = self._trash_abs(row["root_path"], rel)
            try:
                if os.path.lexists(tpath):
                    if row["is_dir"]:
                        shutil.rmtree(tpath, ignore_errors=True)
                    else:
                        os.remove(tpath)
                if row["is_dir"]:
                    await self.db.execute(
                        self.db_path,
                        "DELETE FROM files WHERE root_id=? AND (rel_path=? OR rel_path LIKE ? ESCAPE '\\')",
                        (row["root_id"], rel, rel + "/%"),
                    )
                else:
                    await self.db.execute(
                        self.db_path, "DELETE FROM files WHERE id=?", (row["id"],)
                    )
                purged += 1
            except OSError as e:
                errors.append({"rel_path": rel, "error": str(e)})
        return {"purged": purged, "errors": errors[:50]}

    async def empty(self) -> Dict[str, Any]:
        """清空回收站：删除所有根下 .ff_trash 内容 + 移除全部 trashed 索引"""
        rows = await self.db.fetch_all(
            self.db_path,
            "SELECT f.id, f.root_id, f.rel_path, f.is_dir, r.path AS root_path "
            "FROM files f JOIN roots r ON r.id = f.root_id WHERE f.trashed = 1",
        )
        purged = 0
        for row in rows:
            tpath = self._trash_abs(row["root_path"], row["rel_path"])
            try:
                if os.path.lexists(tpath):
                    if row["is_dir"]:
                        shutil.rmtree(tpath, ignore_errors=True)
                    else:
                        os.remove(tpath)
                purged += 1
            except OSError:
                pass
        await self.db.execute(self.db_path, "DELETE FROM files WHERE trashed=1")
        # 顺带清掉空的回收站目录壳（忽略失败）
        for root_id in {r["root_id"] for r in rows}:
            root = await self.db.fetch_one(
                self.db_path, "SELECT path FROM roots WHERE id=?", (root_id,)
            )
            if root:
                tdir = os.path.join(root["path"].rstrip("\\/"), TRASH_DIR)
                if os.path.isdir(tdir):
                    try:
                        shutil.rmtree(tdir)
                    except OSError:
                        pass
        self.log.info(f"清空回收站：物理删除 {purged} 项")
        return {"purged": purged}
