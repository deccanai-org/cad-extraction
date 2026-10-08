#!/usr/bin/env python3
"""Area (mm2) of every cross-section in profiles.csv, built exactly as steelbuild builds it (build123d only).

usage: profile_areas.py SCHED_DIR OUT.csv [--kit DIR]
"""
import argparse, csv, json, os, sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('folder')
    ap.add_argument('out')
    ap.add_argument('--kit', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'pm', 'kit'))
    a = ap.parse_args()
    sys.path.insert(0, os.path.abspath(a.kit))
    import steelbuild
    F = lambda n: os.path.join(a.folder, n)
    profiles = list(csv.DictReader(open(F('profiles.csv'), newline='', encoding='utf-8'))) if os.path.exists(F('profiles.csv')) else []
    outlines = json.load(open(F('profile_outlines.json'))) if os.path.exists(F('profile_outlines.json')) else {}
    tmp = a.out + '.tmp'
    with open(tmp, 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['profile_id', 'kind', 'area_mm2', 'error'])
        for p in profiles:
            try:
                w.writerow([p['profile_id'], p['kind'], round(steelbuild.profile_face(p, outlines.get(p['profile_id'])).area, 6), ''])
            except Exception as e:
                w.writerow([p['profile_id'], p['kind'], '', f'{type(e).__name__}: {e}'])
    os.replace(tmp, a.out)
    print(len(profiles), 'profiles ->', a.out)


if __name__ == '__main__':
    main()
