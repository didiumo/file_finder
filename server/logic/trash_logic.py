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
    async def move_to_trash(self, ids: List[int]) -> Dict[str, Any]:
        """批量移入回收站：物理移动 + 标记 trashed + 移除收藏快照（支持目录递归）"""
        rows = await self._load_rows(ids)
        moved = missing = 0
        errors: List[Dict[str, Any]] = []
        now = time.time()
        for row in rows:
            rel = row["rel_path"]
            src = self._src_abs(row["root_path"], rel)
            dst = self._trash_abs(row["root_path"], rel)
            # 目标已存在（同名文件曾删除）→ 追加时间戳后缀避免覆盖
            if os.path.lexists(dst):
                base, ext = os.path.splitext(rel)
                dst = self._trash_abs(row["root_path"], f"{base}~{int(now)}{ext}")
            try:
                if os.path.lexists(src):
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.move(src, dst)
                else:
                    missing += 1  # 源已被外部删除：仍记录回收，清理时只删索引
            except OSError as e:
                errors.append({"rel_path": rel, "error": str(e)})
                continue  # 移动失败不标记，文件仍在原位
            if row["is_dir"]:
                await self.db.execute(
                    self.db_path,
                    "UPDATE files SET trashed=1, trashed_at=? WHERE root_id=? "
                    "AND (rel_path=? OR rel_path LIKE ? ESCAPE '\\')",
                    (now, row["root_id"], rel, rel + "/%"),
                )
                await self.db.execute(
                    self.db_path,
                    "DELETE FROM favorites WHERE root_id=? "
                    "AND (rel_path=? OR rel_path LIKE ? ESCAPE '\\')",
                    (row["root_id"], rel, rel + "/%"),
                )
            else:
                await self.db.execute(
                    self.db_path, "UPDATE files SET trashed=1, trashed_at=? WHERE id=?",
                    (now, row["id"]),
                )
                await self.db.execute(
                    self.db_path, "DELETE FROM favorites WHERE root_id=? AND rel_path=?",
                    (row["root_id"], rel),
                )
            moved += 1
        self.log.info(f"移入回收站 {moved} 项（缺失 {missing}，失败 {len(errors)}）")
        return {"moved": moved, "missing": missing, "errors": errors[:50]}

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
