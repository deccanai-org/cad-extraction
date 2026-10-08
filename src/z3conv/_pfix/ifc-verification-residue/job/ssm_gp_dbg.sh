#!/bin/bash
W=/work/agentwork/ifc-verification-residue
S=$W/w/mnc_dev3/c13135ba64e2e8fd/out.step
cd $W/diag/gp
/opt/conv/env/bin/python - "$S" <<'PY'
import sys, re, math
from decimal import Decimal
S = sys.argv[1]
CP_RE = re.compile(r"CARTESIAN_POINT\('[^']*',\(([^)]*)\)\)")
OFF = [-1457000000, 3036000000, -1000000]
D_ = [Decimal(v) for v in OFF]
def _sh(m_):
    vals = m_.group(1).split(',')
    if len(vals) != 3:
        return m_.group(0)
    res_ = []
    for k_, v_ in enumerate(vals):
        x_ = format(Decimal(v_.strip()) - D_[k_], 'f')
        res_.append(x_ if '.' in x_ else x_ + '.')
    return m_.group(0)[:m_.start(1) - m_.start(0)] + ','.join(res_) + '))'
lines = open(S, encoding='latin-1').read().splitlines()
n = 0
for l in lines:
    if 'CARTESIAN_POINT' in l:
        n += 1
        if n in (1, 2, 3, 500):
            print('IN ', l); print('OUT', CP_RE.sub(_sh, l))
print('cp lines', n)
# other entity types that carry coordinates?
import collections
c = collections.Counter(re.match(r'#\d+=([A-Z_0-9]+)\(', l).group(1) for l in lines if re.match(r'#\d+=([A-Z_0-9]+)\(', l))
print(c.most_common(30))
print([l for l in lines if 'AXIS2_PLACEMENT_3D' in l][:3])
print([l for l in lines if 'DIRECTION' in l][:5])
print([l for l in lines if '#113' in l][:3])
PY
