"""pdf_index_fill.py - classify data-4 PDFs still 'unknown' in /work/pdfcache/classes.sqlite whose content Disk-1/Disk-2 stored,
using that run's own per-sha PDF class in /work/idx/union.sqlite (digests bucket 'cad_pdf' / 'other_pdf').
Same source as the Disk-1/2 columns of the live comparison table. why = 'disk12_index' (or 'disk12_index:both' if the sha is in both)."""
import sqlite3, collections
u = sqlite3.connect('file:/work/idx/union.sqlite?mode=ro', uri=True)
db = sqlite3.connect('/work/pdfcache/classes.sqlite', timeout=120)
todo = [(sha, why) for sha, why in db.execute("SELECT sha, why FROM cls WHERE cls='unknown'")]
print('unknown shas:', len(todo), flush=True)
q = "SELECT 1 FROM digests WHERE disk=? AND kind='sha' AND bucket=? AND digest=?"
rows, st = [], collections.Counter()
for sha, why in todo:
    d = bytes.fromhex(sha)
    cad = any(u.execute(q, (k, 'cad_pdf', d)).fetchone() for k in ('Disk-1', 'Disk-2'))
    oth = any(u.execute(q, (k, 'other_pdf', d)).fetchone() for k in ('Disk-1', 'Disk-2'))
    if cad or oth:
        c = 'cad' if cad else 'document'
        rows.append((sha, c, 'disk12_index:both' if cad and oth else 'disk12_index'))
        st[(why, c)] += 1
    else:
        st[(why, 'still_unknown')] += 1
db.executemany('INSERT OR REPLACE INTO cls VALUES (?,?,?)', rows); db.commit()
for k, v in sorted(st.items(), key=lambda x: -x[1]): print(k, v)
print('filled', len(rows), db.execute('SELECT cls, COUNT(*) FROM cls GROUP BY cls').fetchall(), flush=True)
