"""
file_finder 收藏整理与清理流水线
===============================
核心业务闭环：
    收藏 → 整理（把收藏的文件复制/汇集到本地指定目录）→ 清理（删除扫描根内
    除收藏外的所有内容）→ 重新索引

安全设计（重要）：
1. 任何删除前都做 realpath 前缀校验，确认目标在某个扫描根之内，杜绝越界删除；
2. 收藏文件及其目录子树会被完整排除在删除清单之外；
3. 收集目标目录（默认 services/file_finder/data/collected）必须位于所有扫描根
   之外，否则直接拒绝执行；
4. 跳过所有符号链接/联接点（不跟随、不删除目标）；
5. 清理执行前必须通过 plan 接口预览（数量、体积、样本），并显式传 confirm=true；
6. 全程通过 task 插件上报进度（SSE 可订阅）。
"""
import asyncio
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from plugins.task_plugin import TaskContext

from .common import abs_path


class CollectionLogic:
    def __init__(self, ctx, indexer, favorite_logic):
        self.ctx = ctx
        self.db = ctx.plugins["db_v2"]
        self.db_path = str(ctx.data.get_path("file_finder.db"))
        self.task_engine = ctx.plugins.get("task")
        self.log = ctx.plugins["logger"].get_logger(ctx.service_name)
        self.indexer = indexer
        self.favorite_logic = favorite_logic
        self.collection_dir: Path = ctx.data.get_path(ctx.config.get("collection_dir", "collected"))
        self.cleanup_workers = max(1, int(ctx.config.get("cleanup_workers", 8)))

    # ------------------------------------------------------------------
    # 路径安全工具
    # ------------------------------------------------------------------
    @staticmethod
    def _is_within(real_target: str, real_root: str) -> bool:
        real_root = real_root.rstrip("\\/")
        if real_target == real_root:
            return True
        return real_target.startswith(real_root + os.sep)

    def _validate_collection_dir(self, roots: List[Dict[str, Any]]):
        col_real = os.path.realpath(str(self.collection_dir))
        for r in roots:
            if self._is_within(col_real, r["path"]):
                raise ValueError(
                    f"收集目标目录不能位于扫描根之内: {self.collection_dir} 在 {r['path']} 内"
                )

    # ------------------------------------------------------------------
    # 预览计划（不执行任何修改）
    # ------------------------------------------------------------------
    async def plan(self) -> Dict[str, Any]:
        roots = await self.indexer.list_roots()
        self._validate_collection_dir(roots)
        favorites = await self.favorite_logic.all_favorites()

        copy_items = []
        copy_bytes = 0
        missing = 0
        root_folders: Dict[int, str] = {}
        for fav in favorites:
            if not fav["exists_now"]:
                missing += 1
                continue
            src = abs_path(fav["root_path"], fav["rel_path"])
            if not os.path.exists(src):
                missing += 1
                continue
            # 目标子目录：根目录显示名（重名时追加 id）
            folder = root_folders.get(fav["root_id"])
            if folder is None:
                base = (fav["root_name"] or os.path.basename(fav["root_path"].rstrip("\\/")) or "root")
                folder = f"{base}_{fav['root_id']}"
                root_folders[fav["root_id"]] = folder
            dest = str(self.collection_dir / folder / fav["rel_path"].replace("/", os.sep))
            is_dir = os.path.isdir(src)
            size = 0
            count = 1
            if is_dir:
                count = 0
                for dp, dns, fns in os.walk(src):
                    for fn in fns:
                        try:
                            size += os.path.getsize(os.path.join(dp, fn))
                            count += 1
                        except OSError:
                            pass
            else:
                try:
                    size = os.path.getsize(src)
                except OSError:
                    size = 0
            copy_bytes += size
            copy_items.append({
                "root_id": fav["root_id"], "rel_path": fav["rel_path"],
                "name": fav["name"], "size": size, "is_dir": is_dir,
                "source": src, "dest": dest,
            })

        # 待删除清单（来自索引；索引未覆盖的文件不参与，文档中说明）
        delete_rows = await self.db.fetch_all(
            self.db_path,
            "SELECT f.id, f.root_id, f.rel_path, f.size FROM files f WHERE f.is_dir = 0",
        )
        fav_keys: Set[Tuple[int, str]] = set()
        fav_prefixes: List[Tuple[int, str]] = []
        for fav in favorites:
            key = (fav["root_id"], fav["rel_path"])
            fav_keys.add(key)
            if os.path.isdir(abs_path(fav["root_path"], fav["rel_path"])):
                fav_prefixes.append(key)
        delete_items = []
        delete_bytes = 0
        for row in delete_rows:
            rid, rel = row["root_id"], row["rel_path"]
            if (rid, rel) in fav_keys:
                continue
            if any(rid == pr and (rel == pp or rel.startswith(pp + "/")) for pr, pp in fav_prefixes):
                continue
            delete_items.append({"root_id": rid, "rel_path": rel, "size": row["size"]})
            delete_bytes += row["size"]

        return {
            "target_dir": str(self.collection_dir),
            "favorites_total": len(favorites),
            "favorites_ok": len(copy_items),
            "favorites_missing": missing,
            "copy_items": len(copy_items),
            "copy_files": sum(1 for c in copy_items if not c["is_dir"]),
            "copy_dirs": sum(1 for c in copy_items if c["is_dir"]),
            "copy_bytes": copy_bytes,
            "delete_files": len(delete_items),
            "delete_bytes": delete_bytes,
            "delete_sample": delete_items[:20],
            "roots": [{"id": r["id"], "path": r["path"]} for r in roots],
        }

    # ------------------------------------------------------------------
    # 执行：整理 + 清理
    # ------------------------------------------------------------------
    async def run(
        self,
        copy: bool = True,
        cleanup: bool = True,
        remove_empty_roots: bool = True,
        confirm: bool = False,
        root_ids: Optional[List[int]] = None,
    ) -> Optional[str]:
        if not confirm:
            raise ValueError("请先确认执行（confirm=true），建议先调用 plan 预览")

        # 安全护栏：收藏 = 保留清单，没有任何收藏时拒绝清理，防止误操作全删
        if cleanup:
            fav_n = await self.favorite_logic.count()
            if fav_n <= 0:
                raise ValueError("当前没有任何收藏文件，拒绝执行清理（收藏即保留清单，请先收藏要保留的内容）")

        roots = await self.indexer.list_roots()
        self._validate_collection_dir(roots)
        if root_ids:
            roots = [r for r in roots if r["id"] in root_ids]
        if not roots:
            raise ValueError("没有可执行的扫描根")

        if self.task_engine is None:
            await self._run_worker(roots, copy, cleanup, remove_empty_roots, None)
            return None
        task = self.task_engine.submit(
            lambda t: self._run_worker(roots, copy, cleanup, remove_empty_roots, t),
            name="收藏整理与清理",
            service="file_finder",
            total=100,
            stage="准备执行",
        )
        return task.id

    async def _run_worker(self, roots: List[Dict[str, Any]], copy: bool, cleanup: bool,
                          remove_empty_roots: bool, task: Optional[TaskContext]):
        summary: Dict[str, Any] = {"copied": 0, "copy_bytes": 0, "deleted": 0,
                                   "deleted_bytes": 0, "errors": []}
        favorites = await self.favorite_logic.all_favorites()
        fav_keys: Set[Tuple[int, str]] = set()
        fav_prefixes: List[Tuple[int, str]] = []
        for fav in favorites:
            key = (fav["root_id"], fav["rel_path"])
            fav_keys.add(key)
            if os.path.isdir(abs_path(fav["root_path"], fav["rel_path"])):
                fav_prefixes.append(key)

        # ---------------- Stage 1: 复制收藏 ----------------
        if copy:
            await self._stage_copy(favorites, fav_keys, task, summary)
        if task and task.is_cancelled:
            return summary

        # ---------------- Stage 2: 清理非收藏内容 ----------------
        if cleanup:
            await self._stage_cleanup(roots, fav_keys, fav_prefixes, remove_empty_roots, task, summary)
        if task and task.is_cancelled:
            return summary

        # ---------------- Stage 3: 重新索引 ----------------
        if cleanup or copy:
            if task:
                await task.update(percent=96, stage="清理完成，正在重新索引...")
            for r in roots:
                try:
                    await self.indexer.scan_root(r["id"], mode="incremental")
                except Exception as e:
                    summary["errors"].append(f"重扫 {r['path']} 失败: {e}")

        if task:
            await task.update(
                percent=100, stage="整理与清理完成",
                detail=summary,
            )
        self.log.info(f"collect/cleanup 完成: {summary}")
        return summary

    # ---------------- Stage 1: 复制 ----------------
    async def _stage_copy(self, favorites: List[Dict[str, Any]], fav_keys: Set[Tuple[int, str]],
                          task: Optional[TaskContext], summary: Dict[str, Any]):
        if task:
            await task.update(percent=5, stage="开始复制收藏文件", current=0, total=len(favorites))
        done = 0
        for fav in favorites:
            if task and task.is_cancelled:
                return
            if not fav["exists_now"]:
                done += 1
                continue
            src = abs_path(fav["root_path"], fav["rel_path"])
            if not os.path.exists(src):
                done += 1
                continue
            base = (fav["root_name"] or os.path.basename(fav["root_path"].rstrip("\\/")) or "root")
            folder = f"{base}_{fav['root_id']}"
            dest = self.collection_dir / folder / fav["rel_path"].replace("/", os.sep)
            try:
                if os.path.isdir(src):
                    shutil.copytree(
                        src, dest, dirs_exist_ok=True, symlinks=False,
                        ignore_dangling_symlinks=True,
                        copy_function=shutil.copy2,
                    )
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)
                summary["copied"] += 1
                try:
                    summary["copy_bytes"] += os.path.getsize(dest) if os.path.isfile(dest) else 0
                except OSError:
                    pass
            except Exception as e:
                summary["errors"].append(f"复制失败 {src}: {e}")
            done += 1
            if task and done % 5 == 0:
                await task.update(percent=5 + int(done / max(1, len(favorites)) * 30),
                                  current=done, stage=f"复制收藏 {done}/{len(favorites)}")

    # ---------------- Stage 2: 清理 ----------------
    async def _stage_cleanup(self, roots: List[Dict[str, Any]],
                             fav_keys: Set[Tuple[int, str]],
                             fav_prefixes: List[Tuple[int, str]],
                             remove_empty_roots: bool,
                             task: Optional[TaskContext], summary: Dict[str, Any]):
        rows = await self.db.fetch_all(
            self.db_path,
            "SELECT f.id, f.root_id, f.rel_path, f.size FROM files f WHERE f.is_dir = 0",
        )
        candidates: List[Tuple[int, str, int]] = []
        root_by_id = {r["id"]: r for r in roots}
        for row in rows:
            rid, rel = row["root_id"], row["rel_path"]
            if rid not in root_by_id:
                continue
            if (rid, rel) in fav_keys:
                continue
            if any(rid == pr and (rel == pp or rel.startswith(pp + "/")) for pr, pp in fav_prefixes):
                continue
            candidates.append((rid, rel, row["size"]))

        if task:
            await task.update(percent=40, stage=f"开始移入回收站（共 {len(candidates)} 个）",
                              current=0, total=max(1, len(candidates)))

        errors: List[str] = []
        lock = threading.Lock()
        # 预计算每个根的 realpath，避免每删一个文件都做一次网络 realpath
        real_roots = {rid: os.path.realpath(r["path"]).rstrip("\\/") for rid, r in root_by_id.items()}
        trash_dir = ".ff_trash"

        def _unlink_worker(work: List[Tuple[int, str, int]]) -> int:
            n = 0
            for rid, rel, size in work:
                root_real = real_roots[rid]
                full = os.path.realpath(abs_path(root_by_id[rid]["path"], rel))
                if not self._is_within(full, root_real):
                    with lock:
                        errors.append(f"越界跳过: {full}")
                    continue
                try:
                    if os.path.isfile(full) and not os.path.islink(full):
                        # 删除统一先进回收站：移动到 <root>/.ff_trash/<rel_path>
                        dst = os.path.join(root_by_id[rid]["path"].rstrip("\\/"), trash_dir, *rel.split("/"))
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        if os.path.lexists(dst):
                            base, ext = os.path.splitext(dst)
                            dst = f"{base}~{int(time.time())}{ext}"
                        shutil.move(full, dst)
                        n += 1
                        with lock:
                            summary["deleted_bytes"] = summary.get("deleted_bytes", 0) + size
                except OSError as e:
                    with lock:
                        errors.append(f"移动失败 {full}: {e}")
            return n

        # 并行移动（分片）
        chunk_size = max(1, len(candidates) // self.cleanup_workers)
        chunks = [candidates[i:i + chunk_size] for i in range(0, len(candidates), chunk_size)] or [[]]
        loop = asyncio.get_running_loop()
        done_cnt = 0
        with ThreadPoolExecutor(max_workers=self.cleanup_workers, thread_name_prefix="ff-del") as pool:
            futs = [loop.run_in_executor(pool, _unlink_worker, ch) for ch in chunks]
            for fut in asyncio.as_completed(futs):
                done_cnt += fut.result()
                if task:
                    await task.update(percent=40 + int(done_cnt / max(1, len(candidates)) * 40),
                                      current=done_cnt, stage=f"移入回收站 {done_cnt}/{len(candidates)}")
        summary["deleted"] = done_cnt
        summary["errors"].extend(errors[:50])

        # 标记回收（批量）：物理位置已变化，索引标记 trashed 后搜索/预览不可见
        now = time.time()
        actual_moved: List[Tuple[int, str]] = []
        for rid, rel, _size in candidates:
            src = os.path.join(root_by_id[rid]["path"].rstrip("\\/"), *rel.split("/"))
            if not os.path.lexists(src):  # 原位置已不存在 → 已移入回收站
                actual_moved.append((rid, rel))
        if actual_moved:
            await self.db.execute_many(
                self.db_path,
                "UPDATE files SET trashed=1, trashed_at=? WHERE root_id=? AND rel_path=?",
                [(now, rid, rel) for rid, rel in actual_moved],
            )
            # 移除收藏快照（保留清单跟随删除语义）
            for rid, rel in actual_moved:
                await self.db.execute(
                    self.db_path, "DELETE FROM favorites WHERE root_id=? AND rel_path=?",
                    (rid, rel),
                )

        # 移除空目录（自底向上）
        removed_dirs = 0
        for root in roots:
            removed_dirs += self._remove_empty_dirs(root["path"])
        summary["removed_dirs"] = removed_dirs

        if remove_empty_roots:
            for root in roots:
                try:
                    if os.path.isdir(root["path"]) and not os.listdir(root["path"]):
                        os.rmdir(root["path"])
                        summary["removed_roots"] = summary.get("removed_roots", 0) + 1
                        self.log.info(f"已移除空扫描根目录: {root['path']}")
                except OSError as e:
                    summary["errors"].append(f"移除根目录失败 {root['path']}: {e}")

        if task:
            await task.update(percent=90, stage=f"清理完成，删除 {summary['deleted']} 个文件",
                              current=summary["deleted"], total=max(1, len(candidates)))

    def _remove_empty_dirs(self, root_path: str) -> int:
        """自底向上删除空目录，返回删除数量"""
        removed = 0
        for dirpath, dirnames, filenames in os.walk(root_path, topdown=False):
            try:
                if not os.path.islink(dirpath) and not dirnames and not filenames:
                    os.rmdir(dirpath)
                    removed += 1
            except OSError:
                pass
        return removed
