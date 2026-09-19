# -*- coding: utf-8 -*-
"""停服清理：移除测试根 root2 + 重建 FTS（离线，独占访问）"""
import sqlite3, os, time

db = r'services\file_finder\data\file_finder.db'
con = sqlite3.connect(db, timeout=60)

# 1) 移除 root2（测试子目录根，与 root1 子树重叠）
row = con.execute("SELECT id, path FROM roots WHERE id=2").fetchone()
print('root2:', row)
if row:
    con.execute("DELETE FROM favorites WHERE root_id=2")
    con.execute("DELETE FROM files WHERE root_id=2")
    con.execute("DELETE FROM roots WHERE id=2")
    con.commit()
    print('已移除 root2 及其索引')

# 2) 重建 FTS（先删触发器，再删虚表）
for t in ['files_fts_ai', 'files_fts_ad', 'files_fts_au']:
    con.execute(f'DROP TRIGGER IF EXISTS {t}')
con.execute('DROP TABLE IF EXISTS files_fts')
con.commit()
con.executescript('''
CREATE VIRTUAL TABLE files_fts USING fts5(
    name, rel_path,
    tokenize = 'trigram',
    content = 'files',
    content_rowid = 'id'
);
CREATE TRIGGER files_fts_ai AFTER INSERT ON files BEGIN
    INSERT INTO files_fts(rowid, name, rel_path) VALUES (new.id, new.name, new.rel_path);
END;
CREATE TRIGGER files_fts_ad AFTER DELETE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, name, rel_path) VALUES ('delete', old.id, old.name, old.rel_path);
END;
CREATE TRIGGER files_fts_au AFTER UPDATE OF name, rel_path ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, name, rel_path) VALUES ('delete', old.id, old.name, old.rel_path);
    INSERT INTO files_fts(rowid, name, rel_path) VALUES (new.id, new.name, new.rel_path);
END;
''')
t0 = time.perf_counter()
con.execute('INSERT INTO files_fts(rowid, name, rel_path) SELECT id, name, rel_path FROM files')
con.commit()
print(f'FTS 重建 {time.perf_counter()-t0:.1f}s')

# 3) 完整性 + 探活
for q in ['json', 'config', 'NetConfig', 'png']:
    n = con.execute('SELECT count(*) FROM files_fts WHERE files_fts MATCH ?', (q,)).fetchone()[0]
    print(f'MATCH {q!r}: {n}')
try:
    con.execute("INSERT INTO files_fts(files_fts, rank) VALUES('integrity-check', 1)")
    con.commit()
    print('integrity-check: OK')
except Exception as e:
    print('integrity-check ERR:', e)

# 4) 现状
for rid in (1, 3):
    n = con.execute('SELECT COUNT(*) FROM files WHERE root_id=?', (rid,)).fetchone()[0]
    print(f'root{rid} 行数: {n}')
con.close()
