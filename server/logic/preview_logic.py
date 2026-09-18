"""
file_finder 预览服务
===================
支持三类预览：
1. 文本（TXT / Markdown / 代码 / JSON / 日志 …）：读取并做编码探测（UTF-8 → GBK → Latin-1）
2. 图片：原图直出 + Pillow 缩略图（本地磁盘缓存，避免反复读网络共享）
3. 视频：以 FileResponse 直出（Starlette 原生支持 HTTP Range，可拖动进度条）

压缩包 / 动态库等一律不预览（返回 previewable=false，前端显示图标与元数据）。
"""
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi.responses import FileResponse

from .common import abs_path, classify_ext, guess_mime

TEXT_EXTS = {
    "txt", "md", "markdown", "log", "json", "yaml", "yml", "ini", "conf", "cfg",
    "xml", "csv", "html", "htm", "css", "scss", "less", "js", "mjs", "cjs", "ts",
    "jsx", "tsx", "py", "pyw", "java", "c", "cpp", "cc", "h", "hpp", "cs", "go",
    "rs", "rb", "php", "sql", "sh", "bash", "bat", "cmd", "ps1", "toml", "properties",
    "sln", "csproj", "vcxproj", "gradle", "makefile", "dockerfile", "env", "gitignore",
    "xaml", "asm", "vue", "svelte", "ipynb", "diff", "patch",
}
IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "svg", "ico", "avif", "tif", "tiff"}
VIDEO_EXTS = {
    "mp4", "mkv", "webm", "mov", "avi", "flv", "wmv", "m4v", "mpg", "mpeg", "3gp",
    "ts", "m2ts", "ogv", "rmvb",
}
# 明确不预览的二进制类型（即使扩展名未知也走此集合判定）
BINARY_EXTS = {
    "zip", "rar", "7z", "tar", "gz", "bz2", "xz", "zst", "iso", "dmg", "img",
    "dll", "exe", "so", "dylib", "msi", "bin", "dat", "db", "sqlite", "sqlite3",
    "pyc", "pyd", "class", "jar", "apk", "ipa", "deb", "rpm", "pak", "unity3d",
    "assetbundle", "bundle", "resources", "meta", "cache", "pak", "uasset",
}


class PreviewLogic:
    def __init__(self, ctx):
        self.ctx = ctx
        self.db = ctx.plugins["db_v2"]
        self.db_path = str(ctx.data.get_path("file_finder.db"))
        self.log = ctx.plugins["logger"].get_logger(ctx.service_name)
        self.max_text_bytes = int(ctx.config.get("max_text_preview_bytes", 262144))
        self.thumb_size = int(ctx.config.get("thumb_size", 256))
        self.thumb_dir: Path = ctx.data.get_path(ctx.config.get("thumb_dir", "thumbs"))
        self.thumb_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 分类
    # ------------------------------------------------------------------
    def classify(self, item: Dict[str, Any]) -> str:
        """返回 text / image / video / none"""
        if item["is_dir"]:
            return "none"
        return classify_ext(item["ext"])

    def preview_info(self, item: Dict[str, Any]) -> Dict[str, Any]:
        kind = self.classify(item)
        return {
            "id": item["id"],
            "name": item["name"],
            "ext": item["ext"],
            "size": item["size"],
            "mtime": item["mtime"],
            "kind": kind,
            "previewable": kind in ("text", "image", "video"),
            "mime": guess_mime(item["name"], item["ext"], kind),
            "root_path": item["root_path"],
            "rel_path": item["rel_path"],
        }

    # ------------------------------------------------------------------
    # 文本
    # ------------------------------------------------------------------
    def read_text(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """读取文本内容（带编码探测与截断）"""
        full = abs_path(item["root_path"], item["rel_path"])
        size = item["size"]
        truncated = size > self.max_text_bytes
        read_len = self.max_text_bytes if truncated else size
        with open(full, "rb") as fp:
            raw = fp.read(read_len)
        encoding = self._detect_encoding(raw)
        try:
            content = raw.decode(encoding, errors="replace")
        except Exception:
            content = raw.decode("utf-8", errors="replace")
        return {"content": content, "encoding": encoding, "truncated": truncated,
                "truncated_at": read_len}

    @staticmethod
    def _detect_encoding(raw: bytes) -> str:
        if raw.startswith(b"\xef\xbb\xbf"):
            return "utf-8-sig"
        try:
            raw.decode("utf-8")
            return "utf-8"
        except UnicodeDecodeError:
            pass
        try:
            raw.decode("gbk")
            return "gbk"
        except UnicodeDecodeError:
            return "latin-1"

    # ------------------------------------------------------------------
    # 缩略图（图片专用，磁盘缓存）
    # ------------------------------------------------------------------
    def image_thumbnail(self, item: Dict[str, Any], size: int = 256) -> Optional[FileResponse]:
        from PIL import Image
        full = abs_path(item["root_path"], item["rel_path"])
        ext = item["ext"]
        if ext == "svg":
            # SVG 直接原样返回（本身就是矢量文本）
            return FileResponse(full, media_type="image/svg+xml")
        cache_name = f"{item['id']}_{int(item['mtime'])}_s{size}.webp"
        cache_file = self.thumb_dir / cache_name
        if not cache_file.exists():
            try:
                with Image.open(full) as im:
                    im = im.convert("RGB") if im.mode not in ("RGB", "RGBA", "L") else im
                    im.thumbnail((size, size), Image.LANCZOS)
                    im.save(cache_file, "WEBP", quality=82)
            except Exception as e:
                self.log.warning(f"生成缩略图失败 {full}: {e}")
                return None
        return FileResponse(
            str(cache_file), media_type="image/webp",
            headers={"Cache-Control": "private, max-age=86400"},
        )

    # ------------------------------------------------------------------
    # 原图 / 视频直出（支持 Range）
    # ------------------------------------------------------------------
    def raw_file(self, item: Dict[str, Any]) -> FileResponse:
        full = abs_path(item["root_path"], item["rel_path"])
        mime = guess_mime(item["name"], item["ext"], self.classify(item))
        return FileResponse(
            full, media_type=mime,
            headers={"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=3600"},
        )

    def download(self, item: Dict[str, Any]) -> FileResponse:
        full = abs_path(item["root_path"], item["rel_path"])
        return FileResponse(full, media_type="application/octet-stream", filename=item["name"])
