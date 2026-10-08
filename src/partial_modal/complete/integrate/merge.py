#!/usr/bin/env python3
"""merge every track's patch for one sample into its baseline schedules -> the COMPLETED schedules (no CAD).

    python3 complete/integrate/merge.py --tag n1_db1_small --dry-run        # counts only (temp dir)
    python3 complete/integrate/merge.py --tag n1_db1_small --out DIR        # DIR/schedules (+ schedules_original)
"""
import argparse
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import completion_core as cc          # noqa: E402
from samples import COMPLETE, baseline_tree, jobs   # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag', required=True)
    ap.add_argument('--baseline', default=None)
    ap.add_argument('--complete-root', default=COMPLETE)
    ap.add_argument('--out', default=None)
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    bt = a.baseline or baseline_tree(a.tag)
    if not bt:
        sys.exit(f'{a.tag}: no baseline scripts tree (n3: a track must supply complete/<track>/out/n3_ifc_approx/scripts_tree/)')
    patches = cc.load_patches(a.complete_root, a.tag)
    for f, _ in patches:
        print('patch', os.path.relpath(f, a.complete_root))
    tmp = None
    out = a.out
    if a.dry_run or not out:
        tmp = tempfile.mkdtemp(prefix='pmpc_')
        out = os.path.join(tmp, jobs()[a.tag]['model_folder'])
    comp = cc.merge(bt, patches, out, a.tag, jobs()[a.tag]['model_id'])
    import json
    print(json.dumps({k: comp[k] for k in ('counts', 'totals', 'untouched')}, indent=1))
    for u in comp['unresolved'][:10]:
        print('  unresolved', u['part_id'], u['category'], (u['reason'] or '')[:100])
    if len(comp['unresolved']) > 10:
        print(f"  ... {len(comp['unresolved'])} unresolved flags in all")
    for w in comp['warnings']:
        print('  warning', w)
    if tmp:
        shutil.rmtree(tmp)
    else:
        print('->', out)


if __name__ == '__main__':
    main()
