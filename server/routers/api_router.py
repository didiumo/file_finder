"""
file_finder API 路由
====================
统一挂载到 /api/file_finder：
- 响应统一走 response_v2（浏览器 Accept: application/json 自动协商为 JSON）
- 写操作通过 audit_v2 记录审计
- 预览/下载/缩略图等二进制接口直接返回原生响应
"""
from typing import List, Optional

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import Response

from plugins.audit_v2 import AuditRecord

from ..logic.indexer_logic import IndexerLogic
from ..logic.search_logic import SearchLogic
from ..logic.favorite_logic import FavoriteLogic
from ..logic.preview_logic import PreviewLogic
from ..logic.collection_logic import CollectionLogic


async def setup_api_router(ctx) -> APIRouter:
    log = ctx.plugins["logger"].get_logger(ctx.service_name)
    res2 = ctx.plugins.get("response_v2") or ctx.plugins["response"]
    audit2 = ctx.plugins.get("audit_v2")
    task_engine = ctx.plugins.get("task")
    api_prefix = ctx.config.get("api_prefix", f"/api/{ctx.service_name}")

    indexer = IndexerLogic(ctx)
    await indexer.init_db()
    await indexer.seed_roots_from_config()
    search = SearchLogic(ctx)
    favorites = FavoriteLogic(ctx)
    preview = PreviewLogic(ctx)
    collect = CollectionLogic(ctx, indexer, favorites)

    router = APIRouter(prefix=api_prefix, tags=["file_finder"])

    async def audit(action: str, request: Request, detail=None, status="success", code=200):
        if audit2 is None:
            return
        try:
            await audit2.record(
                AuditRecord(action=action, status=status, code=code, detail=detail),
                request=request,
            )
        except Exception:
            pass

    # ==================================================================
    # 扫描根目录管理
    # ==================================================================
    @router.get("/roots")
    async def api_roots(request: Request):
        return res2.data(await indexer.list_roots(), request=request)

    @router.post("/roots")
    async def api_add_root(request: Request, body: dict = Body(...)):
        try:
            root = await indexer.add_root(body.get("path", ""), body.get("display_name", ""))
            await audit("roots.add", request, {"path": root["path"]})
            return res2.data(root, msg="根目录已添加", request=request)
        except ValueError as e:
            return res2.error(str(e), code=400, request=request)

    @router.delete("/roots/{root_id}")
    async def api_remove_root(root_id: int, request: Request):
        ok = await indexer.remove_root(root_id)
        if not ok:
            return res2.error(f"根目录 #{root_id} 不存在", code=404, request=request)
        await audit("roots.remove", request, {"root_id": root_id})
        return res2.data({"root_id": root_id}, msg="根目录已删除", request=request)

    @router.post("/roots/{root_id}/enable")
    async def api_set_root_enabled(root_id: int, request: Request, body: dict = Body(...)):
        root = await indexer.set_root_enabled(root_id, bool(body.get("enabled", True)))
        if not root:
            return res2.error(f"根目录 #{root_id} 不存在", code=404, request=request)
        await audit("roots.enable", request, {"root_id": root_id, "enabled": root["enabled"]})
        return res2.data(root, request=request)

    @router.post("/roots/{root_id}/scan")
    async def api_scan_root(root_id: int, request: Request, body: dict = Body(default={})):
        try:
            task_id = await indexer.scan_root(root_id, body.get("mode", "incremental"))
            await audit("roots.scan", request, {"root_id": root_id, "task_id": task_id})
            return res2.data({"task_id": task_id}, msg="扫描任务已启动", request=request)
        except ValueError as e:
            return res2.error(str(e), code=400, request=request)

    # ==================================================================
    # 文件搜索 / 详情 / 删除
    # ==================================================================
    @router.get("/search")
    async def api_search(
        request: Request,
        q: str = Query(""),
        root_id: Optional[int] = Query(None),
        ext: Optional[str] = Query(None),
        size_min: Optional[int] = Query(None),
        size_max: Optional[int] = Query(None),
        date_from: Optional[float] = Query(None),
        date_to: Optional[float] = Query(None),
        fav_only: bool = Query(False),
        include_dirs: bool = Query(False),
        sort: str = Query("name"),
        order: str = Query("asc"),
        page: int = Query(1),
        page_size: int = Query(300),
    ):
        return res2.data(
            await search.search(q, root_id, ext, size_min, size_max, date_from, date_to,
                                fav_only, include_dirs, sort, order, page, page_size),
            request=request,
        )

    @router.get("/files/{file_id}")
    async def api_get_file(file_id: int, request: Request):
        item = await search.get_file(file_id)
        if not item:
            return res2.error(f"文件 #{file_id} 不存在", code=404, request=request)
        return res2.data(item, request=request)

    @router.delete("/files/{file_id}")
    async def api_delete_file(file_id: int, request: Request):
        item = await search.get_file(file_id)
        if not item:
            return res2.error(f"文件 #{file_id} 不存在", code=404, request=request)
        if item["is_dir"]:
            return res2.error("目录不可直接删除，请使用整理/清理流程", code=400, request=request)
        await search._delete_one(item)
        await audit("files.delete", request, {"file_id": file_id, "name": item["name"]})
        return res2.data({"deleted": file_id}, msg="已删除", request=request)

    @router.post("/files/batch-delete")
    async def api_batch_delete(request: Request, body: dict = Body(...)):
        ids: List[int] = body.get("ids", []) or []
        if not ids:
            return res2.error("ids 不能为空", code=400, request=request)
        result = await search.delete_files(ids)
        await audit("files.batch_delete", request, {"count": result["deleted"]})
        return res2.data(result, msg=f"已删除 {result['deleted']} 个文件", request=request)

    # ==================================================================
    # 统计
    # ==================================================================
    @router.get("/stats")
    async def api_stats(request: Request):
        return res2.data(await search.stats(), request=request)

    # ==================================================================
    # 收藏
    # ==================================================================
    @router.get("/favorites")
    async def api_favorites(
        request: Request,
        q: str = Query(""),
        root_id: Optional[int] = Query(None),
        sort: str = Query("created_at"),
        order: str = Query("desc"),
        only_exists: Optional[bool] = Query(None),
        page: int = Query(1),
        page_size: int = Query(300),
    ):
        return res2.data(
            await favorites.list_favorites(q, sort, order, page, page_size,
                                           root_id=root_id, only_exists=only_exists),
            request=request,
        )

    @router.post("/favorites/toggle")
    async def api_fav_toggle(request: Request, body: dict = Body(...)):
        try:
            result = await favorites.toggle(int(body.get("file_id", 0)))
            await audit("favorites.toggle", request, result)
            return res2.data(result, msg="已收藏" if result["favorite"] else "已取消收藏", request=request)
        except ValueError as e:
            return res2.error(str(e), code=404, request=request)

    @router.post("/favorites/batch")
    async def api_fav_batch(request: Request, body: dict = Body(...)):
        ids: List[int] = body.get("file_ids", []) or []
        if not ids:
            return res2.error("file_ids 不能为空", code=400, request=request)
        added = await favorites.batch_add(ids)
        await audit("favorites.batch", request, {"added": added})
        return res2.data({"added": added}, msg=f"新增收藏 {added} 个", request=request)

    @router.delete("/favorites/{fav_id}")
    async def api_fav_remove(fav_id: int, request: Request):
        ok = await favorites.remove(fav_id)
        if not ok:
            return res2.error(f"收藏 #{fav_id} 不存在", code=404, request=request)
        await audit("favorites.remove", request, {"fav_id": fav_id})
        return res2.data({"fav_id": fav_id}, msg="已取消收藏", request=request)

    @router.delete("/favorites/file/{file_id}")
    async def api_fav_remove_by_file(file_id: int, request: Request):
        ok = await favorites.remove_by_file(file_id)
        if not ok:
            return res2.error(f"文件 #{file_id} 未收藏", code=404, request=request)
        await audit("favorites.remove_by_file", request, {"file_id": file_id})
        return res2.data({"file_id": file_id}, msg="已取消收藏", request=request)

    @router.post("/favorites/prune-missing")
    async def api_fav_prune(request: Request):
        n = await favorites.prune_missing()
        await audit("favorites.prune", request, {"removed": n})
        return res2.data({"removed": n}, msg=f"已清理 {n} 条失效收藏", request=request)

    # ==================================================================
    # 预览 / 缩略图 / 下载
    # ==================================================================
    @router.get("/files/{file_id}/preview-info")
    async def api_preview_info(file_id: int, request: Request):
        item = await search.get_file(file_id)
        if not item:
            return res2.error(f"文件 #{file_id} 不存在", code=404, request=request)
        return res2.data(preview.preview_info(item), request=request)

    @router.get("/files/{file_id}/preview")
    async def api_preview(file_id: int):
        item = await search.get_file(file_id)
        if not item:
            return res2.error(f"文件 #{file_id} 不存在", code=404)
        kind = preview.classify(item)
        if kind == "text":
            try:
                data = preview.read_text(item)
            except Exception as e:
                return res2.error(f"读取失败: {e}", code=500)
            return Response(
                content=data["content"],
                media_type="text/plain; charset=utf-8",
                headers={
                    "X-Preview-Encoding": data["encoding"],
                    "X-Preview-Truncated": "1" if data["truncated"] else "0",
                    "X-Preview-Kind": "text",
                },
            )
        if kind in ("image", "video"):
            return preview.raw_file(item)
        return res2.error("该类型不支持预览", code=415, status_code=415, data=preview.preview_info(item))

    @router.get("/files/{file_id}/thumb")
    async def api_thumb(file_id: int, size: int = Query(256)):
        item = await search.get_file(file_id)
        if not item:
            return res2.error(f"文件 #{file_id} 不存在", code=404)
        if preview.classify(item) != "image":
            return res2.error("非图片文件", code=415, status_code=415)
        resp = preview.image_thumbnail(item, max(32, min(1024, size)))
        if resp is None:
            return res2.error("无法生成缩略图", code=500)
        return resp

    @router.get("/files/{file_id}/download")
    async def api_download(file_id: int):
        item = await search.get_file(file_id)
        if not item or item["is_dir"]:
            return res2.error("文件不存在", code=404)
        return preview.download(item)

    # ==================================================================
    # 后台任务（扫描 / 整理清理）进度
    # ==================================================================
    @router.get("/tasks")
    async def api_tasks(request: Request):
        if task_engine is None:
            return res2.data([], request=request)
        return res2.data(task_engine.list_tasks(service="file_finder", limit=50), request=request)

    @router.get("/tasks/{task_id}")
    async def api_task_detail(task_id: str, request: Request):
        if task_engine is None:
            return res2.error("task 插件未启用", code=500, request=request)
        t = task_engine.get(task_id)
        if not t:
            return res2.error(f"任务 {task_id} 不存在", code=404, request=request)
        return res2.data(t.to_dict(), request=request)

    @router.get("/tasks/{task_id}/events")
    async def api_task_events(task_id: str):
        if task_engine is None:
            return res2.error("task 插件未启用", code=500)
        t = task_engine.get(task_id)
        if not t:
            return res2.error(f"任务 {task_id} 不存在", code=404)
        return res2.sse(t.iter_events())

    @router.post("/tasks/{task_id}/cancel")
    async def api_task_cancel(task_id: str, request: Request):
        if task_engine is None:
            return res2.error("task 插件未启用", code=500)
        ok = task_engine.cancel(task_id)
        if not ok:
            return res2.error(f"任务 {task_id} 不存在或已结束", code=404, request=request)
        await audit("tasks.cancel", request, {"task_id": task_id})
        return res2.data({"task_id": task_id}, msg="任务已取消", request=request)

    # ==================================================================
    # 收藏整理 + 清理
    # ==================================================================
    @router.get("/collect/plan")
    async def api_collect_plan(request: Request):
        try:
            return res2.data(await collect.plan(), request=request)
        except ValueError as e:
            return res2.error(str(e), code=400, request=request)

    @router.post("/collect/run")
    async def api_collect_run(request: Request, body: dict = Body(...)):
        try:
            task_id = await collect.run(
                copy=bool(body.get("copy", True)),
                cleanup=bool(body.get("cleanup", True)),
                remove_empty_roots=bool(body.get("remove_empty_roots", True)),
                confirm=bool(body.get("confirm", False)),
                root_ids=body.get("root_ids"),
            )
            await audit("collect.run", request, {
                "copy": body.get("copy"), "cleanup": body.get("cleanup"), "task_id": task_id,
            })
            return res2.data({"task_id": task_id}, msg="整理清理任务已启动", request=request)
        except ValueError as e:
            return res2.error(str(e), code=400, request=request)

    log.info(f"file_finder 路由已挂载: {api_prefix}")
    return router
