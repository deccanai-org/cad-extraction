import sys, os, time, json
sys.path.insert(0, sys.argv[1] + '/decode'); sys.path.insert(0, os.getcwd())
import brep, grating, to_step2 as T2
from piece_table import read_pieces
from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.BRepCheck import BRepCheck_Analyzer
job, sid, variant = sys.argv[2], int(sys.argv[3]), sys.argv[4]
p = read_pieces(job)[sid]
r = brep.parse(open(os.path.join(job, 'subm', str(sid)), 'rb').read())
rec = T2._piece_record(job, sid, p['name'])
orig = BRepAlgoAPI_Fuse
class F(BRepAlgoAPI_Fuse):
    def SetFuzzyValue(self, v):
        if 'nofuzzy' not in variant: super().SetFuzzyValue(v)
    def Build(self, *a):
        if 'obb' in variant: self.SetUseOBB(True)
        if 'nondestr' in variant: self.SetNonDestructive(True)
        return super().Build(*a)
import OCP.BRepAlgoAPI as BA
BA.BRepAlgoAPI_Fuse = F
if 'nounify' in variant:
    import OCP.ShapeUpgrade as SU
    class U:
        def __init__(self, s, *a): self.s = s
        def Build(self): pass
        def Shape(self): return self.s
    SU.ShapeUpgrade_UnifySameDomain = U
t0 = time.time(); sh, info = grating.build(r[0], r[1], p['wt'], rec)
print(json.dumps(dict(sid=sid, variant=variant, ok=sh is not None, sec=round(time.time() - t0, 1), ratio=info.get('weight_ratio'), why=info.get('why'))))
