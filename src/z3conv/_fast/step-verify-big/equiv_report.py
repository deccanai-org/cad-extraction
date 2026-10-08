#!/usr/bin/env python3
"""Collect the equivalence evidence (equiv/*.json, runs/*.json, probe/*.json, *.time) into equiv/summary.json
(the numbers EQUIVALENCE.md quotes)."""
import json, os, re, glob, gzip, collections

H = os.path.dirname(os.path.abspath(__file__))


def j(p):
    try:
        return json.load(open(os.path.join(H, p)))
    except Exception:
        return None


def tfile(p):
    """/usr/bin/time -l output -> real seconds, user, peak footprint bytes, max rss bytes"""
    try:
        t = open(os.path.join(H, p)).read()
    except Exception:
        return None
    g = lambda rx: (float(re.search(rx, t).group(1)) if re.search(rx, t) else None)
    return {'real_sec': g(r'([\d.]+) real'), 'user_sec': g(r'([\d.]+) user'), 'peak_footprint_mb': round((g(r'(\d+)\s+peak memory footprint') or 0) / 2**20),
            'max_rss_mb': round((g(r'(\d+)\s+maximum resident set size') or 0) / 2**20)}


def main():
    out = {'files': {}}
    for m, f in (('m1', 'med/m1_ifc_z3.step'), ('m2', 'med/m2_ifc_reused.stp'), ('m3', 'med/m3_db1.stp')):
        d = {'bytes': os.path.getsize(os.path.join(H, f)) if os.path.exists(os.path.join(H, f)) else None}
        d['stream_vs_full'] = j(f'equiv/{m}_compare.json')
        d['full2_vs_full'] = j(f'equiv/{m}_full2_vs_full.json')
        d['ec2_vs_full'] = j(f'equiv/{m}_ec2_vs_full.json')
        d['full_time'] = tfile(f'equiv/{m}_full.time')
        d['stream_time'] = tfile(f'runs/{m}_stream.err')
        s = j(f'runs/{m}_stream.json') or {}
        d['stream_streamed'] = s.get('streamed')
        out['files'][m] = d
    for f in sorted(glob.glob(os.path.join(H, 'probe', '*_r*.json'))):
        r = json.load(open(f))
        out.setdefault('probe', {})[os.path.basename(f)] = [(x['eid'], x.get('solids'), x.get('faces'), round(x.get('vol', 0), 3)) for x in r['records']]
    for L in ('L1_68648146', 'L2_b9e5ef0a'):
        s = j(f'runs/{L}_stream.json')
        if s:
            out.setdefault('large', {})[L] = {'result': {k: v for k, v in s.items() if k not in ('invalid_examples',)},
                                              'time': tfile(f'runs/{L}_stream.err'), 'vs_ec2_parts': j(f'equiv/{L}_vs_ec2parts.json')}
    json.dump(out, open(os.path.join(H, 'equiv', 'summary.json'), 'w'), indent=1)
    for m, d in out['files'].items():
        c = d['stream_vs_full'] or {}
        print(m, 'stream_vs_full: top equal', c.get('top_level_all_equal'), 'parts', c.get('parts_identical'), '/', c.get('parts_compared'),
              'mism', c.get('mismatch_by_field'), '| full2', (d['full2_vs_full'] or {}).get('parts_identical'),
              '| ec2', (d['ec2_vs_full'] or {}).get('top_level_all_equal'), '| full', d['full_time'], '| stream', d['stream_time'])


if __name__ == '__main__':
    main()
