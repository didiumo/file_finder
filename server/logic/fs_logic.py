"""
file_finder 文件系统浏览（fs）
============================
类 Windows 资源管理器的按需目录浏览：
- 实时 os.scandir 读盘，**不触发、不依赖全量索引扫描**（文件夹是“多出来的内容”）
- 只允许浏览已配置扫描根（enabled roots）内的路径，realpath 前缀护栏防越界
- 目录优先排序（everything/资源管理器风格），键集分页（目录少时等价 OFFSET）
- 每项尝试与索引关联（root_id + rel_path 命中则携带 files.id，
  未索引的新文件 id=null，预览时提示“未索引”）
"""
import os
from typing import Any, Dict, List, Optional, Tuple


class FsLogic:
    def __init__(self, ctx):
        self.ctx = ctx
        self.db = ctx.plugins["db_v2"]
        self.db_path = str(ctx.data.get_path("file_finder.db"))
        self.log = ctx.plugins["logger"].get_logger(ctx.service_name)
        # 与扫描器保持一致：排除目录（如记录数据 metadata、回收站 .ff_trash）在浏览时不展示、不可进入
        self.exclude_names = set(
            str(x).strip() for x in (ctx.config.get("exclude_names", ["metadata", ".ff_trash"]) or []) if str(x).strip()
        )
        self.exclude_names.add(".ff_trash")

    # ------------------------------------------------------------------
    # 路径护栏
    # ------------------------------------------------------------------
    async def _resolve_root(self, abs_path: str) -> Optional[Tuple[Dict[str, Any], str]]:
        """判断 abs_path 属于哪个已启用扫描根，返回 (root, 根内相对路径 rel='' 表示根本身)"""
        rows = await self.db.fetch_all(
            self.db_path,
            "SELECT * FROM roots WHERE enabled=1 ORDER BY id",
        )
        ap = os.path.abspath(os.path.realpath(abs_path))
        for r in rows:
            root = dict(r)
            rp = os.path.abspath(os.path.realpath(root["path"]))
            if ap == rp:
                return root, ""
            if ap.startswith(rp + os.sep):
                rel = os.path.relpath(ap, rp).replace(os.sep, "/")
                return root, rel
        return None

    # ------------------------------------------------------------------
    # 目录列举
    # ------------------------------------------------------------------
    async def list_dir(
        self,
        path: str,
        page: int = 1,
        page_size: int = 300,
        sort: str = "name",
        order: str = "asc",
        after_dir: Optional[int] = None,
        after_sort_val: Optional[Any] = None,
        after_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        resolved = await self._resolve_root(path)
        if not resolved:
            raise ValueError("路径不在已配置的扫描根范围内")
        root, rel = resolved

        # 实时读盘
        entries: List[Tuple[str, bool, int, float]] = []
        try:
            with os.scandir(path) as it:
                for e in it:
                    if e.name in self.exclude_names:
                        continue
                    try:
                        is_dir = e.is_dir(follow_symlinks=False)
                        st = e.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    entries.append((e.name, is_dir, st.st_size, st.st_mtime))
        except OSError as e:
            raise ValueError(f"无法读取目录：{e}")

        # 目录优先 + 排序字段（name/size/mtime；降序时目录块与文件块各自反向）
        desc = str(order).lower() == "desc"
        sort_field = {"name": 0, "size": 2, "mtime": 3}.get(sort, 0)

        def sort_fn(e):
            return (0 if e[1] else 1, e[sort_field], e[0].lower())

        entries.sort(key=sort_fn)
        if desc:
            dirs = sorted([x for x in entries if x[1]], key=lambda x: (x[sort_field], x[0].lower()), reverse=True)
            files = sorted([x for x in entries if not x[1]], key=lambda x: (x[sort_field], x[0].lower()), reverse=True)
            entries = dirs + files

        total = len(entries)
        page = max(1, int(page))
        page_size = max(1, min(2000, int(page_size)))

        # 键集分页（目录优先排序下的 (is_dir, sort_val, name) 游标）
        if after_name is not None:
            after_dir_b = bool(int(after_dir or 0))
            if sort_field == 0:
                a_val = (after_sort_val or "").lower()
            elif sort_field == 2:
                a_val = int(after_sort_val or 0)
            else:
                a_val = float(after_sort_val or 0)
            start = None
            for i, (nm, is_dir, sz, mt) in enumerate(entries):
                k = (0 if is_dir else 1, (nm if sort_field == 0 else (sz if sort_field == 2 else mt)), nm.lower())
                a = (0 if after_dir_b else 1, a_val, after_name.lower())
                if k > a:
                    start = i
                    break
            if start is None:
                start = total
        else:
            start = (page - 1) * page_size
        page_entries = entries[start:start + page_size]

        # 索引 id 关联（一次 IN 查询）
        ids = await self._lookup_ids(root["id"], rel, [e[0] for e in page_entries])

        items = []
        for name, is_dir, size, mtime in page_entries:
            child_rel = f"{rel}/{name}" if rel else name
            fid = ids.get(name)
            items.append({
                "id": fid,
                "root_id": root["id"],
                "root_path": root["path"],
                "root_name": root["display_name"],
                "rel_path": child_rel,
                "name": name,
                "parent_dir": rel,
                "ext": os.path.splitext(name)[1].lstrip(".").lower(),
                "size": size,
                "mtime": mtime,
                "is_dir": is_dir,
                "indexed": fid is not None,
            })

        next_cursor = None
        if items and start + len(items) < total:
            last = items[-1]
            sv = last["name"] if sort_field == 0 else (last["size"] if sort_field == 2 else last["mtime"])
            next_cursor = {"after_dir": 1 if last["is_dir"] else 0, "after_sort_val": sv, "after_name": last["name"]}

        return {
            "path": os.path.abspath(path),
            "root_id": root["id"],
            "root_path": root["path"],
            "root_name": root["display_name"],
            "rel_path": rel,
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": start + len(items) < total,
            "items": items,
            "next_cursor": next_cursor,
        }

    async def _lookup_ids(self, root_id: int, rel: str, names: List[str]) -> Dict[str, Optional[int]]:
        """按 (root_id, rel_path) 批量查索引 id"""
        if not names:
            return {}
        rel_paths = [f"{rel}/{n}" if rel else n for n in names]
        marks = ",".join("?" * len(rel_paths))
        rows = await self.db.fetch_all(
            self.db_path,
            f"SELECT rel_path, id FROM files WHERE root_id=? AND rel_path IN ({marks})",
            (root_id, *rel_paths),
        )
        return {r["rel_path"].rsplit("/", 1)[-1]: r["id"] for r in rows}
