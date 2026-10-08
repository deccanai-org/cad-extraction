#!/usr/bin/env python3
"""validate one track patch (complete/<track>/out/<tag>/patch.json) against ../INTERFACES.md: schema, ops, ids,
provenance per colour, geometry kinds; with the baseline tree also that every referenced part id exists.

    python3 complete/integrate/validate_patch.py complete/db1/out/n1_db1_small/patch.json
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import completion_core as cc          # noqa: E402
from samples import baseline_tree      # noqa: E402


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    bad = 0
    for f in sys.argv[1:]:
        p = json.load(open(f, encoding='utf-8'))
        tag = p.get('tag')
        ids = None
        bt = baseline_tree(tag) if tag else None
        if bt and os.path.exists(os.path.join(bt, 'schedules', 'parts.csv')):
            _, rows = cc.read_csv(os.path.join(bt, 'schedules', 'parts.csv'))
            ids = {r['part_id'] for r in rows}
        errs = cc.validate_patch(p, tag, ids)
        n = len(p.get('ops') or [])
        if errs:
            bad += 1
            print(f'INVALID {f}: {len(errs)} problem(s) in {n} ops')
            for e in errs[:40]:
                print('  ', e)
        else:
            from collections import Counter
            print(f"OK {f}: {n} ops {dict(Counter(o['op'] for o in p['ops']))} colours "
                  f"{dict(Counter(o.get('colour') for o in p['ops']))}" + ('' if ids else ' (part ids not checked: no baseline)'))
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
