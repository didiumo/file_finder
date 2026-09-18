import sqlite3, time

db = r'services\file_finder\data\file_finder.db'
con = sqlite3.connect(db)
con.row_factory = sqlite3.Row

# 重建 FTS（先删触发器，再删虚表）
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
print(f'rebuild took {time.perf_counter()-t0:.1f}s')

for q in ['config', 'json', 'png', 'NetConfig', 'simulatorapp']:
    n = con.execute('SELECT count(*) FROM files_fts WHERE files_fts MATCH ?', (q,)).fetchone()[0]
    print(f'MATCH {q!r}: {n}')

try:
    con.execute("INSERT INTO files_fts(files_fts, rank) VALUES('integrity-check', 1)")
    con.commit()
    print('integrity-check: OK')
except Exception as e:
    print('integrity-check ERR:', e)
con.close()
