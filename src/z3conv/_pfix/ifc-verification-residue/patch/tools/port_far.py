import sys
p=sys.argv[1]; s=open(p).read()
def rep(old,new,cnt=1):
    global s
    assert s.count(old)==cnt, (s.count(old), old[:80])
    s=s.replace(old,new)
rep("VERSION = 'ifc2step6 6.1.2'", "VERSION = 'ifc2step6 6.1.2+farall'")
rep("""FAR_VERIFY = os.environ.get('V6_FAR_VERIFY', '0') == '1'
""", """FAR_VERIFY = os.environ.get('V6_FAR_VERIFY', '0') == '1'
# V6_FAR_ALWAYS=1 (implies FAR_VERIFY; ship ONLY together with the grader's second-read far rule, step_check_far_secondread):
# every far part - instances of shared geometry included - is verified on a copy of its own block and of its shared block
# whose far points are moved by one model-level whole-km offset, at every level; far instances stay instances; every far
# part is tagged far-origin. (dev3+vr far mode of the IFC verification-residue fixer; the in-place verdicts there are OCC
# precision noise. With the fleet's whole-file grader rule, which skips files with MAPPED_ITEM, it must stay off.)
FAR_ALWAYS = os.environ.get('V6_FAR_ALWAYS', '0') == '1'
FAR_VERIFY = FAR_VERIFY or FAR_ALWAYS
""")
rep('''    def one(m):
        vals = m.group(1).split(b',')
        res = []
        for k, v in enumerate(vals):''', '''    def one(m):
        vals = m.group(1).split(b',')
        if FAR_ALWAYS and (len(vals) != 3 or max(abs(float(v)) for v in vals) < FAR_MM):
            return m.group(0)                      # far mode: only far points move (local frames of shared blocks stay)
        res = []
        for k, v in enumerate(vals):''')
rep("""        self.bb = [1e300, 1e300, 1e300, -1e300, -1e300, -1e300]
        self.n_faces_total = 0

    def close(self):""", """        self.bb = [1e300, 1e300, 1e300, -1e300, -1e300, -1e300]
        self.n_faces_total = 0
        self.far_off = None       # FAR_ALWAYS: one whole-km offset per model (the first far part's)

    def _far(self, lo, hi):
        o = far_offset(lo, hi)
        if o is None or not FAR_ALWAYS:
            return o
        if self.far_off is None:
            self.far_off = o
        return self.far_off

    def close(self):""")
rep("""        far = far_offset(lo, hi)
        return Frag(off, len(data), pd, sdr, len(solids), len(surfaces), len(faces), vol,""", """        far = self._far(lo, hi)
        return Frag(off, len(data), pd, sdr, len(solids), len(surfaces), len(faces), vol,""")
rep("""                    far=far_offset(C.min(0), C.max(0)))""", """                    far=self._far(C.min(0), C.max(0)))""")
rep("""        with open(self.spool.path, 'rb') as sp:
            for key, fr in reps:
                bykey[fr.pd] = key; bykey[fr.sdr] = key
                sp.seek(fr.off)
                data = sp.read(fr.size)
                if fr.far is not None and getattr(self, 'far_shift', False) and fr.needs is None:
                    data = shift_points(data, fr.far)
                    self.far_parts = getattr(self, 'far_parts', 0) + 1
                # chunk items: (key, part data, shared key or None); shared blocks are written once per chunk file
                if fr.size >= limit_b // 3:
                    chunks.append([(key, data, fr.needs)])          # big part: its own file
                    continue
                cur.append((key, data, fr.needs)); cur_b += fr.size
                if cur_b >= limit_b or len(cur) >= 2000:
                    chunks.append(cur); cur, cur_b = [], 0
            if cur:
                chunks.append(cur)""", """        self._sdata = {}          # FAR_ALWAYS: shifted shared blocks by (shared key, offset)
        curs = {}
        with open(self.spool.path, 'rb') as sp:
            for key, fr in reps:
                bykey[fr.pd] = key; bykey[fr.sdr] = key
                sp.seek(fr.off)
                data = sp.read(fr.size)
                sk = fr.needs
                farm = False
                if FAR_ALWAYS and fr.far is not None:
                    farm = True
                    data = shift_points(data, fr.far)
                    self.far_parts = getattr(self, 'far_parts', 0) + 1
                    if fr.needs is not None:
                        shd = self.shared.get(fr.needs)
                        if shd is not None:
                            sk = (fr.needs, fr.far)
                            if sk not in self._sdata:
                                sp.seek(shd.off)
                                self._sdata[sk] = shift_points(sp.read(shd.size), fr.far)
                elif fr.far is not None and getattr(self, 'far_shift', False) and fr.needs is None:
                    data = shift_points(data, fr.far)
                    self.far_parts = getattr(self, 'far_parts', 0) + 1
                # chunk items: (key, part data, shared key or None); shared blocks are written once per chunk file
                if fr.size >= limit_b // 3:
                    chunks.append([(key, data, sk)])          # big part: its own file
                    continue
                # far-mode items never share a file with in-place items (two variants of one shared block = same ids)
                c_ = curs.setdefault(farm, [[], 0])
                c_[0].append((key, data, sk)); c_[1] += fr.size
                if c_[1] >= limit_b or len(c_[0]) >= 2000:
                    chunks.append(c_[0]); curs[farm] = [[], 0]
            for c_ in curs.values():
                if c_[0]:
                    chunks.append(c_[0])""")
rep("""                with open(self.spool.path, 'rb') as sp:
                    for k in need:
                        shd = self.shared.get(k)
                        if shd is not None:
                            sp.seek(shd.off)
                            fh.write(sp.read(shd.size))""", """                with open(self.spool.path, 'rb') as sp:
                    for k in need:
                        if isinstance(k, tuple):
                            fh.write(self._sdata[k])           # FAR_ALWAYS: shared block shifted with its far instances
                            continue
                        shd = self.shared.get(k)
                        if shd is not None:
                            sp.seek(shd.off)
                            fh.write(sp.read(shd.size))""")
rep("""    if fails and FAR_VERIFY:
        far = [r for r in fails""", """    if fails and FAR_VERIFY and not FAR_ALWAYS:
        far = [r for r in fails""")
rep("""        recs = [r for r in recs if r.frag is not None]
        nfar = sum(1 for r in recs if 'far-origin' in r.tags)""", """        recs = [r for r in recs if r.frag is not None]
        if FAR_ALWAYS:
            for r in recs:
                if r.frag.far is not None:
                    r.tags.add('far-origin')
        nfar = sum(1 for r in recs if 'far-origin' in r.tags)""")
open(p,'w').write(s)
print('ported', p)
