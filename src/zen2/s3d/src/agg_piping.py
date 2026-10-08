"""Aggregate piping done-markers -> summary dict (also used by status.py)."""
import os, json, glob, collections, sys
from common import WORK

def summary(verbose=False):
    D = os.path.join(WORK, 'done', 'piping')
    tot = collections.Counter(); pcf = collections.Counter(); types = collections.Counter()
    errs = []; n = 0; nb = 0; sql = 0.0; worst = []
    for f in glob.glob(os.path.join(D, 'pb*.json')):
        try:
            d = json.load(open(f))
        except Exception:
            continue
        nb += 1; sql += d.get('timing', {}).get('sql_s', 0)
        for r in d.get('results', []):
            if 'error' in r:
                errs.append({'pl': r['pl'], 'error': r['error'][:200]}); continue
            n += 1
            for k, v in r['checks'].items():
                if isinstance(v, (int, float)) and not k.endswith('_max_m'):
                    tot[k] += v
            tot['gap_max_m'] = max(tot['gap_max_m'], r['checks'].get('connection_gap_max_m', 0))
            for k, v in r['pcf'].items():
                pcf[k] += v
            for k, v in r['counts'].items():
                types[k] += v
            if r['pcf'].get('points_dangling', 0) > 5:
                worst.append((r['pcf']['points_dangling'], r['name']))
            if r['checks'].get('components', 0) == 0:
                tot['empty_pipelines'] += 1
    out = {'batches_done': nb, 'pipelines_ok': n, 'pipelines_error': len(errs), 'errors_sample': errs[:20],
           'checks': dict(tot), 'pcf': dict(pcf), 'types': dict(types), 'sql_s_total': round(sql, 1),
           'worst_dangling': sorted(worst, reverse=True)[:15]}
    return out

if __name__ == '__main__':
    print(json.dumps(summary(), indent=1))
