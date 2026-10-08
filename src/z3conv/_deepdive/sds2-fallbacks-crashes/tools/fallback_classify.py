"""Why a piece fell back to the approximate builders (profile_fallback / plate_fallback): classify every listed piece
file by the stage at which brep_placed() rejects it, and whether a candidate repair recovers an exact solid.
usage: fallback_classify.py <decode dir> <job> [piece ids comma-separated | all-rolled-failing]
Repairs tried (patched brep.py if present in the decode dir: keyhole split; section extrusion for 2D profiles)."""
import sys, os, collections, numpy as np
sys.path.insert(0, sys.argv[1])
import brep
from piece_table import read_pieces, kind
from sds2job import read_shapes
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp
MM = 25.4
job = sys.argv[2]
P = read_pieces(job); shapes = read_shapes(job)
ids = [int(x) for x in sys.argv[3].split(',')] if len(sys.argv) > 3 and sys.argv[3] not in ('', 'all') else \
      sorted(int(f) for f in os.listdir(os.path.join(job, 'subm')) if f.isdigit())
def vol(sh):
    g = GProp_GProps(); BRepGProp.VolumeProperties_s(sh, g); return abs(g.Mass()) / MM ** 3
C = collections.Counter(); rows = []
for sid in ids:
    p = P.get(sid)
    fp = os.path.join(job, 'subm', str(sid))
    if p is None: C['no piece-table entry'] += 1; continue
    if not os.path.exists(fp): C['no piece file'] += 1; continue
    data = open(fp, 'rb').read(); r = brep.parse(data)
    if r is None: why = 'no readable face topology'; rows.append((sid, p['name'], why)); C[why] += 1; continue
    V, F = r
    used = sorted({i for f in F for i in f}); ext = np.ptp(V[used], 0)
    s0 = brep._solid_parts(V, F)
    s = brep.solid(V, F)                                   # with repairs (patched: keyhole split)
    keyh = any(len(set(l)) != len(l) for f in F for l in brep.loops_of(f))
    planar = ext.min() < 1e-6
    if s0 is not None: why = 'closed as stored'
    elif s is not None: why = 'closed after repair (%s)' % ('keyhole split' if keyh else 'conform/drop_covered')
    elif planar: why = '2D profile only (all face vertices in one plane: extrusion implicit)'
    elif keyh: why = 'keyhole faces, still open'
    else: why = 'faces do not sew (other)'
    ratio = None
    if s is not None and 0 < p['wt'] < 1e9: ratio = round(vol(s) * 0.2836 / p['wt'], 3)
    sx = None
    if hasattr(brep, 'section_extrusion') and s is None and planar and p['L'] > 0:
        sx = brep.section_extrusion(V, F, p['L'])
        if sx is not None and 0 < p['wt'] < 1e9: ratio = round(vol(sx) * 0.2836 / p['wt'], 3); why += ' -> section_extrusion'
    C[why] += 1
    rows.append((sid, p['name'], kind(p), why, 'faces', len(F), 'ext', np.round(ext, 3).tolist(), 'L', round(p['L'], 3), 'vol/SDS2wt', ratio))
print(os.path.basename(job.rstrip('/')), dict(C))
for x in rows[:60]: print('  ', x)
