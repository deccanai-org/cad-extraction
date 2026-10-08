#!/usr/bin/env python3
"""link_dups.py - hardlink the canonical dxf_from_pdf/<relpath>/ outputs into every duplicate relpath folder."""
import json, os
OUT = '/work/2d/out/dxf_from_pdf/'
n = 0
for l in open('/work/2d/state/pdf_results.jsonl'):
    r = json.loads(l)
    src = OUT + r['canonical_relpath']
    if not os.path.isdir(src):
        continue
    files = [f for f in os.listdir(src) if os.path.isfile(os.path.join(src, f))]
    for rel in r['relpaths'][1:]:
        dst = OUT + rel
        os.makedirs(dst, exist_ok=True)
        for f in files:
            d = os.path.join(dst, f)
            if not os.path.exists(d):
                os.link(os.path.join(src, f), d); n += 1
print('linked', n)
