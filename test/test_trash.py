# -*- coding: utf-8 -*-
"""回收站 API 流程自测（沙箱 root3）"""
import json
import os
import subprocess
import sys
import urllib.request

BASE = "http://127.0.0.1:8000/api/file_finder"
H = {"Accept": "application/json"}


def req(method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    h = dict(H)
    if data:
        h["Content-Type"] = "application/json"
    r = urllib.request.Request(BASE + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw.decode("utf-8"))
            except Exception:
                return resp.status, raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


ok = True
def check(name, cond, detail=""):
    global ok
    ok = ok and cond
    print(("PASS" if cond else "FAIL") + f" | {name}" + (f" | {detail}" if detail else ""))


# 重建沙箱
sb = os.path.join(os.path.dirname(os.path.abspath(__file__)), "make_sandbox.py")
subprocess.run([sys.executable, sb], check=True, capture_output=True)

# 清空历史回收站 + 历史收藏
req("POST", "/trash/empty", {})
st, old_favs = req("GET", "/favorites?page_size=1000")
for f in old_favs["data"]["items"]:
    req("DELETE", f"/favorites/{f['fav_id']}")

# 扫描沙箱
st, r = req("POST", "/roots/3/scan", {"mode": "incremental"})
tid = r["data"]["task_id"]
import time
for _ in range(60):
    time.sleep(1)
    st, t = req("GET", "/tasks/" + tid)
    if t["data"]["status"] in ("COMPLETED", "FAILED", "CANCELLED"):
        break
check("scan", t["data"]["status"] == "COMPLETED")

# 找文件
st, s = req("GET", "/search?root_id=3&page_size=200")
files = {i["name"]: i for i in s["data"]["items"]}
check("search after scan", "readme.md" in files and "photo.png" in files)
total_before = s["data"]["total"]

# 收藏 readme + photo（保留清单）
req("POST", "/favorites/toggle", {"file_id": files["readme.md"]["id"]})
req("POST", "/favorites/toggle", {"file_id": files["photo.png"]["id"]})
st, fav = req("GET", "/favorites")
check("favorites=2", fav["data"]["total"] == 2)

# 1. 删除 clip.mp4（单删）→ 进回收站
st, r = req("DELETE", "/files/" + str(files["clip.mp4"]["id"]))
check("delete status", st == 200, f"status={st} body={str(r)[:200]}")
check("delete to trash", r["data"].get("trashed") == files["clip.mp4"]["id"], f"{r}")
disk = os.path.join(os.environ["TEMP"], "ff_sandbox", "clip.mp4")
check("clip moved from disk", not os.path.exists(disk))
trash_disk = os.path.join(os.environ["TEMP"], "ff_sandbox", ".ff_trash", "clip.mp4")
check("clip in .ff_trash", os.path.exists(trash_disk))

# 2. 搜索不再出现（trashed=0 过滤）
st, s2 = req("GET", "/search?root_id=3&q=clip&page_size=20")
check("search excludes trash", s2["data"]["total"] == 0, f"total={s2['data']['total']}")

# 3. 收藏存在性（exists_now 应随删除变 False）
st, fav2 = req("GET", "/favorites")
for it in fav2["data"]["items"]:
    if it["name"] == "readme.md":
        check("fav exists still True", it["exists_now"] is True)
st, s3 = req("GET", "/search?root_id=3&page_size=200")
check("search total-1", s3["data"]["total"] == total_before - 1, f"{s3['data']['total']} vs {total_before}")

# 4. 回收站列表
st, tr = req("GET", "/trash/list")
check("trash list 1", tr["data"]["total"] == 1, f"total={tr['data'].get('total')}")
it = tr["data"]["items"][0]
check("trash item fields", it["name"] == "clip.mp4" and it["trashed_at"] > 0 and it["rel_path"] == "clip.mp4")

# 5. 批量删除 bundle.zip + native.dll
ids = [files["bundle.zip"]["id"], files["native.dll"]["id"]]
st, r = req("POST", "/files/batch-delete", {"ids": ids})
check("batch delete to trash", r["data"]["moved"] == 2, f"{r}")
st, tr = req("GET", "/trash/list")
check("trash list 3", tr["data"]["total"] == 3, f"total={tr['data'].get('total')}")

# 6. 目录删除（sub 目录整体进回收站，子树条目一并标记）
sub_id = next(i["id"] for i in s["data"]["items"] if i["name"] == "sub")
st, r = req("DELETE", "/files/" + str(sub_id))
check("dir delete to trash", r["data"].get("trashed") == sub_id, f"{r}")
st, tr = req("GET", "/trash/list?page_size=500")
sub_items = [i for i in tr["data"]["items"] if i["rel_path"] == "sub" or i["rel_path"].startswith("sub/")]
check("dir subtree in trash", len(sub_items) >= 4 and any(i["is_dir"] and i["rel_path"] == "sub" for i in sub_items),
      f"sub_items={[(i['rel_path'], i['is_dir']) for i in sub_items]}")
dir_trash = os.path.join(os.environ["TEMP"], "ff_sandbox", ".ff_trash", "sub")
check("dir moved to trash", os.path.isdir(dir_trash))

# 7. 恢复 clip.mp4
clip_trash_id = next(i["id"] for i in tr["data"]["items"] if i["name"] == "clip.mp4")
st, r = req("POST", "/trash/restore", {"ids": [clip_trash_id]})
check("restore", r["data"]["restored"] == 1, f"{r}")
check("clip back on disk", os.path.exists(os.path.join(os.environ["TEMP"], "ff_sandbox", "clip.mp4")))
st, tr2 = req("GET", "/trash/list")
check("trash -1 after restore", tr2["data"]["total"] == tr["data"]["total"] - 1,
      f"before={tr['data'].get('total')} after={tr2['data'].get('total')}")
st, s4 = req("GET", "/search?root_id=3&q=clip&page_size=20")
check("search finds clip again", s4["data"]["total"] == 1)

# 8. purge 一个（bundle.zip 彻底删除）
bundle_trash_id = next(i["id"] for i in tr2["data"]["items"] if i["name"] == "bundle.zip")
st, r = req("POST", "/trash/purge", {"ids": [bundle_trash_id]})
check("purge", r["data"]["purged"] == 1, f"{r}")
check("purge gone from disk", not os.path.exists(os.path.join(os.environ["TEMP"], "ff_sandbox", ".ff_trash", "bundle.zip")))
st, tr3 = req("GET", "/trash/list")
check("trash -1 after purge", tr3["data"]["total"] == tr2["data"]["total"] - 1,
      f"before={tr2['data'].get('total')} after={tr3['data'].get('total')}")

# 9. empty 清空
st, r = req("POST", "/trash/empty", {})
check("empty", r["data"]["purged"] >= 2, f"{r}")
st, tr4 = req("GET", "/trash/list")
check("trash empty list", tr4["data"]["total"] == 0, f"total={tr4['data'].get('total')}")
check("ff_trash dir removed", not os.path.exists(os.path.join(os.environ["TEMP"], "ff_sandbox", ".ff_trash")))

# 10. 扫描后回收站不复活
st, r = req("POST", "/roots/3/scan", {"mode": "incremental"})
tid = r["data"]["task_id"]
for _ in range(60):
    time.sleep(1)
    st, t = req("GET", "/tasks/" + tid)
    if t["data"]["status"] in ("COMPLETED", "FAILED", "CANCELLED"):
        break
st, tr5 = req("GET", "/trash/list")
check("trash stays empty after scan", tr5["data"]["total"] == 0)

print("\n=== SUMMARY ===")
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
