# -*- coding: utf-8 -*-
"""
file_finder 回收站逻辑
======================
- 删除 = 物理移动到 <root>/.ff_trash/（保留相对路径结构）+ 标记 trashed=1 + 移除收藏快照
- 回收站列表 = trashed=1 的索引记录（含原路径与删除时间）
- 恢复 = 移回原位置（目标冲突时报错）；清理 = 物理删除 + 从索引移除
- 索引扫描排除 .ff_trash，回收站记录在增量扫描中不会被当作“磁盘缺失”删除
"""
import asyncio
import os
import shutil
import time
from typing import Any, Dict, List, Optional, Tuple

TRASH_DIR = ".ff_trash"


class TrashLogic:
    def __init__(self, ctx):
        self.ctx = ctx
        self.db = ctx.plugins["db_v2"]
        self.db_path = str(ctx.data.get_path("file_finder.db"))
        self.task_engine = ctx.plugins.get("task")
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
        # 目标已存在（同名文件曾删除）→ 追加时间戳与 id 后缀避免并发覆盖
        if os.path.lexists(dst):
            base, ext = os.path.splitext(rel)
            dst = self._trash_abs(row["root_path"], f"{base}~{int(now)}_{row['id']}{ext}")
        try:
            if os.path.lexists(src):
                shutil.move(src, dst)
                return True, None
            return False, "missing"
        except OSError as e:
            return False, str(e)

    async def create_delete_task(self, ids: List[int]) -> Optional[str]:
        """创建后台批量删除任务，返回 task_id（支持 SSE 进度监控）"""
        if self.task_engine is None:
            return None
        task = self.task_engine.submit(
            lambda t: self._run_delete_task(ids, t),
            name=f"移入回收站 ({len(ids)} 项)",
            service="file_finder",
            total=len(ids),
            stage="正在准备移入回收站",
        )
        return task.id

    async def _run_delete_task(self, ids: List[int], task: Optional[Any]):
        return await self.move_to_trash(ids, task=task)

    async def move_to_trash(self, ids: List[int], task: Optional[Any] = None) -> Dict[str, Any]:
        """批量移入回收站：物理移动（16 线程池并发）+ 标记 trashed + 移除收藏快照（支持进度实时回传）"""
        _t0 = time.time()
        rows = await self._load_rows(ids)
        _t1 = time.time()
        now = time.time()

        if task:
            await task.update(percent=2, stage=f"已加载 {len(rows)} 项元数据，准备移动...", current=0, total=len(ids))

        # 先在 DB 中立即标记 trashed=1，保证任何并发查询/翻页立即排除已删除项，避免前端拉到脏数据产生空洞
        if rows:
            files = [r for r in rows if not r["is_dir"]]
            dirs = [r for r in rows if r["is_dir"]]
            async with self.db.transaction(self.db_path) as tx:
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

        # 预创建全部目标目录（去重一次）
        try:
            for d in {os.path.dirname(self._trash_abs(r["root_path"], r["rel_path"])) for r in rows}:
                os.makedirs(d, exist_ok=True)
        except OSError as e:
            self.log.warning(f"预创建回收站目录失败：{e}")

        moved_rows: List[Dict[str, Any]] = []
        missing = 0
        errors: List[Dict[str, Any]] = []

        total_count = len(rows)
        done_count = 0
        last_update_time = 0.0

        file_rows = [r for r in rows if not r["is_dir"]]
        dir_rows = [r for r in rows if r["is_dir"]]

        # 1. 普通文件（图片等）：通过信号量进行 16 线程池并发移动
        if file_rows:
            sem = asyncio.Semaphore(16)

            async def _safe_move_file(r):
                nonlocal done_count, missing, last_update_time
                async with sem:
                    ok, err = await asyncio.to_thread(self._move_one, r, now)
                    if ok:
                        moved_rows.append(r)
                    elif err == "missing":
                        missing += 1
                    else:
                        errors.append({"rel_path": r["rel_path"], "error": err, "id": r["id"]})
                    done_count += 1

                    curr_t = time.time()
                    if task and (curr_t - last_update_time > 0.15 or done_count == total_count):
                        last_update_time = curr_t
                        pct = min(92, max(2, int(done_count / total_count * 92)))
                        await task.update(
                            percent=pct,
                            current=done_count,
                            total=total_count,
                            stage=f"正在移入回收站 ({done_count}/{total_count})",
                        )

            await asyncio.gather(*[_safe_move_file(r) for r in file_rows])

        # 2. 目录条目：串行移动防层级冲突
        for r in dir_rows:
            ok, err = await asyncio.to_thread(self._move_one, r, now)
            if ok:
                moved_rows.append(r)
            elif err == "missing":
                missing += 1
            else:
                errors.append({"rel_path": r["rel_path"], "error": err, "id": r["id"]})
            done_count += 1
            if task:
                pct = min(92, max(2, int(done_count / total_count * 92)))
                await task.update(
                    percent=pct,
                    current=done_count,
                    total=total_count,
                    stage=f"正在移入回收站目录 ({done_count}/{total_count})",
                )

        # 3. 若有物理移动失败的项，在 DB 中回滚标记（恢复 trashed=0）
        if errors:
            err_fids = [e["id"] for e in errors if "id" in e]
            if err_fids:
                async with self.db.transaction(self.db_path) as tx:
                    await tx.execute(
                        "UPDATE files SET trashed=0, trashed_at=NULL WHERE id IN (%s)"
                        % ",".join("?" * len(err_fids)),
                        tuple(err_fids),
                    )

        _t2 = time.time()
        self.log.info(f"[perf] ids={len(ids)} load={_t1-_t0:.3f}s move={_t2-_t1:.3f}s total={_t2-_t0:.3f}s | 移入回收站 {len(moved_rows)} 项（缺失 {missing}，失败 {len(errors)}）")

        summary = {"moved": len(moved_rows), "missing": missing, "errors": errors[:50]}
        if task:
            await task.update(
                percent=100,
                current=total_count,
                total=total_count,
                stage=f"已移入回收站 {len(moved_rows)} 项" + (f"，{len(errors)} 项失败" if errors else ""),
                detail=summary,
            )
        return summary

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
            "mtime": "f.mtime", "rel_path": "f.rel_path", "path": "f.rel_path",
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
    # 恢复 / 彻底删除 / 清空回收站
    # ------------------------------------------------------------------
    def _remove_one(self, row: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """物理删除一个回收站条目（在工作线程中执行，避开主事件循环阻塞）"""
        rel = row["rel_path"]
        tpath = self._trash_abs(row["root_path"], rel)
        try:
            if os.path.lexists(tpath):
                if row.get("is_dir"):
                    shutil.rmtree(tpath, ignore_errors=True)
                else:
                    os.remove(tpath)
            return True, None
        except OSError as e:
            return False, str(e)

    def _restore_one(self, row: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """物理恢复单个条目（在工作线程中执行）"""
        rel = row["rel_path"]
        src = self._trash_abs(row["root_path"], rel)
        dst = self._src_abs(row["root_path"], rel)
        if os.path.lexists(dst):
            return False, "目标位置已存在同名文件"
        try:
            if os.path.lexists(src):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.move(src, dst)
            return True, None
        except OSError as e:
            return False, str(e)

    async def get_trash_count(self) -> int:
        """获取当前回收站条目总数"""
        return int(await self.db.fetch_val(self.db_path, "SELECT COUNT(*) FROM files WHERE trashed = 1", default=0) or 0)

    async def create_restore_task(self, ids: List[int]) -> Optional[str]:
        """创建后台恢复文件任务，返回 task_id（支持 SSE 进度监控）"""
        if self.task_engine is None:
            return None
        task = self.task_engine.submit(
            lambda t: self._run_restore_task(ids, t),
            name=f"恢复文件 ({len(ids)} 项)",
            service="file_finder",
            total=len(ids),
            stage="正在准备恢复文件",
        )
        return task.id

    async def _run_restore_task(self, ids: List[int], task: Optional[Any]):
        return await self.restore(ids, task=task)

    async def restore(self, ids: List[int], task: Optional[Any] = None) -> Dict[str, Any]:
        """从回收站恢复：移回原位置（目标已存在则跳过并报错，支持并发与进度上报）"""
        rows = await self._load_rows(ids)
        total_count = len(rows)
        if task:
            await task.update(percent=2, stage=f"已加载 {total_count} 项元数据，准备恢复...", current=0, total=total_count)

        restored = 0
        errors: List[Dict[str, Any]] = []
        ok_rows: List[Dict[str, Any]] = []
        done_count = 0
        last_update_time = 0.0

        for row in rows:
            ok, err = await asyncio.to_thread(self._restore_one, row)
            if ok:
                ok_rows.append(row)
                restored += 1
            else:
                errors.append({"rel_path": row["rel_path"], "error": err, "id": row["id"]})
            done_count += 1
            curr_t = time.time()
            if task and (curr_t - last_update_time > 0.15 or done_count == total_count):
                last_update_time = curr_t
                pct = min(92, max(2, int(done_count / total_count * 92)))
                await task.update(
                    percent=pct,
                    current=done_count,
                    total=total_count,
                    stage=f"正在恢复文件 ({done_count}/{total_count})",
                )

        if task:
            await task.update(percent=95, stage="正在更新数据库索引...")

        if ok_rows:
            files = [r for r in ok_rows if not r["is_dir"]]
            dirs = [r for r in ok_rows if r["is_dir"]]
            async with self.db.transaction(self.db_path) as tx:
                if files:
                    fids = [r["id"] for r in files]
                    for i in range(0, len(fids), 500):
                        chunk = fids[i:i + 500]
                        await tx.execute(
                            "UPDATE files SET trashed=0, trashed_at=0 WHERE id IN (%s)"
                            % ",".join("?" * len(chunk)),
                            tuple(chunk),
                        )
                for d in dirs:
                    await tx.execute(
                        "UPDATE files SET trashed=0, trashed_at=0 WHERE root_id=? "
                        "AND (rel_path=? OR rel_path LIKE ? ESCAPE '\\')",
                        (d["root_id"], d["rel_path"], d["rel_path"] + "/%"),
                    )

        summary = {"restored": restored, "errors": errors[:50]}
        if task:
            await task.update(
                percent=100,
                current=total_count,
                total=total_count,
                stage=f"恢复完成：已恢复 {restored} 项" + (f"，{len(errors)} 项失败" if errors else ""),
                detail=summary,
            )
        return summary

    async def create_purge_task(self, ids: List[int]) -> Optional[str]:
        """创建后台彻底删除任务，返回 task_id（支持 SSE 进度监控）"""
        if self.task_engine is None:
            return None
        task = self.task_engine.submit(
            lambda t: self._run_purge_task(ids, t),
            name=f"彻底删除 ({len(ids)} 项)",
            service="file_finder",
            total=len(ids),
            stage="正在准备彻底删除",
        )
        return task.id

    async def _run_purge_task(self, ids: List[int], task: Optional[Any]):
        return await self.purge(ids, task=task)

    async def purge(self, ids: List[int], task: Optional[Any] = None) -> Dict[str, Any]:
        """彻底删除：物理删除回收站文件 + 从索引移除（目录递归，支持并发与进度上报）"""
        rows = await self._load_rows(ids)
        total_count = len(rows)

        if task:
            await task.update(percent=2, stage=f"已加载 {total_count} 项元数据，准备彻底删除...", current=0, total=total_count)

        done_rows: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        purged = 0
        done_count = 0
        last_update_time = 0.0

        file_rows = [r for r in rows if not r["is_dir"]]
        dir_rows = [r for r in rows if r["is_dir"]]

        # 1. 普通文件并发删除（16 线程池并发）
        if file_rows:
            sem = asyncio.Semaphore(16)

            async def _safe_remove(r):
                nonlocal done_count, purged, last_update_time
                async with sem:
                    ok, err = await asyncio.to_thread(self._remove_one, r)
                    if ok:
                        done_rows.append(r)
                        purged += 1
                    else:
                        errors.append({"rel_path": r["rel_path"], "error": err, "id": r["id"]})
                    done_count += 1

                    curr_t = time.time()
                    if task and (curr_t - last_update_time > 0.15 or done_count == total_count):
                        last_update_time = curr_t
                        pct = min(92, max(2, int(done_count / total_count * 92)))
                        await task.update(
                            percent=pct,
                            current=done_count,
                            total=total_count,
                            stage=f"正在彻底删除 ({done_count}/{total_count})",
                        )

            await asyncio.gather(*[_safe_remove(r) for r in file_rows])

        # 2. 目录条目串行删除
        for r in dir_rows:
            ok, err = await asyncio.to_thread(self._remove_one, r)
            if ok:
                done_rows.append(r)
                purged += 1
            else:
                errors.append({"rel_path": r["rel_path"], "error": err, "id": r["id"]})
            done_count += 1
            curr_t = time.time()
            if task and (curr_t - last_update_time > 0.15 or done_count == total_count):
                last_update_time = curr_t
                pct = min(92, max(2, int(done_count / total_count * 92)))
                await task.update(
                    percent=pct,
                    current=done_count,
                    total=total_count,
                    stage=f"正在彻底删除目录 ({done_count}/{total_count})",
                )

        # 3. 数据库批量清理
        if task:
            await task.update(percent=95, stage="正在清理数据库索引...")

        if done_rows:
            files = [r for r in done_rows if not r["is_dir"]]
            dirs = [r for r in done_rows if r["is_dir"]]
            async with self.db.transaction(self.db_path) as tx:
                if files:
                    fids = [r["id"] for r in files]
                    for i in range(0, len(fids), 500):
                        chunk = fids[i:i + 500]
                        await tx.execute(
                            "DELETE FROM files WHERE id IN (%s)" % ",".join("?" * len(chunk)),
                            tuple(chunk),
                        )
                for d in dirs:
                    await tx.execute(
                        "DELETE FROM files WHERE root_id=? AND (rel_path=? OR rel_path LIKE ? ESCAPE '\\')",
                        (d["root_id"], d["rel_path"], d["rel_path"] + "/%"),
                    )

        summary = {"purged": purged, "errors": errors[:50]}
        if task:
            await task.update(
                percent=100,
                current=total_count,
                total=total_count,
                stage=f"彻底删除完成：已删除 {purged} 项" + (f"，{len(errors)} 项失败" if errors else ""),
                detail=summary,
            )
        return summary

    async def create_empty_task(self) -> Optional[str]:
        """创建后台清空回收站任务，返回 task_id（支持 SSE 进度监控）"""
        if self.task_engine is None:
            return None
        count = await self.get_trash_count()
        task = self.task_engine.submit(
            lambda t: self._run_empty_task(t),
            name=f"清空回收站 ({count} 项)",
            service="file_finder",
            total=count,
            stage="正在准备清空回收站",
        )
        return task.id

    async def _run_empty_task(self, task: Optional[Any]):
        return await self.empty(task=task)

    async def empty(self, task: Optional[Any] = None) -> Dict[str, Any]:
        """清空回收站：删除所有根下 .ff_trash 内容 + 移除全部 trashed 索引（支持并发与进度上报）"""
        rows = await self.db.fetch_all(
            self.db_path,
            "SELECT f.id, f.root_id, f.rel_path, f.is_dir, r.path AS root_path "
            "FROM files f JOIN roots r ON r.id = f.root_id WHERE f.trashed = 1",
        )
        total_count = len(rows)
        if task:
            await task.update(percent=2, stage=f"回收站共 {total_count} 项，准备清理...", current=0, total=total_count)

        purged = 0
        done_count = 0
        last_update_time = 0.0

        file_rows = [r for r in rows if not r["is_dir"]]
        dir_rows = [r for r in rows if r["is_dir"]]

        if file_rows:
            sem = asyncio.Semaphore(16)

            async def _safe_remove(r):
                nonlocal done_count, purged, last_update_time
                async with sem:
                    ok, _ = await asyncio.to_thread(self._remove_one, r)
                    if ok:
                        purged += 1
                    done_count += 1

                    curr_t = time.time()
                    if task and (curr_t - last_update_time > 0.15 or done_count == total_count):
                        last_update_time = curr_t
                        pct = min(90, max(2, int(done_count / total_count * 90)))
                        await task.update(
                            percent=pct,
                            current=done_count,
                            total=total_count,
                            stage=f"正在清空回收站 ({done_count}/{total_count})",
                        )

            await asyncio.gather(*[_safe_remove(r) for r in file_rows])

        for r in dir_rows:
            ok, _ = await asyncio.to_thread(self._remove_one, r)
            if ok:
                purged += 1
            done_count += 1
            curr_t = time.time()
            if task and (curr_t - last_update_time > 0.15 or done_count == total_count):
                last_update_time = curr_t
                pct = min(90, max(2, int(done_count / total_count * 90)))
                await task.update(
                    percent=pct,
                    current=done_count,
                    total=total_count,
                    stage=f"正在清空回收站目录 ({done_count}/{total_count})",
                )

        if task:
            await task.update(percent=95, stage="正在清除数据库索引与目录壳...")

        await self.db.execute(self.db_path, "DELETE FROM files WHERE trashed=1")

        # 顺带清掉空的回收站目录壳（在线程池中执行）
        root_ids = {r["root_id"] for r in rows}
        for root_id in root_ids:
            root = await self.db.fetch_one(
                self.db_path, "SELECT path FROM roots WHERE id=?", (root_id,)
            )
            if root:
                tdir = os.path.join(root["path"].rstrip("\\/"), TRASH_DIR)
                if os.path.isdir(tdir):
                    try:
                        await asyncio.to_thread(shutil.rmtree, tdir, ignore_errors=True)
                    except OSError:
                        pass

        self.log.info(f"清空回收站：物理删除 {purged} 项")
        summary = {"purged": purged}
        if task:
            await task.update(
                percent=100,
                current=total_count,
                total=total_count,
                stage=f"已清空回收站（共清理 {purged} 项）",
                detail=summary,
            )
        return summary
