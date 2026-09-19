"""file_finder 端到端 API 测试（针对本地沙箱）"""
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8000/api/file_finder"
H = {"Accept": "application/json"}


def req(method, path, body=None, headers=None, raw=False):
    url = BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    h = dict(H)
    if data:
        h["Content-Type"] = "application/json"
    if headers:
        h.update(headers)
    r = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            ct = resp.headers.get("Content-Type", "")
            raw_body = resp.read()
            if raw:
                return resp.status, dict(resp.headers), raw_body
            if "json" in ct or "msgpack" in ct:
                return resp.status, json.loads(raw_body.decode("utf-8"))
            return resp.status, raw_body.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def check(name, cond, detail=""):
    print(("PASS" if cond else "FAIL") + f" | {name}" + (f" | {detail}" if detail else ""))
    return cond


ok = True

# 0. 重建沙箱（幂等：上一轮测试可能删除了 data.json 等文件）
sb = os.path.join(os.path.dirname(os.path.abspath(__file__)), "make_sandbox.py")
subprocess.run([sys.executable, sb], check=True, capture_output=True)

# 0b. 清理历史收藏（保证幂等）
st, old_favs = req("GET", "/favorites?page_size=1000")
for f in old_favs["data"]["items"]:
    req("DELETE", f"/favorites/{f['fav_id']}")

# 1. 扫描沙箱
st, r = req("POST", "/roots/3/scan", {"mode": "incremental"})
task_id = r["data"]["task_id"]
import time
for _ in range(60):
    time.sleep(1)
    st, t = req("GET", "/tasks/" + task_id)
    if t["data"]["status"] in ("COMPLETED", "FAILED", "CANCELLED"):
        break
ok &= check("sandbox scan completed", t["data"]["status"] == "COMPLETED",
            f"files={t['data'].get('current')} detail={t['data'].get('detail')}")

st, s = req("GET", "/search?root_id=3&page_size=100")
files = {i["name"]: i for i in s["data"]["items"]}
ok &= check("search finds readme.md", "readme.md" in files)
ok &= check("search finds photo.png", "photo.png" in files)
ok &= check("search finds clip.mp4", "clip.mp4" in files)
ok &= check("search finds sub/inner.txt", any(i["name"] == "inner.txt" for i in s["data"]["items"]))
ok &= check("sandbox total=13", s["data"]["total"] == 13, f"total={s['data']['total']}")

# 2. 文本预览
st, text = req("GET", "/files/" + str(files["readme.md"]["id"]) + "/preview")
ok &= check("md preview is text", "markdown" in text, f"status={st}")

# 3. 图片预览 + 缩略图
pid = files["photo.png"]["id"]
st, _, img = req("GET", f"/files/{pid}/preview", raw=True)
ok &= check("png raw preview", st == 200 and img[:8] == b"\x89PNG\r\n\x1a\n", f"status={st}")
st, _, thumb = req("GET", f"/files/{pid}/thumb?size=128", raw=True)
ok &= check("png thumbnail", st == 200 and thumb[:4] == b"RIFF", f"status={st} len={len(thumb)}")

# 4. 视频 Range
vid = files["clip.mp4"]["id"]
st, hdrs, chunk = req("GET", f"/files/{vid}/preview", headers={"Range": "bytes=0-1023"}, raw=True)
ok &= check("video range 206", st == 206 and len(chunk) == 1024, f"status={st} len={len(chunk)}")

# 5. 不可预览
zipf = files["bundle.zip"]["id"]
st, r = req("GET", f"/files/{zipf}/preview")
ok &= check("zip not previewable", st == 415, f"status={st}")
st, r = req("GET", f"/files/{zipf}/thumb")
ok &= check("zip thumb 415", st == 415, f"status={st}")

# 6. 收藏
st, r = req("POST", "/favorites/toggle", {"file_id": files["readme.md"]["id"]})
ok &= check("favorite add", r["data"]["favorite"] is True)
st, r = req("POST", "/favorites/toggle", {"file_id": files["readme.md"]["id"]})
ok &= check("favorite toggle off", r["data"]["favorite"] is False)
st, r = req("POST", "/favorites/toggle", {"file_id": files["readme.md"]["id"]})
st, r2 = req("POST", "/favorites/toggle", {"file_id": files["photo.png"]["id"]})
st, fav = req("GET", "/favorites")
ok &= check("favorites list=2", fav["data"]["total"] == 2, f"total={fav['data']['total']}")
ok &= check("favorite card fields", all(k in fav["data"]["items"][0] for k in ("name", "size", "mtime", "exists_now")))

# 7. 删除文件（显式删除会同时移除其收藏快照）
st, r = req("POST", "/favorites/toggle", {"file_id": files["data.json"]["id"]})
st, r = req("DELETE", "/files/" + str(files["data.json"]["id"]))
ok &= check("delete file", r["data"]["deleted"] == files["data.json"]["id"])
disk_path = os.path.join(os.environ["TEMP"], "ff_sandbox", "data.json")
ok &= check("deleted from disk", not os.path.exists(disk_path))
st, fav = req("GET", "/favorites?q=data.json")
ok &= check("favorite removed with explicit delete", fav["data"]["total"] == 0,
            f"total={fav['data']['total']}")

# 7b. 文件系统浏览（实时读盘，不触发全量扫描；目录是“多出来的内容”）
sb_root = os.path.join(os.environ["TEMP"], "ff_sandbox")
st, fs = req("GET", "/fs/list?path=" + urllib.parse.quote(sb_root) + "&page_size=100")
ok &= check("fs root total=8", fs["data"]["total"] == 8, f"total={fs['data'].get('total')}")
fs_names = [i["name"] for i in fs["data"]["items"]]
ok &= check("fs has dir sub", "sub" in fs_names, f"names={fs_names[:6]}")
ok &= check("fs dir indexed", all(i["indexed"] for i in fs["data"]["items"]), "dirs should be indexed")
st, fs2 = req("GET", "/fs/list?path=" + urllib.parse.quote(os.path.join(sb_root, "sub")))
ok &= check("fs sub total=3", fs2["data"]["total"] == 3, f"total={fs2['data'].get('total')}")
sub_names = {i["name"]: i for i in fs2["data"]["items"]}
ok &= check("fs sub items", {"inner.txt", "thumb_test.png", "nested"} <= set(sub_names), f"names={list(sub_names)}")
ok &= check("fs nested is dir", sub_names["nested"]["is_dir"] is True)
# 越界护栏：temp 目录不在扫描根内
st, r3 = req("GET", "/fs/list?path=" + urllib.parse.quote(os.environ["TEMP"]))
ok &= check("fs guard 400", st == 400, f"status={st}")

# 8. 收藏整理 plan
st, plan = req("GET", "/collect/plan")
ok &= check("collect plan", plan["data"]["copy_items"] >= 2, f"copy={plan['data'].get('copy_items')} delete={plan['data'].get('delete_files')}")
ok &= check("plan excludes favorites from delete", all(i["rel_path"] != "readme.md" for i in plan["data"]["delete_sample"]))
print(json.dumps({k: v for k, v in plan["data"].items() if k != "delete_sample"}, ensure_ascii=False, indent=1))

# 9. 执行收集（仅复制，不清理）
st, r = req("POST", "/collect/run", {"copy": True, "cleanup": False, "confirm": True})
task_id = r["data"]["task_id"]
for _ in range(60):
    time.sleep(1)
    st, t = req("GET", "/tasks/" + task_id)
    if t["data"]["status"] in ("COMPLETED", "FAILED", "CANCELLED"):
        break
ok &= check("collect run", t["data"]["status"] == "COMPLETED", f"detail={t['data'].get('detail')}")
col_dir = os.path.join(os.environ["TEMP"], "ff_sandbox")  # 实际目标在服务 data 下
import glob
copied = glob.glob(r"E:\Projects\Trae\py-lite-server\services\file_finder\data\collected\**\*", recursive=True)
ok &= check("collected files exist", any(p.endswith("readme.md") for p in copied), f"copied={len(copied)}")

print("\n=== SUMMARY ===")
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
