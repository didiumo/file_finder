"""
file_finder 索引引擎
====================
核心职责：
1. 管理扫描根目录（局域网共享路径）的增删查
2. 多线程并发遍历文件系统（ThreadPoolExecutor 并行 scandir + stat）
3. 基于 db_v2（WAL + 读写分离连接池 + executemany 批量写）落库
4. 通过 task 插件上报后台扫描进度（SSE 可订阅）

并发模型：
- 遍历阶段：N 个工作线程共享一个目录任务队列，并行 scandir/stat（网络 IO 密集）
- 写库阶段：事件循环内的异步消费者从线程安全队列批量取记录，
  每 2000 条调用一次 db_v2.execute_many 提交（WAL 模式，写入开销可控）
- 进度上报：共享 stats 字典（GIL 保护下的整数自增），消费者定期折算百分比
"""
import asyncio
import os
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from plugins.task_plugin import TaskContext

_SCHEMA_STATEMENTS: List[str] = [
    """
CREATE TABLE IF NOT EXISTS roots (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    path             TEXT    NOT NULL UNIQUE,
    display_name     TEXT    NOT NULL DEFAULT '',
    enabled          INTEGER NOT NULL DEFAULT 1,
    last_scan_at     REAL,
    last_scan_count  INTEGER,
    last_scan_elapsed REAL,
    created_at       REAL    NOT NULL
);
""",
    """
CREATE TABLE IF NOT EXISTS files (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    root_id    INTEGER NOT NULL,
    rel_path   TEXT    NOT NULL,
    name       TEXT    NOT NULL,
    parent_dir TEXT    NOT NULL DEFAULT '',
    ext        TEXT    NOT NULL DEFAULT '',
    size       INTEGER NOT NULL DEFAULT 0,
    mtime      REAL    NOT NULL DEFAULT 0,
    is_dir     INTEGER NOT NULL DEFAULT 0,
    indexed_at REAL    NOT NULL DEFAULT 0,
    UNIQUE(root_id, rel_path)
);
""",
    "CREATE INDEX IF NOT EXISTS idx_files_root   ON files(root_id);",
    "CREATE INDEX IF NOT EXISTS idx_files_name   ON files(name);",
    "CREATE INDEX IF NOT EXISTS idx_files_parent ON files(parent_dir);",
    "CREATE INDEX IF NOT EXISTS idx_files_ext    ON files(ext);",
    "CREATE INDEX IF NOT EXISTS idx_files_rel    ON files(rel_path);",
    # 覆盖索引：支撑「浏览全部 + 按 name/size/mtime 排序」的无全表排序翻页
    "CREATE INDEX IF NOT EXISTS idx_files_name_dir ON files(name, is_dir, id);",
    "CREATE INDEX IF NOT EXISTS idx_files_size_dir ON files(size, is_dir, id);",
    "CREATE INDEX IF NOT EXISTS idx_files_mtime_dir ON files(mtime, is_dir, id);",
    """
CREATE TABLE IF NOT EXISTS favorites (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    root_id    INTEGER NOT NULL,
    rel_path   TEXT    NOT NULL,
    name       TEXT    NOT NULL DEFAULT '',
    size       INTEGER NOT NULL DEFAULT 0,
    mtime      REAL    NOT NULL DEFAULT 0,
    ext        TEXT    NOT NULL DEFAULT '',
    created_at REAL    NOT NULL,
    UNIQUE(root_id, rel_path)
);
""",
    # FTS5 全文索引（trigram 支持任意子串匹配，≥3 字符生效）
    # 外链表 + 触发器同步，与 files 表事务一致
    """
CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
    name, rel_path,
    tokenize = 'trigram',
    content = 'files',
    content_rowid = 'id'
);
""",
    """
CREATE TRIGGER IF NOT EXISTS files_fts_ai AFTER INSERT ON files BEGIN
    INSERT INTO files_fts(rowid, name, rel_path) VALUES (new.id, new.name, new.rel_path);
END;
""",
    """
CREATE TRIGGER IF NOT EXISTS files_fts_ad AFTER DELETE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, name, rel_path) VALUES ('delete', old.id, old.name, old.rel_path);
END;
""",
    """
CREATE TRIGGER IF NOT EXISTS files_fts_au AFTER UPDATE OF name, rel_path ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, name, rel_path) VALUES ('delete', old.id, old.name, old.rel_path);
    INSERT INTO files_fts(rowid, name, rel_path) VALUES (new.id, new.name, new.rel_path);
END;
""",
]

_INSERT_SQL = (
    "INSERT OR REPLACE INTO files "
    "(root_id, rel_path, name, parent_dir, ext, size, mtime, is_dir, indexed_at) "
    "VALUES (?,?,?,?,?,?,?,?,?)"
)

# 记录结构: (rel_path, name, parent_dir, ext, size, mtime, is_dir)
_Record = Tuple[str, str, str, str, int, float, int]


def _ext_of(name: str) -> str:
    """取小写扩展名（不含点）"""
    idx = name.rfind(".")
    if idx <= 0 or idx == len(name) - 1:
        return ""
    return name[idx + 1:].lower()


class IndexerLogic:
    """索引引擎业务逻辑"""

    def __init__(self, ctx):
        self.ctx = ctx
        self.db = ctx.plugins["db_v2"]
        self.db_path = str(ctx.data.get_path("file_finder.db"))
        self.task_engine = ctx.plugins.get("task")
        self.log = ctx.plugins["logger"].get_logger(ctx.service_name)
        self.scan_workers = max(1, int(ctx.config.get("scan_workers", 8)))
        self.walk_queue_size = max(1000, int(ctx.config.get("walk_queue_size", 20000)))
        self.exclude_names = set(
            str(x).strip() for x in (ctx.config.get("exclude_names", ["metadata", ".ff_trash"]) or []) if str(x).strip()
        )
        self.exclude_names.add(".ff_trash")  # 回收站目录永不参与索引

    # ------------------------------------------------------------------
    # 建表 / 初始化
    # ------------------------------------------------------------------
    async def init_db(self):
        for stmt in _SCHEMA_STATEMENTS:
            st = stmt.strip()
            if st:
                await self.db.execute(self.db_path, st)
        await self._ensure_trash_columns()
        await self._sync_fts_backfill()
        self.log.info("file_finder 数据库表结构已就绪")

    async def _ensure_trash_columns(self):
        """幂等迁移：files 表加回收站标记列（trashed / trashed_at）"""
        cols = await self.db.fetch_all(self.db_path, "PRAGMA table_info(files)")
        names = {c["name"] for c in cols}
        if "trashed" not in names:
            await self.db.execute(
                self.db_path, "ALTER TABLE files ADD COLUMN trashed INTEGER NOT NULL DEFAULT 0"
            )
            await self.db.execute(
                self.db_path, "ALTER TABLE files ADD COLUMN trashed_at REAL NOT NULL DEFAULT 0"
            )
            await self.db.execute(
                self.db_path, "CREATE INDEX IF NOT EXISTS idx_files_trashed ON files(trashed, trashed_at)"
            )
            self.log.info("files 表已迁移：新增 trashed / trashed_at 列（回收站）")

    async def _sync_fts_backfill(self):
        """FTS 与 files 行数不一致 / 索引异常时重建（首次升级、意外漂移、损坏兜底）"""
        probe = None
        try:
            fts_n = await self.db.fetch_val(self.db_path, "SELECT COUNT(*) FROM files_fts", default=-1)
            files_n = await self.db.fetch_val(self.db_path, "SELECT COUNT(*) FROM files", default=-1)
            if fts_n is not None and files_n is not None and int(fts_n or 0) == int(files_n or 0):
                # 行数一致但索引可能损坏：轻量探活（MATCH 一个常见词）
                probe = await self.db.fetch_val(
                    self.db_path,
                    "SELECT COUNT(*) FROM files_fts WHERE files_fts MATCH 'json'",
                    default=-1,
                )
                if probe is not None and int(probe or 0) >= 0:
                    return
            self.log.info(
                f"FTS 索引需重建（fts={fts_n} files={files_n} probe={probe}）"
            )
        except Exception as e:
            self.log.warning(f"FTS 索引异常（{e}），将重建")
        await self._rebuild_fts()
        self.log.info("FTS 索引重建完成")

    async def _rebuild_fts(self):
        """删除并重建 FTS 虚表 + 触发器 + 回填（损坏恢复）"""
        for t in ("files_fts_ai", "files_fts_ad", "files_fts_au"):
            await self.db.execute(self.db_path, f"DROP TRIGGER IF EXISTS {t}")
        await self.db.execute(self.db_path, "DROP TABLE IF EXISTS files_fts")
        await self.db.execute(
            self.db_path,
            """
            CREATE VIRTUAL TABLE files_fts USING fts5(
                name, rel_path,
                tokenize = 'trigram',
                content = 'files',
                content_rowid = 'id'
            )
            """,
        )
        for t in (
            """
            CREATE TRIGGER files_fts_ai AFTER INSERT ON files BEGIN
                INSERT INTO files_fts(rowid, name, rel_path) VALUES (new.id, new.name, new.rel_path);
            END;
            """,
            """
            CREATE TRIGGER files_fts_ad AFTER DELETE ON files BEGIN
                INSERT INTO files_fts(files_fts, rowid, name, rel_path) VALUES ('delete', old.id, old.name, old.rel_path);
            END;
            """,
            """
            CREATE TRIGGER files_fts_au AFTER UPDATE OF name, rel_path ON files BEGIN
                INSERT INTO files_fts(files_fts, rowid, name, rel_path) VALUES ('delete', old.id, old.name, old.rel_path);
                INSERT INTO files_fts(rowid, name, rel_path) VALUES (new.id, new.name, new.rel_path);
            END;
            """,
        ):
            await self.db.execute(self.db_path, t)
        await self.db.execute(
            self.db_path,
            "INSERT INTO files_fts(rowid, name, rel_path) SELECT id, name, rel_path FROM files",
        )

    async def seed_roots_from_config(self):
        """将配置中的默认根目录写入数据库（幂等）"""
        roots = self.ctx.config.get("roots", []) or []
        now = time.time()
        for path in roots:
            if not path or not str(path).strip():
                continue
            p = str(path).strip()
            exists = await self.db.fetch_one(
                self.db_path, "SELECT id FROM roots WHERE path=?", (p,)
            )
            if not exists:
                await self.db.execute(
                    self.db_path,
                    "INSERT INTO roots (path, display_name, enabled, created_at) VALUES (?,?,1,?)",
                    (p, os.path.basename(p.rstrip("\\/")) or p, now),
                )
                self.log.info(f"已注册默认扫描根: {p}")

    # ------------------------------------------------------------------
    # 根目录管理
    # ------------------------------------------------------------------
    async def list_roots(self) -> List[Dict[str, Any]]:
        rows = await self.db.fetch_all(
            self.db_path,
            """
            SELECT r.*,
                   (SELECT COUNT(*) FROM files f WHERE f.root_id = r.id AND f.is_dir = 0) AS file_count,
                   (SELECT COUNT(*) FROM files f WHERE f.root_id = r.id AND f.is_dir = 1) AS dir_count,
                   (SELECT COUNT(*) FROM favorites fa WHERE fa.root_id = r.id) AS fav_count,
                   (SELECT COALESCE(SUM(f.size),0) FROM files f WHERE f.root_id = r.id AND f.is_dir = 0) AS total_size
            FROM roots r
            ORDER BY r.id
            """,
        )
        return [dict(r) for r in rows]

    async def get_root(self, root_id: int) -> Optional[Dict[str, Any]]:
        row = await self.db.fetch_one(self.db_path, "SELECT * FROM roots WHERE id=?", (root_id,))
        return dict(row) if row else None

    async def get_root_by_path(self, path: str) -> Optional[Dict[str, Any]]:
        row = await self.db.fetch_one(self.db_path, "SELECT * FROM roots WHERE path=?", (path,))
        return dict(row) if row else None

    async def add_root(self, path: str, display_name: str = "") -> Dict[str, Any]:
        path = str(path).strip().rstrip("\\/")
        if not path:
            raise ValueError("路径不能为空")
        exists = await self.get_root_by_path(path)
        if exists:
            return exists
        if not os.path.exists(path):
            raise ValueError(f"路径不存在或不可访问: {path}")
        if not os.path.isdir(path):
            raise ValueError(f"路径不是目录: {path}")
        now = time.time()
        new_id = await self.db.insert(
            self.db_path,
            "INSERT INTO roots (path, display_name, enabled, created_at) VALUES (?,?,1,?)",
            (path, display_name or os.path.basename(path.rstrip("\\/")) or path, now),
        )
        self.log.info(f"新增扫描根 #{new_id}: {path}")
        return await self.get_root(new_id)

    async def remove_root(self, root_id: int) -> bool:
        root = await self.get_root(root_id)
        if not root:
            return False
        await self.db.execute(self.db_path, "DELETE FROM favorites WHERE root_id=?", (root_id,))
        await self.db.execute(self.db_path, "DELETE FROM files WHERE root_id=?", (root_id,))
        await self.db.execute(self.db_path, "DELETE FROM roots WHERE id=?", (root_id,))
        self.log.info(f"已删除扫描根 #{root_id}: {root['path']}")
        return True

    async def set_root_enabled(self, root_id: int, enabled: bool) -> Optional[Dict[str, Any]]:
        if not await self.get_root(root_id):
            return None
        await self.db.execute(
            self.db_path, "UPDATE roots SET enabled=? WHERE id=?", (1 if enabled else 0, root_id)
        )
        return await self.get_root(root_id)

    async def _touch_root_scan(self, root_id: int, count: int, elapsed: float):
        await self.db.execute(
            self.db_path,
            "UPDATE roots SET last_scan_at=?, last_scan_count=?, last_scan_elapsed=? WHERE id=?",
            (time.time(), count, elapsed, root_id),
        )

    # ------------------------------------------------------------------
    # 扫描任务
    # ------------------------------------------------------------------
    async def scan_root(self, root_id: int, mode: str = "incremental") -> Optional[str]:
        """启动后台扫描任务，返回 task_id（未启用 task 插件时同步执行）"""
        root = await self.get_root(root_id)
        if not root:
            raise ValueError(f"扫描根 #{root_id} 不存在")
        if not os.path.isdir(root["path"]):
            raise ValueError(f"扫描根路径不可访问: {root['path']}")
        mode = mode if mode in ("full", "incremental") else "incremental"

        if self.task_engine is None:
            await self._run_scan(root, mode, None)
            return None

        task = self.task_engine.submit(
            lambda t: self._run_scan(root, mode, t),
            name=f"扫描 {root['display_name'] or root['path']}",
            service="file_finder",
            total=100,
            stage="准备扫描",
        )
        return task.id

    # ------------------------------------------------------------------
    # 扫描执行（核心）
    # ------------------------------------------------------------------
    async def _run_scan(self, root: Dict[str, Any], mode: str, task: Optional[TaskContext]):
        root_id = root["id"]
        root_path = root["path"]
        started = time.time()
        stats = {"dirs": 0, "files": 0, "errors": 0, "pending": 1}
        out_q: "queue.Queue[Optional[object]]" = queue.Queue(maxsize=self.walk_queue_size)
        stop_event = threading.Event()

        if task:
            await task.update(stage="开始扫描", current=0, percent=1)

        # ---- 遍历线程（并行 scandir + stat）----
        def _walk():
            self._parallel_walk(root_path, stats, out_q, stop_event)
            out_q.put(None)  # 结束哨兵

        try:
            walk_fut = asyncio.create_task(asyncio.to_thread(_walk))
            # ---- 异步消费者：批量写入 ----
            await self._consume_and_write(root_id, out_q, walk_fut, stats, task, mode)
        finally:
            stop_event.set()
            # 等待遍历线程退出（通常已完成或即将完成）
            if "walk_fut" in locals():
                try:
                    await asyncio.wait_for(asyncio.shield(walk_fut), timeout=10)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass

        elapsed = time.time() - started
        total_count = stats["files"]
        await self._touch_root_scan(root_id, total_count, round(elapsed, 2))
        if task:
            await task.update(
                percent=100, current=total_count, total=total_count,
                stage=f"扫描完成，共 {total_count} 个文件（耗时 {elapsed:.1f}s）",
                detail={"elapsed": round(elapsed, 2), "errors": stats["errors"]},
            )
        self.log.info(f"扫描完成 root={root_path} files={total_count} elapsed={elapsed:.1f}s")

    def _parallel_walk(self, root_path: str, stats: Dict[str, int],
                       out_q: "queue.Queue[Optional[object]]", stop_event: threading.Event):
        """多线程并行遍历目录树，产出 (rel_path, name, parent, ext, size, mtime, is_dir) 记录"""
        dir_q: "queue.Queue[Tuple[str, str]]" = queue.Queue()
        dir_q.put((root_path, ""))
        stats["pending"] = 1
        lock = threading.Lock()

        def worker():
            while True:
                if stop_event.is_set():
                    return
                try:
                    abs_dir, rel_dir = dir_q.get(timeout=1)
                except queue.Empty:
                    with lock:
                        if stats["pending"] <= 0:
                            return
                    continue

                subdirs: List[Tuple[str, str]] = []
                records: List[_Record] = []
                try:
                    with os.scandir(abs_dir) as it:
                        for e in it:
                            if stop_event.is_set():
                                break
                            try:
                                if e.is_symlink():
                                    continue  # 跳过链接，防环
                                if e.is_dir(follow_symlinks=False):
                                    # 跳过排除目录（如记录数据 metadata），其子树整体不索引
                                    if e.name in self.exclude_names:
                                        continue
                                    subdirs.append(
                                        (e.path, f"{rel_dir}/{e.name}" if rel_dir else e.name)
                                    )
                                elif e.is_file(follow_symlinks=False):
                                    try:
                                        st = e.stat(follow_symlinks=False)
                                    except OSError:
                                        continue
                                    rel = f"{rel_dir}/{e.name}" if rel_dir else e.name
                                    records.append(
                                        (rel, e.name, rel_dir, _ext_of(e.name),
                                         st.st_size, st.st_mtime, 0)
                                    )
                            except OSError:
                                continue
                except OSError:
                    with lock:
                        stats["errors"] += 1

                # 目录自身记录（根目录除外）
                if rel_dir:
                    st = None
                    try:
                        st = os.stat(abs_dir, follow_symlinks=False)
                    except OSError:
                        pass
                    records.append(
                        (rel_dir, os.path.basename(rel_dir), os.path.dirname(rel_dir).replace("\\", "/"),
                         "", 0, st.st_mtime if st else 0, 1)
                    )

                with lock:
                    stats["dirs"] += 1
                    stats["pending"] += len(subdirs) - 1

                # 带超时的非阻塞产出：任务被取消（stop_event）时线程能及时退出
                for rec in records:
                    while True:
                        try:
                            out_q.put(rec, timeout=0.5)
                            break
                        except queue.Full:
                            if stop_event.is_set():
                                return
                    with lock:
                        stats["files"] += 1
                for s in subdirs:
                    dir_q.put(s)

        threads = [
            threading.Thread(target=worker, name=f"ff-scan-{i}", daemon=True)
            for i in range(self.scan_workers)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    async def _consume_and_write(self, root_id: int,
                                 out_q: "queue.Queue[Optional[object]]",
                                 walk_fut: asyncio.Future,
                                 stats: Dict[str, int],
                                 task: Optional[TaskContext],
                                 mode: str):
        """消费记录队列，按模式增量/全量写入数据库"""
        batch: List[tuple] = []
        inserted = updated = deleted = 0
        processed_since_yield = 0

        if mode == "full":
            rc = await self.db.execute(self.db_path, "DELETE FROM files WHERE root_id=?", (root_id,))
            self.log.info(f"full 扫描已清空旧索引 root_id={root_id} 行数={rc}")
        else:
            existing = await self._load_existing(root_id)
            changed = []  # (id, new_size, new_mtime, new_indexed_at)
            collected: set = set()

        def stats_percent() -> float:
            denom = stats["dirs"] + stats["pending"]
            if denom <= 0:
                return 1.0
            return min(94.0, max(1.0, stats["dirs"] / denom * 94.0))

        while True:
            if walk_fut.done() and out_q.empty():
                break
            try:
                rec = out_q.get_nowait()
            except queue.Empty:
                # 非阻塞轮询：主动让出事件循环，避免阻塞 HTTP 等其他协程
                await asyncio.sleep(0.01)
                if task:
                    await task.update(current=stats["files"], percent=stats_percent())
                continue
            if rec is None:
                continue

            rel, name, parent, ext, size, mtime, is_dir = rec
            if mode == "incremental":
                collected.add(rel)
                old = existing.get(rel)
                if old is None:
                    batch.append((root_id, rel, name, parent, ext, size, mtime, is_dir, time.time()))
                    inserted += 1
                elif old[1] != size or old[2] != mtime or old[3] != is_dir:
                    changed.append((size, mtime, time.time(), old[0]))
                    updated += 1
            else:
                batch.append((root_id, rel, name, parent, ext, size, mtime, is_dir, time.time()))
                inserted += 1

            if len(batch) >= 2000:
                await self.db.execute_many(self.db_path, _INSERT_SQL, batch)
                batch.clear()
                if task:
                    await task.update(current=stats["files"], percent=stats_percent())
            else:
                processed_since_yield += 1
                if processed_since_yield >= 500:
                    processed_since_yield = 0
                    await asyncio.sleep(0)  # 让出事件循环，保持 HTTP 响应及时

        # 收尾写库
        if batch:
            await self.db.execute_many(self.db_path, _INSERT_SQL, batch)
            batch.clear()

        if mode == "incremental":
            # 更新变更行
            if changed:
                await self.db.execute_many(
                    self.db_path,
                    "UPDATE files SET size=?, mtime=?, indexed_at=? WHERE id=?",
                    changed,
                )
            # 删除磁盘上已不存在的行（增量同步的核心价值：不重扫也能保持准确）
            # 注意：回收站条目（trashed=1）物理位置已移到 .ff_trash，不作为“缺失”删除
            missing_ids = []
            for rel, old in existing.items():
                if rel not in collected and not old[4]:
                    missing_ids.append(old[0])
            if missing_ids:
                for i in range(0, len(missing_ids), 2000):
                    chunk = missing_ids[i:i + 2000]
                    placeholders = ",".join("?" * len(chunk))
                    deleted += await self.db.execute(
                        self.db_path, f"DELETE FROM files WHERE id IN ({placeholders})", tuple(chunk)
                    )

        if task:
            await task.update(
                current=stats["files"], total=stats["files"],
                percent=95, stage=f"写入数据库完成（新增 {inserted} / 更新 {updated} / 删除 {deleted}）",
            )
        self.log.info(f"索引写入完成 mode={mode} 新增={inserted} 更新={updated} 删除={deleted}")

    async def _load_existing(self, root_id: int) -> Dict[str, Tuple[int, int, float, int, int]]:
        """加载指定根目录现有索引: rel_path -> (id, size, mtime, is_dir, trashed)"""
        rows = await self.db.fetch_all(
            self.db_path,
            "SELECT id, rel_path, size, mtime, is_dir, trashed FROM files WHERE root_id=?",
            (root_id,),
        )
        return {r["rel_path"]: (r["id"], r["size"], r["mtime"], r["is_dir"], r["trashed"]) for r in rows}
