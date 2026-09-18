"""
file_finder 搜索与统计
=====================
基于 SQLite 索引的即时搜索：
- 文件名 / 路径 子串匹配（LIKE，自动转义通配符）
- 支持扩展名、大小区间、修改时间区间、仅收藏、是否含目录等过滤
- 走 db_v2 只读连接池，搜索与扫描可并发互不阻塞
- 排序稳定（name/size/mtime + id 兜底），支持翻页
"""
import os
import time
from typing import Any, Dict, List, Optional, Tuple

_BASE_SELECT = """
SELECT f.id, f.root_id, f.rel_path, f.name, f.parent_dir, f.ext,
       f.size, f.mtime, f.is_dir, f.indexed_at,
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
        include_dirs: bool = False,
        sort: str = "name",
        order: str = "asc",
        page: int = 1,
        page_size: int = 300,
    ) -> Dict[str, Any]:
        where: List[str] = []
        params: List[Any] = []

        q = (q or "").strip()
        if q:
            esc = _escape_like(q)
            like = f"%{esc}%"
            where.append("(f.name LIKE ? ESCAPE '\\' OR f.rel_path LIKE ? ESCAPE '\\')")
            params.extend([like, like])
        if root_id is not None:
            where.append("f.root_id = ?")
            params.append(root_id)
        if not include_dirs:
            where.append("f.is_dir = 0")
        if ext:
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

        where_sql = " AND ".join(where) if where else "1=1"
        sort_col = {"name": "f.name", "size": "f.size", "mtime": "f.mtime"}.get(sort, "f.name")
        order_sql = "DESC" if str(order).lower() == "desc" else "ASC"
        page = max(1, int(page))
        page_size = max(1, min(2000, int(page_size)))
        offset = (page - 1) * page_size

        total = await self.db.fetch_val(
            self.db_path,
            f"SELECT COUNT(*) FROM files f JOIN roots r ON r.id = f.root_id WHERE r.enabled = 1 AND {where_sql}",
            tuple(params),
            default=0,
        )

        rows = await self.db.fetch_all(
            self.db_path,
            f"{_BASE_SELECT} AND {where_sql} ORDER BY {sort_col} {order_sql}, f.id ASC LIMIT ? OFFSET ?",
            tuple(params) + (page_size, offset),
        )
        items = [self._to_item(dict(r)) for r in rows]
        return {
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
            "has_more": offset + len(items) < int(total or 0),
            "items": items,
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
    # ------------------------------------------------------------------
    async def delete_files(self, ids: List[int]) -> Dict[str, Any]:
        """删除文件（磁盘 + 索引 + 收藏快照）"""
        deleted_disk = 0
        missing = 0
        for fid in ids:
            item = await self.get_file(fid)
            if not item or item["is_dir"]:
                continue
            await self._delete_one(item)
            deleted_disk += 1
        return {"deleted": deleted_disk, "missing": missing}

    async def _delete_one(self, item: Dict[str, Any]):
        """删除单个文件行对应的磁盘文件并清理索引/收藏"""
        full_path = self._abs_path(item["root_path"], item["rel_path"])
        if os.path.isfile(full_path):
            try:
                os.remove(full_path)
            except OSError as e:
                self.log.warning(f"删除磁盘文件失败 {full_path}: {e}")
        await self.db.execute(
            self.db_path,
            "DELETE FROM favorites WHERE root_id=? AND rel_path=?",
            (item["root_id"], item["rel_path"]),
        )
        await self.db.execute(
            self.db_path, "DELETE FROM files WHERE id=?", (item["id"],)
        )

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
                   (SELECT COUNT(*) FROM files f WHERE f.root_id = r.id AND f.is_dir = 0) AS file_count,
                   (SELECT COUNT(*) FROM files f WHERE f.root_id = r.id AND f.is_dir = 1) AS dir_count,
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
            FROM files
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
