"""
file_finder 搜索与统计
=====================
基于 SQLite 索引的即时搜索：
- 文件名 / 路径 子串匹配（LIKE，自动转义通配符）
- 正则表达式匹配（regex=1，Python re 层过滤，配合分页）
- 目录参与搜索（include_dirs 默认开启，everything 风格）
- 目录范围限定（prefix：在某目录内搜索，含其子树）
- 支持扩展名、大小区间、修改时间区间、仅收藏等过滤
- 走 db_v2 只读连接池，搜索与扫描可并发互不阻塞
- 排序稳定（name/size/mtime + id 兜底），支持翻页
"""
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

_BASE_SELECT = """
SELECT f.id, f.root_id, f.rel_path, f.name, f.parent_dir, f.ext,
       f.size, f.mtime, f.is_dir, f.indexed_at, f.trashed,
       r.path AS root_path, r.display_name AS root_name,
       EXISTS(SELECT 1 FROM favorites fa
              WHERE fa.root_id = f.root_id AND fa.rel_path = f.rel_path) AS favorite
FROM files f
JOIN roots r ON r.id = f.root_id
WHERE r.enabled = 1
"""


def _escape_like(text: str) -> str:
    """转义 LIKE 通配符（配合 ESCAPE '\\' 使用）"""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class SearchLogic:
    def __init__(self, ctx):
        self.ctx = ctx
        self.db = ctx.plugins["db_v2"]
        self.db_path = str(ctx.data.get_path("file_finder.db"))
        self.log = ctx.plugins["logger"].get_logger(ctx.service_name)

    # ------------------------------------------------------------------
    # 搜索
    # ------------------------------------------------------------------
    async def search(
        self,
        q: str = "",
        root_id: Optional[int] = None,
        ext: Optional[str] = None,
        size_min: Optional[int] = None,
        size_max: Optional[int] = None,
        date_from: Optional[float] = None,
        date_to: Optional[float] = None,
        fav_only: bool = False,
        include_dirs: bool = True,
        regex: bool = False,
        prefix: Optional[str] = None,
        sort: str = "name",
        order: str = "asc",
        page: int = 1,
        page_size: int = 300,
        after_name: Optional[Any] = None,
        after_size: Optional[int] = None,
        after_mtime: Optional[float] = None,
        after_ext: Optional[str] = None,
        after_path: Optional[str] = None,
        after_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        where: List[str] = ["f.trashed = 0"]
        params: List[Any] = []

        q = (q or "").strip()
        regex = bool(regex)
        # 正则模式下 q 不走 FTS/LIKE，改为 Python re 层过滤（见下方正则分支）
        if q and not regex:
            if len(q) >= 3:
                # FTS5 trigram：任意子串匹配（大小写不敏感），毫秒级
                fts_q = q.replace('"', '""')
                where.append(
                    "f.id IN (SELECT rowid FROM files_fts WHERE files_fts MATCH ?)"
                )
                params.append(f'"{fts_q}"')
            else:
                # 短词（1~2 字符）trigram 无法匹配，回退 LIKE（命中多时早停，够快）
                esc = _escape_like(q)
                like = f"%{esc}%"
                where.append("(f.name LIKE ? ESCAPE '\\' OR f.rel_path LIKE ? ESCAPE '\\')")
                params.extend([like, like])
        if root_id is not None:
            where.append("f.root_id = ?")
            params.append(root_id)
        if prefix:
            # 在某目录内搜索：目录自身 + 整个子树（everything 的“进入文件夹搜索”）
            prefix = str(prefix).strip().strip("/")
            if prefix:
                esc = _escape_like(prefix)
                where.append(
                    "(f.rel_path = ? OR f.rel_path LIKE ? ESCAPE '\\')"
                )
                params.extend([prefix, f"{prefix}/%"])
        if not include_dirs:
            where.append("f.is_dir = 0")
        if ext:
            if str(ext).strip().lower() in ("__dirs__", "dirs"):
                # 特殊类型「文件夹」：只显示目录
                where.append("f.is_dir = 1")
            else:
                exts = [e.strip().lstrip(".").lower() for e in ext.split(",") if e.strip()]
                if exts:
                    where.append(f"f.ext IN ({','.join('?' * len(exts))})")
                    params.extend(exts)
        if size_min is not None:
            where.append("f.size >= ?")
            params.append(size_min)
        if size_max is not None:
            where.append("f.size <= ?")
            params.append(size_max)
        if date_from is not None:
            where.append("f.mtime >= ?")
            params.append(date_from)
        if date_to is not None:
            where.append("f.mtime <= ?")
            params.append(date_to)
        if fav_only:
            where.append("EXISTS(SELECT 1 FROM favorites fa WHERE fa.root_id = f.root_id AND fa.rel_path = f.rel_path)")

        page = max(1, int(page))
        page_size = max(1, min(2000, int(page_size)))

        # 正则模式：候选全量（应用除 q 外的过滤）→ Python re 匹配 → 内存分页
        if regex and q:
            try:
                compiled = re.compile(q, re.IGNORECASE)
            except re.error as e:
                raise ValueError(f"正则表达式无效: {e}")
            base_where = " AND ".join(where) if where else "1=1"
            cand_rows = await self.db.fetch_all(
                self.db_path,
                f"SELECT f.id, f.name, f.rel_path FROM files f JOIN roots r ON r.id = f.root_id "
                f"WHERE r.enabled = 1 AND {base_where}",
                tuple(params),
            )
            matched: List[Tuple[int, str, str]] = []
            for r in cand_rows:
                nm, rp = r["name"], r["rel_path"]
                if compiled.search(nm) or compiled.search(rp):
                    matched.append((r["id"], nm, rp))
            total = len(matched)
            offset = (page - 1) * page_size
            page_ids = [m[0] for m in matched[offset:offset + page_size]]
            items: List[Dict[str, Any]] = []
            if page_ids:
                rows = await self.db.fetch_all(
                    self.db_path,
                    f"{_BASE_SELECT} AND f.id IN ({','.join('?' * len(page_ids))})",
                    tuple(page_ids),
                )
                by_id = {r["id"]: dict(r) for r in rows}
                items = [self._to_item(by_id[i]) for i in page_ids if i in by_id]
            return {
                "total": total,
                "page": page,
                "page_size": page_size,
                "has_more": offset + len(items) < total,
                "items": items,
                "next_cursor": None,
            }

        sort_col = {
            "name": "f.name", "size": "f.size", "mtime": "f.mtime",
            "ext": "f.ext", "path": "f.rel_path",
        }.get(sort, "f.name")
        sort_field = {"name": "name", "size": "size", "mtime": "mtime", "ext": "ext", "path": "rel_path"}.get(sort, "name")
        order_sql = "DESC" if str(order).lower() == "desc" else "ASC"

        # 游标分页：跳过 OFFSET 全扫描，深翻页 O(页大小)
        after_val = {
            "name": after_name, "size": after_size, "mtime": after_mtime,
            "ext": after_ext, "path": after_path,
        }.get(sort)
        offset = None
        if after_val is not None and after_id is not None:
            if order_sql == "ASC":
                where.append(f"({sort_col} > ? OR ({sort_col} = ? AND f.id > ?))")
            else:
                where.append(f"({sort_col} < ? OR ({sort_col} = ? AND f.id > ?))")
            params.extend([after_val, after_val, after_id])
        else:
            offset = (page - 1) * page_size

        where_sql = " AND ".join(where) if where else "1=1"

        total = await self.db.fetch_val(
            self.db_path,
            f"SELECT COUNT(*) FROM files f JOIN roots r ON r.id = f.root_id WHERE r.enabled = 1 AND {where_sql}",
            tuple(params),
            default=0,
        )

        limit_sql = f"LIMIT {page_size}"
        offset_sql = "" if offset is None else f"OFFSET {offset}"
        rows = await self.db.fetch_all(
            self.db_path,
            f"{_BASE_SELECT} AND {where_sql} ORDER BY {sort_col} {order_sql}, f.id ASC {limit_sql} {offset_sql}",
            tuple(params),
        )
        items = [self._to_item(dict(r)) for r in rows]
        next_cursor = None
        if items:
            next_cursor = {f"after_{sort}": items[-1][sort_field], "after_id": items[-1]["id"]}
        return {
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
            "has_more": len(items) >= page_size,
            "items": items,
            "next_cursor": next_cursor,
        }

    @staticmethod
    def _to_item(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "root_id": row["root_id"],
            "rel_path": row["rel_path"],
            "name": row["name"],
            "parent_dir": row["parent_dir"],
            "ext": row["ext"],
            "size": row["size"],
            "mtime": row["mtime"],
            "is_dir": bool(row["is_dir"]),
            "root_path": row["root_path"],
            "root_name": row["root_name"],
            "favorite": bool(row["favorite"]),
            "trashed": bool(row.get("trashed", 0)),
        }

    # ------------------------------------------------------------------
    # 文件详情 / 定位
    # ------------------------------------------------------------------
    async def get_file(self, file_id: int) -> Optional[Dict[str, Any]]:
        row = await self.db.fetch_one(
            self.db_path,
            f"{_BASE_SELECT} AND f.id = ?",
            (file_id,),
        )
        return self._to_item(dict(row)) if row else None

    async def resolve_path(self, root_id: int, rel_path: str) -> Optional[Dict[str, Any]]:
        """按 (root_id, rel_path) 定位文件行"""
        row = await self.db.fetch_one(
            self.db_path,
            f"{_BASE_SELECT} AND f.root_id = ? AND f.rel_path = ?",
            (root_id, rel_path),
        )
        return self._to_item(dict(row)) if row else None

    # ------------------------------------------------------------------
    # 删除
    # （删除统一走回收站：物理移动到 <root>/.ff_trash/ + 标记 trashed，见 trash_logic）
    # ------------------------------------------------------------------
    @staticmethod
    def _abs_path(root_path: str, rel_path: str) -> str:
        root = root_path.rstrip("\\/")
        return os.path.join(root, rel_path.replace("/", os.sep))

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------
    async def stats(self) -> Dict[str, Any]:
        rows = await self.db.fetch_all(
            self.db_path,
            """
            SELECT r.id, r.path, r.display_name, r.enabled, r.last_scan_at,
                   r.last_scan_count, r.last_scan_elapsed,
                   (SELECT COUNT(*) FROM files f WHERE f.root_id = r.id AND f.is_dir = 0 AND f.trashed = 0) AS file_count,
                   (SELECT COUNT(*) FROM files f WHERE f.root_id = r.id AND f.is_dir = 1 AND f.trashed = 0) AS dir_count,
                   (SELECT COUNT(*) FROM favorites fa WHERE fa.root_id = r.id) AS fav_count,
                   (SELECT COALESCE(SUM(f.size),0) FROM files f WHERE f.root_id = r.id AND f.is_dir = 0) AS total_size
            FROM roots r ORDER BY r.id
            """,
        )
        roots = [dict(r) for r in rows]
        global_row = await self.db.fetch_one(
            self.db_path,
            """
            SELECT COUNT(*) AS files,
                   COALESCE(SUM(CASE WHEN is_dir=0 THEN size ELSE 0 END),0) AS bytes,
                   COUNT(DISTINCT root_id) AS roots
            FROM files WHERE trashed = 0
            """,
        )
        fav_row = await self.db.fetch_one(
            self.db_path, "SELECT COUNT(*) AS n FROM favorites"
        )
        now = time.time()
        return {
            "roots": roots,
            "total_files": (global_row or {}).get("files", 0),
            "total_bytes": (global_row or {}).get("bytes", 0),
            "total_favorites": (fav_row or {}).get("n", 0),
            "server_time": now,
        }
