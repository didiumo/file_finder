"""
file_finder 服务入口
====================
Everything 风格的局域网文件索引与整理服务：
- 多线程扫描局域网共享目录并建立 SQLite 索引
- Web 端即时搜索（虚拟滚动展示）
- 收藏 → 整理 → 清理 的完整保留流程
"""
from fastapi import APIRouter

from .routers.api_router import setup_api_router


async def start(ctx):
    """服务启动入口（框架唯一约定）"""
    log = ctx.plugins["logger"].get_logger(ctx.service_name)
    log.info(f"[file_finder] 正在启动...")

    audit2 = ctx.plugins.get("audit_v2")
    if audit2 is not None and hasattr(audit2, "set_context"):
        audit2.set_context(ctx)

    main_router = APIRouter()
    main_router.include_router(await setup_api_router(ctx))

    app = ctx.plugins.get("web_app")
    if app:
        app.include_router(main_router)
        log.info(f"[file_finder] 路由挂载完成，界面: /ui/{ctx.service_name}/")
    else:
        log.error("[file_finder] 未获取到 web_app 插件实例")

    log.info(f"[file_finder] 服务加载完成")
