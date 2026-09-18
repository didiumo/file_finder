import urllib.request, time, json, urllib.parse, concurrent.futures

BASE = 'http://127.0.0.1:8010/api/file_finder/'
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

def get(url):
    req = urllib.request.Request(BASE + url, headers={'Accept': 'application/json'})
    t0 = time.perf_counter()
    with opener.open(req, timeout=30) as r:
        data = json.load(r)
    return (time.perf_counter() - t0) * 1000, data['data']

for _ in range(30):
    try:
        get('stats')
        break
    except Exception:
        time.sleep(1)

cases = [
    ('q=config 稀有词', 'search?q=config&page=1&page_size=300&sort=name&order=asc'),
    ('q=mj 短词',       'search?q=mj&page=1&page_size=300'),
    ('q=net 大写词',    'search?q=net&page=1&page_size=300'),
    ('name asc p1',     'search?page=1&page_size=300&sort=name&order=asc'),
    ('name desc p1',    'search?page=1&page_size=300&sort=name&order=desc'),
    ('size desc p1',    'search?page=1&page_size=300&sort=size&order=desc'),
    ('size asc p1',     'search?page=1&page_size=300&sort=size&order=asc'),
    ('mtime desc p1',   'search?page=1&page_size=300&sort=mtime&order=desc'),
    ('ext png',         'search?page=1&page_size=300&ext=png'),
    ('favorites',       'favorites?page=1&page_size=300'),
]
for name, q in cases:
    ms, d = get(q)
    print(f'{name}: {ms:.0f}ms total={d["total"]}')

# 游标连续翻 20 页（name asc）
ms0, d = get('search?page_size=300&sort=name&order=asc')
cur = d.get('next_cursor')
t_start = time.perf_counter()
for i in range(19):
    if not cur:
        break
    q = 'search?page_size=300&sort=name&order=asc&' + urllib.parse.urlencode(cur)
    ms, d = get(q)
    cur = d.get('next_cursor')
t_cur = (time.perf_counter() - t_start) * 1000
print(f'游标翻 20 页: {(t_cur/20):.0f}ms/页')

ms, d = get('search?page=100&page_size=300&sort=name&order=asc')
print(f'OFFSET page=100: {ms:.0f}ms')

# 10 并发
with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
    futs = [ex.submit(get, 'search?page=1&page_size=300&sort=size&order=desc') for _ in range(10)]
    t0 = time.perf_counter()
    res = [f.result() for f in futs]
    print(f'10 并发 size desc: 总 {(time.perf_counter()-t0)*1000:.0f}ms，逐请求 {[f"{m:.0f}" for m, _ in res]}ms')
