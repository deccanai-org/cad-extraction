import gzip, json, collections, os
from common import *
sk = collections.Counter(); pt = collections.defaultdict(list); ty = collections.Counter()
for line in gzip.open(os.path.join(OUT, 'pairs', 'pcf_validation.jsonl.gz'), 'rt'):
    r = json.loads(line)
    for m in r.get('mismatch_samples', []):
        if 'skey_orig' in m: sk[(m['type'], m['skey_orig'], m['skey_ours'])] += 1
        elif 'max_dev_mm' in m: pt[m['type']].append(m['max_dev_mm'])
        elif 'orig' in m: ty[(m['orig'], m['ours'])] += 1
print('SKEY pairs', sk.most_common(40))
import numpy as np
for t, v in sorted(pt.items(), key=lambda kv: -len(kv[1])):
    v = np.array(v); print('PTS', t, len(v), 'p10/50/90 %.1f %.1f %.1f' % tuple(np.percentile(v, [10, 50, 90])))
print('TYPE', ty.most_common(15))
