"""
file_finder 公共工具
===================
路径拼装、扩展名分类、MIME 推断。
"""
import mimetypes
import os
from typing import Optional

# 与 preview_logic 保持一致的三类扩展名集合（此处避免循环 import 单独维护）
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

_VIDEO_MIME = {
    "mp4": "video/mp4", "m4v": "video/mp4", "mkv": "video/x-matroska",
    "webm": "video/webm", "mov": "video/quicktime", "avi": "video/x-msvideo",
    "flv": "video/x-flv", "wmv": "video/x-ms-wmv", "mpg": "video/mpeg",
    "mpeg": "video/mpeg", "3gp": "video/3gpp", "ts": "video/mp2t",
    "m2ts": "video/mp2t", "ogv": "video/ogg", "rmvb": "application/vnd.rn-realmedia-vbr",
}
_IMAGE_MIME = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif",
    "webp": "image/webp", "bmp": "image/bmp", "svg": "image/svg+xml", "ico": "image/x-icon",
    "avif": "image/avif", "tif": "image/tiff", "tiff": "image/tiff",
}


def abs_path(root_path: str, rel_path: str) -> str:
    """将根路径与相对路径拼为绝对路径（统一分隔符）"""
    root = (root_path or "").rstrip("\\/")
    rel = (rel_path or "").replace("/", os.sep)
    return os.path.join(root, rel)


def classify_ext(ext: str) -> str:
    """按扩展名分类：text / image / video / none"""
    ext = (ext or "").lower().lstrip(".")
    if ext in TEXT_EXTS:
        return "text"
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    return "none"


def guess_mime(name: str, ext: str, kind: Optional[str] = None) -> str:
    """推断 MIME 类型"""
    ext = (ext or "").lower().lstrip(".")
    if kind == "video" and ext in _VIDEO_MIME:
        return _VIDEO_MIME[ext]
    if kind == "image" and ext in _IMAGE_MIME:
        return _IMAGE_MIME[ext]
    mime, _ = mimetypes.guess_type(name or f"x.{ext}")
    return mime or "application/octet-stream"
