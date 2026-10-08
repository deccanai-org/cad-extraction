#!/usr/bin/env python3
"""annot_scan.py - list distinct PDFs (sha256) that carry annotations (to re-run with flattening)."""
import collections, json, pymupdf
seen = {}
for l in open('/work/out/json/source_sha256.tsv'):
    h, p = l.rstrip('\n').split('\t', 1)
    if p.lower().endswith('.pdf') and not p.startswith('PLC 17072025/') and h not in seen:
        seen[h] = p
out = []
types = collections.Counter()
for h, p in seen.items():
    try:
        d = pymupdf.open('/work/in/src/' + p)
    except Exception:
        continue
    n = 0
    for pg in d:
        for a in pg.annots() or []:
            n += 1
            types[a.type[1]] += 1
    if n:
        out.append(h)
print(len(out), dict(types))
open('/work/2d/state/annotated_pdfs.txt', 'w').write(','.join(out))
