#!/usr/bin/env python3
"""dev3 vs dev3 + patches 1+2 (dev3pc) for the combined-run models -> markdown rows"""
import os, json, glob
D = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
print('| model | dev3: class / coverage / parts / no geometry | dev3 + patches 1+2: class / coverage / parts / no geometry | opening_shell_repair | null_curve_segments_dropped |')
print('|---|---|---|---|---|')
for d in sorted(glob.glob(D + '/dev3pc/*/case.json')):
    i = d.split('/')[-2]
    a = json.load(open(f'{D}/dev3/{i}/case.json')); b = json.load(open(d))
    sa = json.load(open(f'{D}/dev3/{i}/out.step.stats.json')); sb = json.load(open(f'{D}/dev3pc/{i}/out.step.stats.json'))
    r = sb.get('opening_shell_repair') or {}
    print(f"| {i} | {a['class']} / {a.get('coverage_all')} / {sa.get('parts')} / {sa.get('parts_without_geometry')} | "
          f"{b['class']} / {b.get('coverage_all')} / {sb.get('parts')} / {sb.get('parts_without_geometry')} | "
          f"{r.get('shells_repaired', 0)} of {r.get('shells_checked', 0)} shells | {sb.get('null_curve_segments_dropped')} |")
