p = 'src/db1dec.py'; s = open(p).read()
old = """        if best:
            lay.update(best[1]); lay['poly_frac'] = round(best[0], 3)
            self._detect_chamfers(lay, cp)
        return lay"""
new = """        if best is None:
            # v2 (eng): 9.50 stores the outline arrays as float64 (u[10]@25, v[10]@105 in a stride-465 record behind the
            # same 2-hop link); chamfer x/y stay float32 and the type array follows them
            for f, T, ro, Lk in hop1:
                for g in range(9, T - 3):
                    v2 = self.I(ro + g)
                    if np.mean(v2 > 0) < 0.8: continue
                    for T2 in self._strides_holding(np.unique(v2[v2 > 0]), 0.8)[:3]:
                        r2o = self.lookup(v2, T2); ok2 = r2o >= 0
                        if ok2.mean() < 0.8: continue
                        r2 = self._uv_detect64(r2o[ok2], Lk[ok2], T2)
                        if r2 and (best is None or r2[0] > best[0]):
                            best = (r2[0], dict(poly_field=f, poly_stride=T, poly_field2=g, poly_stride2=T2,
                                                poly_ub=r2[1], poly_vb=r2[2], poly_cap=r2[3], poly_f64=True))
        if best:
            lay.update(best[1]); lay['poly_frac'] = round(best[0], 3)
            self._detect_chamfers(lay, cp)
        return lay

    def _uv_detect64(self, ro, Lk, T):
        \"\"\"float64 variant of _uv_detect (cap 10 only, as validated on 9.50)\"\"\"
        best = None
        for ub in range(9, T - 160):
            if np.mean(np.abs(self.D(ro + ub)) < 1e-6) < 0.9: continue
            cap = 10; vb = ub + 8 * cap
            if vb + 8 * cap > T: break
            if np.mean((np.abs(self.D(ro + vb)) < 1e-6) & (np.abs(self.D(ro + vb + 8)) < 1e-6)) < 0.9: continue
            U = np.stack([self.D(ro + ub + 8 * i) for i in range(cap)], 1)
            V = np.stack([self.D(ro + vb + 8 * i) for i in range(cap)], 1)
            frac = float(np.mean(_outline_ok(U, V, Lk)))
            if frac >= 0.8 and (best is None or frac > best[0]): best = (frac, ub, vb, cap)
            if frac >= 0.8: break
        return best

    @staticmethod
    def _poly_offsets(lay):
        \"\"\"-> (element size, cx, cy, type offsets) of a contour record layout\"\"\"
        cap, ub = lay['poly_cap'], lay['poly_ub']
        if lay.get('poly_f64'):
            cx = ub + 24 * cap; return 8, cx, cx + 4 * cap, cx + 8 * cap
        A = 4 * cap; return 4, ub + 3 * A, ub + 4 * A, ub + 5 * A"""
assert s.count(old) == 1; s = s.replace(old, new)
old = """        cap, ub = lay['poly_cap'], lay['poly_ub']; A = 4 * cap; hit = tot = 0"""
new = """        cap, ub = lay['poly_cap'], lay['poly_ub']; A = 4 * cap; hit = tot = 0
        es, cxo, cyo, tyo = self._poly_offsets(lay); RD = self.D if es == 8 else self.F"""
assert s.count(old) == 1; s = s.replace(old, new)
old = """                u = self.F(r + ub + 4 * np.arange(cap)); v = self.F(r + lay['poly_vb'] + 4 * np.arange(cap))
                n = 1
                while n < cap and not (abs(u[n]) < 1e-3 and abs(v[n]) < 1e-3): n += 1
                if n >= cap: continue
                tot += 1
                ty = self.I(r + ub + 5 * A + 4 * np.arange(cap))"""
new = """                u = RD(r + ub + es * np.arange(cap)); v = RD(r + lay['poly_vb'] + es * np.arange(cap))
                n = 1
                while n < cap and not (abs(u[n]) < 1e-3 and abs(v[n]) < 1e-3): n += 1
                if n >= cap: continue
                tot += 1
                ty = self.I(r + tyo + 4 * np.arange(cap))"""
assert s.count(old) == 1; s = s.replace(old, new)
old = """        cap, ub, vb = lay['poly_cap'], lay['poly_ub'], lay['poly_vb']
        A = 4 * cap; ch = lay.get('poly_ch')"""
new = """        cap, ub, vb = lay['poly_cap'], lay['poly_ub'], lay['poly_vb']
        A = 4 * cap; ch = lay.get('poly_ch')
        es, cxo, cyo, tyo = self._poly_offsets(lay); RD = self.D if es == 8 else self.F"""
assert s.count(old) == 1; s = s.replace(old, new)
old = """            u = self.F(r + ub + 4 * np.arange(cap)); v = self.F(r + vb + 4 * np.arange(cap))
            if ch:
                ty = self.I(r + ub + 5 * A + 4 * np.arange(cap)); cx = self.F(r + ub + 3 * A + 4 * np.arange(cap)); cy = self.F(r + ub + 4 * A + 4 * np.arange(cap))"""
new = """            u = RD(r + ub + es * np.arange(cap)); v = RD(r + vb + es * np.arange(cap))
            if ch:
                ty = self.I(r + tyo + 4 * np.arange(cap)); cx = self.F(r + cxo + 4 * np.arange(cap)); cy = self.F(r + cyo + 4 * np.arange(cap))"""
assert s.count(old) == 1; s = s.replace(old, new)
open(p, 'w').write(s); print('ok')
