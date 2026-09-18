"""创建 file_finder 端到端测试沙箱（本地可销毁目录，重复运行会先清空）"""
import os
import random
import shutil

root = os.path.join(os.environ["TEMP"], "ff_sandbox")
if os.path.isdir(root):
    shutil.rmtree(root)
os.makedirs(root, exist_ok=True)

# 文本
with open(os.path.join(root, "readme.md"), "w", encoding="utf-8") as f:
    f.write("# 测试文档\n\n这是 **markdown** 预览测试。\n\n- 列表项 A\n- 列表项 B\n")
with open(os.path.join(root, "notes.txt"), "w", encoding="utf-8") as f:
    f.write("Hello file_finder!\n第二行中文内容。\n第三行。\n")
with open(os.path.join(root, "data.json"), "w", encoding="utf-8") as f:
    f.write('{"name": "测试", "items": [1,2,3], "ok": true}')

# 图片（Pillow 生成）
from PIL import Image
im = Image.new("RGB", (800, 600), (30, 120, 200))
px = im.load()
for y in range(0, 600, 6):
    for x in range(0, 800, 6):
        px[x, y] = (255, 255, 0)
im.save(os.path.join(root, "photo.png"))
im2 = Image.new("RGB", (400, 300), (200, 60, 60))
im2.save(os.path.join(root, "photo.jpg"))

# 视频占位（Range 测试用，不保证可解码）
with open(os.path.join(root, "clip.mp4"), "wb") as f:
    f.write(os.urandom(65536))

# 二进制不可预览
with open(os.path.join(root, "bundle.zip"), "wb") as f:
    f.write(os.urandom(8192))
with open(os.path.join(root, "native.dll"), "wb") as f:
    f.write(os.urandom(2048))

# 子目录 + 内部文件
os.makedirs(os.path.join(root, "sub", "nested"), exist_ok=True)
with open(os.path.join(root, "sub", "inner.txt"), "w", encoding="utf-8") as f:
    f.write("inner")
with open(os.path.join(root, "sub", "nested", "deep.log"), "w", encoding="utf-8") as f:
    f.write("deep log")
im3 = Image.new("RGB", (120, 120), (10, 200, 10))
im3.save(os.path.join(root, "sub", "thumb_test.png"))

total = sum(len(fs) for _, _, fs in os.walk(root))
print("sandbox created:", root)
print("file count:", total)
