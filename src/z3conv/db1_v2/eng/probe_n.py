import sys, collections, numpy as np, time
sys.path.insert(0, 'src')
import db1dec
from db1dec import *
f = sys.argv[1]; flags = [int(x) for x in sys.argv[2].split(',')]
data = load(f)
class Db2(Db):
    def segment(self, maxstride=1500):
        u8 = self.u8; L = self.L
        cand = np.nonzero(np.isin(u8[8:], flags))[0]
        cand = cand[cand + 13 < L]
        a = self.I(cand); r = self.I(cand + 4)
        cand = cand[(a > 0) & (r > 0)]
        isH = np.zeros(L + 3 * maxstride + 16, bool); isH[cand] = True
        stride = np.zeros(len(cand), np.int32); todo = np.ones(len(cand), bool)
        for s in range(13, maxstride):
            c = cand[todo]
            if not len(c): break
            m = isH[c + s] & isH[c + 2 * s] & isH[c + 3 * s]
            idx = np.nonzero(todo)[0][m]; stride[idx] = s; todo[idx] = False
        order = {int(o): i for i, o in enumerate(cand)}
        used = np.zeros(len(cand), bool); runs = []
        for i in range(len(cand)):
            if used[i] or stride[i] == 0: continue
            s = int(stride[i]); p = int(cand[i]); recs = [p]
            while isH[p + s]:
                p += s; j = order.get(p)
                if j is not None: used[j] = True
                recs.append(p)
            if len(recs) >= 3: runs.append((s, np.array(recs, np.int64)))
        self.runs = runs
        bys = collections.defaultdict(list)
        for s, recs in runs: bys[s].append(recs)
        self.bystride = {s: np.unique(np.concatenate(v)) for s, v in bys.items()}
        self.seqidx = {}
        allk, allo, alls = [], [], []
        for s, recs in self.bystride.items():
            q = self.I(recs + 9); o = np.argsort(q, kind='stable')
            self.seqidx[s] = (q[o], recs[o]); allk.append(q); allo.append(recs); alls.append(np.full(len(recs), s))
        k = np.concatenate(allk); o = np.concatenate(allo); st = np.concatenate(alls); srt = np.argsort(k, kind='stable')
        self.gkeys, self.goffs, self.gstr = k[srt], o[srt], st[srt]
        return runs
t = time.time(); db = Db2(data); db.segment(); print('seg', round(time.time() - t, 1))
c = collections.Counter({s: len(r) for s, r in db.bystride.items()}); print('top strides', c.most_common(25))
r41 = sorted([(s, r) for s, r in db.runs if s == 41], key=lambda x: -len(x[1]))[:5]
for s, r in r41:
    x, y, z, ok = db._xyz(r, 17); print('41 run', len(r), 'plaus@17', round(ok.mean(), 3), 'flagbytes', collections.Counter(int(v) for v in db.u8[r + 8]).most_common(3))
