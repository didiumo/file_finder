"""
file_finder 收藏管理
===================
收藏 = 用户要「保留」的文件清单（最终整理时只保留这些）。

设计要点：
- 收藏表独立于文件索引表（快照方式）：即使文件在磁盘上被删除、索引被重建，
  收藏记录依然保留，界面可显示「文件已丢失」状态。
- 以 (root_id, rel_path) 为唯一键，与索引通过该键关联。
"""
import time
from typing import Any, Dict, List, Optional

_LIST_SQL = """
SELECT fa.id AS fav_id, fa.root_id, fa.rel_path, fa.name, fa.ext,
       fa.size AS fav_size, fa.mtime AS fav_mtime, fa.created_at,
       r.path AS root_path, r.display_name AS root_name,
       f.id AS file_id,
       CASE WHEN f.id IS NULL OR COALESCE(f.trashed, 0) = 1 THEN 0 ELSE 1 END AS exists_now,
       COALESCE(f.size, fa.size) AS size,
       COALESCE(f.mtime, fa.mtime) AS mtime
FROM favorites fa
JOIN roots r ON r.id = fa.root_id
LEFT JOIN files f ON f.root_id = fa.root_id AND f.rel_path = fa.rel_path
"""


class FavoriteLogic:
    def __init__(self, ctx):
        self.ctx = ctx
        self.db = ctx.plugins["db_v2"]
        self.db_path = str(ctx.data.get_path("file_finder.db"))
        self.log = ctx.plugins["logger"].get_logger(ctx.service_name)

    async def toggle(self, file_id: int) -> Dict[str, Any]:
        """切换收藏状态，返回 {favorite: bool}"""
        row = await self.db.fetch_one(
            self.db_path,
            "SELECT f.id, f.root_id, f.rel_path, f.name, f.size, f.mtime, f.ext "
            "FROM files f WHERE f.id=?",
            (file_id,),
        )
        if not row:
            raise ValueError(f"文件 #{file_id} 不存在")
        exist = await self.db.fetch_one(
            self.db_path,
            "SELECT id FROM favorites WHERE root_id=? AND rel_path=?",
            (row["root_id"], row["rel_path"]),
        )
        if exist:
            await self.db.execute(
                self.db_path, "DELETE FROM favorites WHERE id=?", (exist["id"],)
            )
            return {"favorite": False, "fav_id": None}
        fav_id = await self.db.insert(
            self.db_path,
            "INSERT INTO favorites (root_id, rel_path, name, size, mtime, ext, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (row["root_id"], row["rel_path"], row["name"], row["size"], row["mtime"],
             row["ext"], time.time()),
        )
        return {"favorite": True, "fav_id": fav_id}

    async def batch_add(self, file_ids: List[int]) -> int:
        """批量收藏（已收藏的自动忽略）"""
        now = time.time()
        rows = await self.db.fetch_all(
            self.db_path,
            f"SELECT id, root_id, rel_path, name, size, mtime, ext FROM files WHERE id IN ({','.join('?' * len(file_ids))})",
            tuple(file_ids),
        )
        added = 0
        for r in rows:
            exist = await self.db.fetch_one(
                self.db_path,
                "SELECT id FROM favorites WHERE root_id=? AND rel_path=?",
                (r["root_id"], r["rel_path"]),
            )
            if exist:
                continue
            await self.db.insert(
                self.db_path,
                "INSERT INTO favorites (root_id, rel_path, name, size, mtime, ext, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (r["root_id"], r["rel_path"], r["name"], r["size"], r["mtime"], r["ext"], now),
            )
            added += 1
        return added

    async def remove(self, fav_id: int) -> bool:
        res = await self.db.execute(
            self.db_path, "DELETE FROM favorites WHERE id=?", (fav_id,)
        )
        return res > 0

    async def remove_by_file(self, file_id: int) -> bool:
        row = await self.db.fetch_one(
            self.db_path, "SELECT root_id, rel_path FROM files WHERE id=?", (file_id,)
        )
        if not row:
            return False
        res = await self.db.execute(
            self.db_path,
            "DELETE FROM favorites WHERE root_id=? AND rel_path=?",
            (row["root_id"], row["rel_path"]),
        )
        return res > 0

    async def prune_missing(self) -> int:
        """清除已不存在于索引中的收藏（对应磁盘文件已丢失）"""
        res = await self.db.execute(
            self.db_path,
            """
            DELETE FROM favorites
            WHERE NOT EXISTS (
                SELECT 1 FROM files f
                WHERE f.root_id = favorites.root_id AND f.rel_path = favorites.rel_path
            )
            """,
        )
        return res

    async def list_favorites(
        self,
        q: str = "",
        sort: str = "created_at",
        order: str = "desc",
        page: int = 1,
        page_size: int = 300,
        root_id: Optional[int] = None,
        only_exists: Optional[bool] = None,
        ext: Optional[str] = None,
    ) -> Dict[str, Any]:
        where: List[str] = []
        params: List[Any] = []

        q = (q or "").strip()
        if q:
            esc = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            like = f"%{esc}%"
            where.append("(fa.name LIKE ? ESCAPE '\\' OR fa.rel_path LIKE ? ESCAPE '\\')")
            params.extend([like, like])
        if root_id is not None:
            where.append("fa.root_id = ?")
            params.append(root_id)
        if ext:
            if str(ext).strip().lower() in ("__dirs__", "dirs"):
                # 特殊类型「文件夹」：目录的扩展名快照为空
                where.append("fa.ext = ''")
            else:
                exts = [e.strip().lstrip(".").lower() for e in ext.split(",") if e.strip()]
                if exts:
                    where.append(f"fa.ext IN ({','.join('?' * len(exts))})")
                    params.extend(exts)
        if only_exists is True:
            where.append("f.id IS NOT NULL AND COALESCE(f.trashed, 0) = 0")
        elif only_exists is False:
            where.append("f.id IS NULL")

        where_sql = " AND ".join(where) if where else "1=1"
        sort_col = {
            "created_at": "fa.created_at", "name": "fa.name", "size": "COALESCE(f.size, fa.size)",
            "mtime": "COALESCE(f.mtime, fa.mtime)",
        }.get(sort, "fa.created_at")
        order_sql = "DESC" if str(order).lower() == "desc" else "ASC"
        page = max(1, int(page))
        page_size = max(1, min(2000, int(page_size)))
        offset = (page - 1) * page_size

        total = await self.db.fetch_val(
            self.db_path,
            f"SELECT COUNT(*) FROM favorites fa JOIN roots r ON r.id = fa.root_id "
            f"LEFT JOIN files f ON f.root_id = fa.root_id AND f.rel_path = fa.rel_path "
            f"WHERE {where_sql}",
            tuple(params),
            default=0,
        )
        rows = await self.db.fetch_all(
            self.db_path,
            f"{_LIST_SQL} WHERE {where_sql} ORDER BY {sort_col} {order_sql}, fa.id DESC LIMIT ? OFFSET ?",
            tuple(params) + (page_size, offset),
        )
        items = []
        for r in rows:
            d = dict(r)
            items.append({
                "fav_id": d["fav_id"],
                "root_id": d["root_id"],
                "rel_path": d["rel_path"],
                "name": d["name"],
                "ext": d["ext"],
                "size": d["size"],
                "mtime": d["mtime"],
                "created_at": d["created_at"],
                "root_path": d["root_path"],
                "root_name": d["root_name"],
                "file_id": d["file_id"],
                "exists_now": bool(d["exists_now"]),
            })
        return {
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
            "has_more": offset + len(items) < int(total or 0),
            "items": items,
        }

    async def all_favorites(self, root_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """一次性取全部收藏（供整理/清理使用）"""
        if root_id is not None:
            rows = await self.db.fetch_all(
                self.db_path, _LIST_SQL + " WHERE fa.root_id = ?", (root_id,)
            )
        else:
            rows = await self.db.fetch_all(self.db_path, _LIST_SQL)
        return [dict(r) for r in rows]

    async def count(self) -> int:
        """收藏总数（轻量）"""
        n = await self.db.fetch_val(self.db_path, "SELECT COUNT(*) FROM favorites", default=0)
        return int(n or 0)
