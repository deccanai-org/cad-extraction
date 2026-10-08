"""Per-model catalog entries for the data-3 Tekla DB1 models (model_catalogs.json, keyed by DB1 sha256).
Sources, in order (each entry records its provenance):
  1. the model folder's own profdb.bin (angles: h/b/t/r1/r2; round bars 'R.B Ø<d>'), see profdb.model_catalog
  2. Tekla built-in round bar D<d> / ROD<d> larger than the generic plausibility bound, only where the model's own
     data proves the size: its own Tekla report lists the part with a solid-round weight, or the diameter continues an
     adjacent tapered part end (ELD..d) or a stacked run of rounds on one axis.
Only names the current parser leaves approximate or unresolved get an entry.
  python3 gen_catalogs.py  -> model_catalogs.json + catalog_evidence.json
"""
import glob, gzip, json, math, os, re, sys, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import profdb, db1prof

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'kit_patched'))
import db1old, db1step
from db1dec import load

F = json.load(open(os.path.join(HERE, 'folders.json')))
CAT = json.load(open(os.path.join(HERE, 'kit_patched', 'tekla_profiles.json')))
APPROX = {'parametric_angle', 'parametric_angle_equal'}
P_BIG = re.compile(r'^(D|ROD)(\d+)$')
RX_RPT = re.compile(r'^\s*\S+\s+(?:\S+\s+)?(D\d+|ROD\d+)\s+(\d+)\s+\S+\s+(\d+)\s+([\d.]+)\s+([\d.]+)\s*$')


def report_lines(d):
    """lines of the model folder's own Tekla text reports (xsr / csv) -> [(file, line)]"""
    out = []
    for p in glob.glob(os.path.join(d, '*.xsr')) + glob.glob(os.path.join(d, '*.XSR')) + glob.glob(os.path.join(d, '*.CSV')) + glob.glob(os.path.join(d, '*.csv')):
        try: txt = open(p, 'rb').read().decode('latin1')
        except Exception: continue
        out += [(os.path.basename(p), ln) for ln in txt.splitlines()]
    return out


RPT = None


def family_lines(model_name):
    """report lines of every MoldTek upload folder holding the same model (same model folder name), with their key"""
    global RPT
    if RPT is None:
        RPT = collections.defaultdict(list)
        idx = os.path.join(HERE, 'rpt', 'index.tsv')
        if os.path.exists(idx):
            for row in open(idx):
                f, k = row.rstrip('\n').split('\t', 1)
                parts = k.split('/')
                try: txt = open(f, 'rb').read().decode('latin1')
                except Exception: continue
                for nm in parts[-4:-1]:
                    RPT[nm.upper()] += [(k.split('kwik/')[-1], ln) for ln in txt.splitlines()]
    return RPT.get(model_name.upper(), [])


def weight_proof(lines, n, dd, Lpart):
    """a report line naming n that lists (length, weight) of a solid round d=dd, or the weight of this part's length"""
    for src, ln in lines:
        toks = ln.replace(',', ' ').split()
        if n not in toks: continue
        nums = []
        for t in toks[toks.index(n) + 1:]:
            try: nums.append(float(t))
            except ValueError: pass
        for i, a in enumerate(nums):
            for b in nums[i + 1:]:
                if abs(a - Lpart) <= 1.0 and b > 0 and abs(b / solid_round_kg(dd, a) - 1) <= 0.01:
                    return f'{src}: {n} L{a:g} {b:g} kg = solid round d{dd:g} ({solid_round_kg(dd, a):.0f} kg)'
        for b in nums:
            if b > 0 and abs(b / solid_round_kg(dd, Lpart) - 1) <= 0.01:
                return f'{src}: {n} {b:g} kg = solid round d{dd:g} x this part length L{Lpart:g} ({solid_round_kg(dd, Lpart):.0f} kg)'
    return None


def solid_round_kg(d, L):
    return math.pi / 4 * (d / 1000) ** 2 * (L / 1000) * 7850


def main():
    res = {}; ev = {}; sib = {}
    for sha, v in sorted(F.items()):
        d = os.path.join(HERE, 'mf', sha[:10])
        job = next(j for j in JOBS if j['sha256'] == sha)
        p_db = os.path.join(d, os.path.basename(job['input_key']))
        if not os.path.exists(p_db):
            ev[sha] = {'status': 'db1_not_downloaded'}; continue
        data = load(p_db); eng = float(re.search(rb'(\d+\.\d+)', data[:16]).group(1))
        if eng >= 7.5:
            ev[sha] = {'status': f'engine {eng} (new reader; not covered)'}; continue
        M, info, cut = db1old.read(data, eng)
        cur = {}
        for m in M:
            n = m.get('prof')
            if not n or m.get('cut') or m.get('bolt'): continue
            if n not in cur: cur[n] = db1step.section_for(n, CAT)
        nulls = {m.get('prof') for m in M if db1prof.is_null_record(m)}
        need = {n for n, (k, vv, how) in cur.items() if (k is None and vv not in ('contour_plate',)) or how in APPROX}
        need -= {n for n in nulls if not any(x.get('prof') == n and not db1prof.is_null_record(x) for x in M)}
        entries = {}; why = {}
        pdb = os.path.join(d, 'profdb.bin')
        if os.path.exists(pdb):
            mc = profdb.model_catalog(profdb.load(pdb), wanted=need)
            for n, e in mc.items():
                entries[n] = dict(kind=e['kind'], dims=e['dims'], tier='P', src='model folder profdb.bin: ' + e['src'])
        # large Tekla round bars proven by the model's own data
        own_lines = report_lines(d); fam_lines = family_lines(os.path.splitext(os.path.basename(job['input_key']))[0])
        big = [m for m in M if m.get('prof') and P_BIG.match(m['prof']) and cur.get(m['prof'], (None, ''))[1] == 'implausible_profile']
        for m in big:
            n = m['prof']; dd = float(P_BIG.match(n).group(2))
            if n in entries: continue
            proof = None; tier = 'A'
            w = weight_proof(own_lines, n, dd, m['L'])
            if w: proof = 'own Tekla report ' + w
            if proof is None:
                w = weight_proof(fam_lines, n, dd, m['L'])
                if w: proof = 'Tekla report of the same model (another upload of this model folder) ' + w
            if proof is None:
                # diameter continuity: an end of an adjacent tapered part (ELD) or a round on the same axis meets this part's end
                ax = np.asarray(m['x']); ends = (np.asarray(m['O']), np.asarray(m['E']))
                for o in M:
                    if o is m or not o.get('prof'): continue
                    if np.linalg.norm(np.cross(np.asarray(o['x']), ax)) > 1e-3: continue
                    tp = db1prof.parse_tapered(o['prof'])
                    if tp and tp[0] == 'FRUSTUM':
                        # start diameter at o['O'], end diameter at o['E']
                        for pt, dia in ((np.asarray(o['O']), tp[1][0]), (np.asarray(o['E']), tp[1][1])):
                            if abs(dia - dd) < 1e-6 and min(np.linalg.norm(pt - e) for e in ends) < 1.0:
                                proof = f'diameter continuity: {o["prof"]} end d{dia:g} meets this part end'; break
                    if proof: break
            if proof is None:
                # stacked run: consecutive rounds of this family on one axis, end to end (vessel shell steps)
                ax = np.asarray(m['x']); runs = 0
                for o in M:
                    if o is m or not o.get('prof') or not P_BIG.match(o['prof']): continue
                    if np.linalg.norm(np.cross(np.asarray(o['x']), ax)) > 1e-3: continue
                    same = np.linalg.norm(np.asarray(o['O']) - np.asarray(m['O'])) < 1.0 and np.linalg.norm(np.asarray(o['E']) - np.asarray(m['E'])) < 1.0
                    if not same and min(np.linalg.norm(np.asarray(a) - np.asarray(b)) for a in (m['O'], m['E']) for b in (o['O'], o['E'])) < 1.0: runs += 1
                if runs:
                    tier = 'B'
                    proof = f'stacked rounds: meets {runs} other D/ROD part end(s) on the same axis (vessel shell run); D<d>/ROD<d> = solid round per the environment reports'
            if proof is None and P_BIG.match(n).group(1) == 'D':
                tier = 'C'; proof = ('Tekla built-in D<d> = solid round bar of diameter d, verified in this environment by Tekla reports '
                                     '(1620-D-029 D3376 L10120 710,655 kg; 1620-C-003 D2212 L9050 272,830 kg; 1620-D-016 D2530 L8205 323,604 kg)')
            if proof:
                entries[n] = dict(kind='CIRC', dims=[dd / 2], tier=tier, src=f'tier {tier}: Tekla D/ROD round bar, size from the name; ' + proof)
            else:
                why[n] = 'no own-data proof (no report row, no continuity)'
        if not os.path.exists(pdb):
            for n in sorted(need - set(entries)):
                e = SIB.get(n)
                if e: sib.setdefault(sha, {})[n] = dict(kind=e['kind'], dims=e['dims'], tier='S', src='sibling MoldTek profdb.bin (not in this model folder; all %d copies agree): %s' % (e['copies'], e['src']))
        res[sha] = entries
        ev[sha] = {'engine': eng, 'profdb': os.path.exists(pdb), 'need': sorted(need), 'resolved': {n: e['src'] for n, e in entries.items()},
                   'unresolved': sorted(set(need) - set(entries)), 'big_unproven': why, 'report_lines': len(own_lines), 'family_lines': len(fam_lines)}
        print(sha[:10], eng, 'profdb', os.path.exists(pdb), 'need', len(need), 'resolved', len(entries), 'left', sorted(set(need) - set(entries))[:6], flush=True)
    json.dump({k: v for k, v in res.items() if v}, open(os.path.join(HERE, 'model_catalogs.json'), 'w'), indent=0)
    both = {k: dict(v) for k, v in res.items()}
    for k, v in sib.items(): both.setdefault(k, {}).update(v)
    json.dump({k: v for k, v in both.items() if v}, open(os.path.join(HERE, 'model_catalogs_with_siblings.json'), 'w'), indent=0)
    json.dump(ev, open(os.path.join(HERE, 'catalog_evidence.json'), 'w'), indent=1)


JOBS = json.load(open(os.path.join(HERE, '..', 'work', 'd3jobs.json')))


def sibling_catalog():
    """entries that EVERY MoldTek profdb.bin copy defines identically"""
    vals = collections.defaultdict(list)
    mold = {sha[:10] for sha, v in F.items() if 'MOLDTEK' in v['dir'].upper()}
    files = sorted(p for p in glob.glob(os.path.join(HERE, 'mf', '*', 'profdb.bin')) if os.path.basename(os.path.dirname(p)) in mold)
    for p in files:
        for n, e in profdb.model_catalog(profdb.load(p)).items(): vals[n].append(json.dumps([e['kind'], e['dims']]))
    out = {}
    for n, v in vals.items():
        if len(set(v)) == 1 and len(v) == len(files):
            k, dims = json.loads(v[0]); out[n] = dict(kind=k, dims=dims, copies=len(v), src=f'{k} {dims[:5]}')
    return out


SIB = sibling_catalog()
if __name__ == '__main__':
    main()
