#!/usr/bin/env python3
"""Partial-STEP tier report (packages/3d_partial/), same section structure as the perfect report (build_report.py).
Inputs (data/): stats_<PRUN>.json + projects_<PRUN>.json (rep_stats over every partial package), class_final.json, verify_partial.json,
FINISH_DONE.json, partial_issues.json; samples under s3mirror/passets/ (pmodels, ppdf, prange, pjoin, pthree). Sections whose samples are not
there yet are left out. Usage: python3 build_partial_report.py [PRUN]   (default p1). Output psite/."""
import json, sys, os, re, math, shutil, html, collections, datetime, base64
from PIL import Image

PRUN = sys.argv[1] if len(sys.argv) > 1 else 'p1'
H = os.path.dirname(os.path.abspath(__file__))
D, A, OUT = f'{H}/data', f'{H}/s3mirror/passets', f'{H}/psite'
os.makedirs(f'{OUT}/models', exist_ok=True); os.makedirs(f'{OUT}/2d', exist_ok=True)
S = json.load(open(f'{D}/stats_{PRUN}.json')); P = json.load(open(f'{D}/projects_{PRUN}.json'))
C = json.load(open(f'{D}/class_final.json'))
VER = json.load(open(f'{D}/verify_partial.json')) if os.path.exists(f'{D}/verify_partial.json') else None
FIN = json.load(open(f'{D}/FINISH_DONE.json')) if os.path.exists(f'{D}/FINISH_DONE.json') else None
ISS = json.load(open(f'{D}/partial_issues.json'))
PERF = json.load(open(f'{D}/stats_f1.json')) if os.path.exists(f'{D}/stats_f1.json') else None
E = html.escape
def n(x): return f'{int(x):,}'
def gb(b): return f'{b / 1e9:,.1f} GB'
def tb(b): return f'{b / 1e12:,.2f} TB'
def pct(a, b, d=0): return f'{100 * a / b:.{d}f}%' if b else '—'
def have(*p): return all(os.path.exists(f'{A}/{x}') for x in p)

# ---------------------------------------------------------------- channels (same vocabulary as the perfect report)
CH = [(['model/step'], 'STEP models (class 2, partial)', '3d'), (['model/ifc'], 'IFC models', '3d'),
      (['model/db1', 'model/db2'], 'Tekla model databases', '3d'), (['model/sds2'], 'SDS/2 job zips', '3d'), (['model/stl'], 'STL meshes', '3d'),
      (['drawings/pdf'], 'Drawings (PDF)', '2d'), (['drawings/dg'], 'SDS/2 drawing files (.dg)', '2d'), (['drawings/dpm'], 'Tekla drawing files (.dpm)', '2d'),
      (['drawings/dxf'], 'DXF piece outlines', '2d'), (['drawings/dwg'], 'DWG', '2d'), (['fab/nc1'], 'CNC programs (NC1)', 'fab'),
      (['tables/bom'], 'BOM tables', 'tab'), (['tables/kiss'], 'KISS join tables', 'tab'), (['tables/abm'], 'Excel / ABM sheets', 'tab'),
      (['tables/drawing_index'], 'Drawing indexes', 'tab')]
GCOL = {'3d': 'var(--ac)', '2d': 'var(--cy)', 'fab': 'var(--gd)', 'tab': 'var(--am)'}
def chsum(dist, keys): return sum(dist['files'].get(k, 0) for k in keys), sum(dist['bytes'].get(k, 0) for k in keys)
def grp(dist, g): return [sum(x) for x in zip(*[chsum(dist, k) for k, _, gg in CH if gg == g])]
DI = S['distinct']; TOTF, TOTB = DI['total_files'], DI['total_bytes']
F3, B3 = grp(DI, '3d'); F2, B2 = grp(DI, '2d'); FF, BF = grp(DI, 'fab'); FT, BT = grp(DI, 'tab')
NPROJ = S['projects']
ORIG = {'disk-2': ('↳ from Disk-2', 'identical copies of Disk-2 archives (data-3 holds all 2,474)'), 'data-3-only': ('↳ only on data-3', '510 archives not on Disk-2'),
        'disk-1': ('↳ from Disk-1', 'identical copies of Disk-1 archives (data-4 holds all 1,154)'), 'data-4-only': ('↳ only on data-4', 'TEKLA-HYD/Backup 2026')}
proj = collections.Counter(); addon = collections.Counter(); steps = collections.Counter(); kinds = collections.Counter(); models = collections.Counter(); src = collections.Counter()
for p in P:
    for t in (p['disk'], p.get('origin'), 'all'):
        if not t: continue
        proj[t] += 1; addon[t] += bool(p.get('addon_of'))
        for s_ in p['steps']:
            steps[t] += 1; kinds[(t, s_.get('partial_kind'))] += 1; models[t] += 1 + (s_.get('also') or 0); src[(t, s_.get('step_source'))] += 1
NADD = addon['all']; NSTD = NPROJ - NADD; STP = steps['all']; CTS = kinds[('all', 'complete_to_source')]; APX = kinds[('all', 'approximated')]
PO = [p for p in P if not p.get('addon_of')]                     # partial-only projects: carry their sources themselves
pocov = collections.Counter(ch for p in PO for ch in p['per_channel'])
def has(p, pre): return any(c.startswith(pre) for c in p['per_channel'])
po_draw = sum(1 for p in PO if has(p, 'drawings/')); po_nc1 = sum(1 for p in PO if p['per_channel'].get('fab/nc1'))
po_join = sum(1 for p in PO if p['per_channel'].get('tables/bom') or p['per_channel'].get('tables/kiss'))
po_all3 = sum(1 for p in PO if has(p, 'drawings/') and p['per_channel'].get('fab/nc1') and (p['per_channel'].get('tables/bom') or p['per_channel'].get('tables/kiss')))
stamp = datetime.datetime.strptime(S['at'], '%Y-%m-%dT%H:%M:%SZ') - datetime.timedelta(hours=7)
STAMP = stamp.strftime('%-d %b %Y, %-I:%M %p PDT')
PERF_N = PERF['projects'] if PERF else None

# ---------------------------------------------------------------- PDF sample (partial tier; rule label checked against 600 hand labels)
PDFS = json.load(open(f'{A}/ppdf/pdf_sample.json')) if have('ppdf/pdf_sample.json') else None
NPDF = DI['files'].get('drawings/pdf', 0)
if PDFS:
    lab = [x for x in PDFS if x.get('label')]
    wd = {d: S['distinct_by_disk'].get(d, {'files': {}})['files'].get('drawings/pdf', 0) for d in ('data-3', 'data-4')}; WT = sum(wd.values()) or 1
    FALSE_DRAW = 10 / 600                                          # rule calls 'drawing' where the hand label said 'not a drawing'
    def strat(pred):
        est = var = 0
        for d in wd:
            xs = [x for x in lab if x['disk'] == d]
            if not xs: continue
            k = sum(1 for x in xs if pred(x)); m = len(xs); p_ = k / m; w_ = wd[d] / WT
            est += w_ * p_; var += w_ * w_ * p_ * (1 - p_) / m
        return est, max(0.0, est - 1.645 * math.sqrt(var) - FALSE_DRAW)
    pd_est, pd_lo = strat(lambda x: x['label'].startswith('drawing')); pv_est, pv_lo = strat(lambda x: x['label'] == 'drawing_vector')
    pn_est, _ = strat(lambda x: x['label'] == 'not_drawing')
    def floor_m(f):
        v = f * NPDF
        return f'{math.floor(v / 1e5) / 10:.1f} million' if v >= 1e6 else f'{int(math.floor(v / 1000) * 1000):,}'

# ---------------------------------------------------------------- assets
def jpg(src_, dst, maxw=None, q=86, crop=None):
    im = Image.open(src_).convert('RGB')
    if crop: im = im.crop(crop)
    if maxw and im.width > maxw: im = im.resize((maxw, round(im.height * maxw / im.width)), Image.LANCZOS)
    im.save(dst, quality=q, optimize=True); return im.size
MODELS = {m['tag']: m for m in json.load(open(f'{A}/pmodels/models.json'))} if have('pmodels/models.json') else {}
for t in MODELS:
    g64 = base64.b64encode(open(f'{A}/pmodels/{t}.glb', 'rb').read()).decode(); PART = 12_000_000   # chars, multiple of 4; host limit is 16 MB per file
    if len(g64) <= PART: json.dump({'format': 'glb-base64', 'glb': g64}, open(f'{OUT}/models/{t}.json', 'w'))
    else:
        parts = [f'{t}.p{k}.json' for k in range((len(g64) + PART - 1) // PART)]
        for k, pn in enumerate(parts): json.dump({'glb': g64[k * PART:(k + 1) * PART]}, open(f'{OUT}/models/{pn}', 'w'))
        json.dump({'format': 'glb-base64-parts', 'parts': parts}, open(f'{OUT}/models/{t}.json', 'w'))
    jpg(f'{A}/pmodels/{t}.png', f'{OUT}/models/{t}.jpg', 1000)
RANGE = json.load(open(f'{A}/prange/range.json')) if have('prange/range.json') else []
for r in RANGE:
    shutil.copy(f"{A}/prange/r{r['n']:02d}.jpg", f"{OUT}/2d/range_{r['n']:02d}.jpg"); shutil.copy(f"{A}/prange/r{r['n']:02d}_full.jpg", f"{OUT}/2d/range_{r['n']:02d}_full.jpg")
J = None
if have('pjoin/join_examples2.json'):
    JX = json.load(open(f'{A}/pjoin/join_examples2.json')); JK = next(iter(JX)) if JX else None
    if JK:
        J = dict(JX[JK], mark=JK); shutil.copy(f'{A}/pjoin/{JK}_sheet.jpg', f'{OUT}/2d/join_sheet.jpg'); shutil.copy(f'{A}/pjoin/{JK}_dxf.png', f'{OUT}/2d/join_dxf.png')
T3 = json.load(open(f'{A}/pthree/three.json')) if have('pthree/three.json') else None
if T3:
    shutil.copy(f'{A}/pthree/sheet.jpg', f'{OUT}/2d/three_sheet.jpg'); shutil.copy(f'{A}/pthree/sheet_full.jpg', f'{OUT}/2d/three_sheet_full.jpg')
    for c_ in T3.get('crops') or []:
        if have(f"pthree/{c_['name']}.jpg"):   # rendered from the PDF itself at 220 dpi (rep_range_p.sh)
            jpg(f"{A}/pthree/{c_['name']}.jpg", f"{OUT}/2d/{c_['name']}.jpg", c_.get('maxw', 1600)); continue
        fw, fh = Image.open(f'{A}/pthree/sheet_full.jpg').size
        jpg(f'{A}/pthree/sheet_full.jpg', f"{OUT}/2d/{c_['name']}.jpg", c_.get('maxw', 1600), crop=tuple(int(v * fw) if i % 2 == 0 else int(v * fh) for i, v in enumerate(c_['box'])))

PBY = {p['id']: p for p in P}
def pc(pid):
    p = PBY.get(pid)
    if not p: return None
    c = p['per_channel']; g = lambda *ks: sum(c.get(k, 0) for k in ks)
    return {'step': g('model/step'), 'ifc': g('model/ifc'), 'tekla': g('model/db1', 'model/db2'), 'sds2': g('model/sds2'),
            'pdf': g('drawings/pdf'), 'dxf': g('drawings/dxf'), 'dwg': g('drawings/dwg'), 'dg': g('drawings/dg'), 'dpm': g('drawings/dpm'),
            'draw': g('drawings/pdf', 'drawings/dxf', 'drawings/dwg', 'drawings/dg', 'drawings/dpm'), 'nc1': g('fab/nc1'),
            'tab': g('tables/bom', 'tables/kiss', 'tables/abm', 'tables/drawing_index'), 'disk': p['disk'], 'origin': p.get('origin'),
            'addon': bool(p.get('addon_of')), 'kinds': collections.Counter(s_.get('partial_kind') for s_ in p['steps'])}
def counts_line(c, short=False):
    m = [f"{n(c['step'])} partial STEP"] + ([f"{n(c['ifc'])} IFC"] if c['ifc'] else []) + ([f"{n(c['tekla'])} Tekla DB"] if c['tekla'] else []) + ([f"{n(c['sds2'])} SDS/2 zips"] if c['sds2'] else [])
    d = [f"{n(c['draw'])} drawings"] + ([f"{n(c['nc1'])} NC1"] if c['nc1'] else [])
    if short: return ' · '.join(m), ' · '.join(d)
    det = ', '.join(f'{n(c[k])} {lbl}' for k, lbl in (('pdf', 'PDF'), ('dxf', 'DXF'), ('dwg', 'DWG'), ('dg', 'DG'), ('dpm', 'DPM')) if c[k])
    return ' · '.join(m + [f"{n(c['draw'])} drawings ({det})" if det else '0 drawings'] + ([f"{n(c['nc1'])} NC1"] if c['nc1'] else []) + ([f"{n(c['tab'])} tables"] if c['tab'] else []))
def kind_badge(k): return '<span class="kb ks">complete to source</span>' if k == 'complete_to_source' else '<span class="kb ka">approximated</span>'
LACK = {  # readable labels for the converters' shortfall texts (numbers normalised to N)
    'verify': 'converter self-check warnings: parts dropped, solid count, duplicates',
    'N/N parts differ > N% from the source volume': 'parts whose volume differs from the source beyond tolerance',
    'N parts: part written as a surface model (no valid solid)': 'parts written as surface models, no valid solid',
    'N parts: part rebuilt from an alternative source representation; volume check not passed': 'parts rebuilt from an alternative source representation',
    'N hole slotted cut round (bolt hole of a slotted group cut round (slotted plies not decoded))': 'slotted bolt holes cut round, slots not decoded',
    'N parts with derived section dimensions (headed stud written as its shank only)': 'headed studs written as their shank only',
    'N parts with derived section dimensions (panel from an AxB name (orientation assumed))': 'panels sized from their name, orientation assumed',
    'N bolt axial position unknown (bolt (no connected ply on its axis: shank centred on the bolt plane))': 'bolts with no connected ply, centred on the bolt plane',
    'N mating holes not stored (bolt holes in the piece a single decoded ply bolts to)': 'mating bolt holes not cut where only one ply was decoded',
    'N holes derived from bolts (bolt holes in the main material)': 'bolt holes in the main material derived from bolts',
    'N open-web joists rebuilt from their designation (open-web steel joist NKN (vendor-designed))': 'open-web joists (vendor-designed) rebuilt from their designation',
    'N pieces approximated (rolled profile extrusion: WNxN)': 'rolled profiles approximated as straight extrusions',
    'N reference parts written as open surfaces (zero-thickness double-sided source surface (not a solid))': 'reference parts that are zero-thickness surfaces in the source, written as surfaces',
    'N parts are surface models / open shells in the source (copied faithfully; no solid to check)': 'parts that are surface models / open shells in the source, copied faithfully',
    'N bolts guessed from hole stacks (no bolt record)': 'bolts placed from hole stacks, no bolt record in the source',
}
def lack_label(w_):
    if w_ in LACK: return LACK[w_]
    s_ = re.sub(r'^(N/N |N )', '', w_)
    if len(s_) > 80 and ' (' in s_: s_ = s_[:s_.index(' (')]   # drop a long trailing explanation rather than cut it mid-word
    return s_
WHAT = {'source_data_absent': 'missing or incomplete in the source itself', 'converter_feature': 'converter limitation', 'profile_or_catalog_missing': 'catalog / profile not stored in the source',
        'source_damaged': 'source damaged'}

# ================================================================= HTML
css = open(f'{H}/report.css').read() + """
.kb{display:inline-block;border-radius:10px;padding:1px 8px;font-size:11px;font-weight:700;margin-left:4px;vertical-align:1px}
.ks{background:rgba(52,211,153,.15);color:var(--gd);border:1px solid rgba(52,211,153,.35)}
.ka{background:rgba(251,191,36,.12);color:var(--am);border:1px solid rgba(251,191,36,.35)}
.lacks{margin:6px 0 0;padding-left:18px;color:var(--mut);font-size:12px}.lacks li{margin:2px 0}
"""
o = []; w = o.append
w(f'<meta charset="utf-8">\n<title>Partial STEP Pack</title>\n<meta name="description" content="Zenitude disks: {NPROJ} partial-STEP project packages (separate folder), every STEP flagged with what it lacks.">\n<style>{css}</style>\n')
w('<div class="wrap">\n<div class="hero">\n  <h1>Structural Steel Detailing &amp; Fabrication Data Pack <span class="sub">· Partial-STEP tier</span></h1>\n')
w(f'  <p>{n(NPROJ)} steel-detailing project packages whose 3D models converted to STEP only <b>partially</b> (class 2): {n(NSTD)} projects in which no model '
  f'converted perfectly, carrying their source models, shop drawings and CNC programs, and {n(NADD)} add-ons that hold the partial STEP files of projects '
  f'already in the perfect pack. Kept in a separate folder (<code>packages/3d_partial/</code>) and counted separately from the perfect pack'
  + (f' ({n(PERF_N)} projects)' if PERF_N else '') + '. Every STEP file says exactly what it lacks.</p>\n')
w('  <span class="tag">DESIGN / CAD</span><span class="tag">PARTIAL TIER · class-2 STEP</span><span class="tag">SOURCE Zenitude data-3 + data-4</span>'
  '<span class="tag">includes Disk-1 and Disk-2</span><span class="tag">Tekla Structures · SDS/2</span>\n')
vl = ''
if VER:
    vl = (f" <b>{n(VER['ok'])} of {n(VER['projects'])}</b> partial packages pass the full package verify (every file present at its recorded size and SHA-256, "
          f"no extra or duplicate objects).")
still = ''
if FIN and FIN.get('still_converting_not_waited'):
    still = ' One Tekla DB1 model (30.7 MB, Littleton Elementary School) was still re-converting at the final pass and is added automatically when it completes.'
dem = ''
if os.path.exists(f'{D}/projects_f1.json'):
    _F = json.load(open(f'{D}/projects_f1.json')); _F = _F if isinstance(_F, list) else _F.get('projects', _F)
    _pm = {s_['model_id'] for p_ in P for s_ in p_['steps']}
    NDEMF = sum(1 for p_ in _F for s_ in p_['steps'] if s_['model_id'] in _pm)
    NDEM = len({s_['model_id'] for p_ in _F for s_ in p_['steps'] if s_['model_id'] in _pm})
    if NDEM: dem = (f' {n(NDEM)} of these models still also have an earlier class-1 conversion (older converter code) in the perfect pack '
                    f'({n(NDEMF)} STEP files); the re-run graded them class 2, and those perfect-pack copies are listed for removal, awaiting the owner&rsquo;s OK.')
w(f'  <div class="growing"><b>Final, {STAMP}.</b> Every conversion re-run on both disks is finished and the partial tier is fully packaged and verified.{vl}{still}{dem} '
  f'Nothing in this tier counts toward the perfect numbers. Every number is counted from the delivered packages and the conversion indexes, not estimated, '
  f'except where a section says it is sampled.</div>\n</div>\n')
w('<div class="kpis">\n')
w(f'  <div class="kpi hl"><div class="v">{n(NPROJ)}</div><div class="l">partial-tier projects</div><div class="d">{n(NSTD)} partial-only · {n(NADD)} add-ons</div></div>\n')
w(f'  <div class="kpi"><div class="v">{n(STP)}</div><div class="l">partial STEP files</div><div class="d dm">carrying {n(models["all"])} partial models</div></div>\n')
w(f'  <div class="kpi"><div class="v">{n(CTS)}</div><div class="l">complete to source</div><div class="d dm">STEP = everything the source holds</div></div>\n')
w(f'  <div class="kpi"><div class="v">{n(APX)}</div><div class="l">approximated</div><div class="d dm">some parts left out or stood in</div></div>\n')
w(f'  <div class="kpi"><div class="v">{n(F2)}</div><div class="l">2D files</div><div class="d dm">PDF · DG · DPM · DXF · DWG</div></div>\n')
w(f'  <div class="kpi"><div class="v">{tb(TOTB)}</div><div class="l">total size</div><div class="d dm">{n(TOTF)} distinct files</div></div>\n</div>\n')

# ---- What is in the pack
mx = max(chsum(DI, k)[1] for k, _, _ in CH)
w('<h2>What is in the pack</h2>\n<div class="card">\n')
w(f'  <p class="lead">Every project here carries at least one partial STEP model &mdash; that is what puts it in this tier. Of the {n(NSTD)} partial-only projects, '
  f'{pct(po_draw, NSTD)} carry drawings, {pct(po_nc1, NSTD)} carry CNC programs and {pct(po_join, NSTD)} carry BOM or KISS join tables. The {n(NADD)} add-ons hold '
  f'only partial STEP files (and SDS/2 job zips the perfect package lacks); their drawings, CNC programs and source models are in the project&rsquo;s perfect package, '
  f'never stored twice.</p>\n')
w('  <div class="srow shead"><div class="slabel"></div><div class="strack2">bar length &middot; channel size</div><div class="sval w2">files</div><div class="sval w2">size</div></div>\n')
for keys, label, g in sorted(CH, key=lambda c: -chsum(DI, c[0])[1]):
    f_, b_ = chsum(DI, keys)
    if not f_: continue
    w(f'  <div class="barrow"><div class="blabel">{label}</div><div class="btrack"><div class="bfill" style="width:{max(0.4, 100 * b_ / mx):.1f}%;background:{GCOL[g]}"></div></div>'
      f'<div class="bval">{n(f_)}</div><div class="bgb">{gb(b_)}</div></div>\n')
w('  <p class="note">The STEP row holds only partial (class-2) conversions; class-1 STEP of the same projects ship in the perfect pack, class-3 conversions never ship. '
  'Each STEP row of a package manifest carries its class, its kind and the exact list of what it lacks.'
  + (f' The table counts distinct contents: of the {n(STP)} STEP files (one per model), {n(STP - S["distinct"]["files"]["model/step"])} pair '
     'converted from different source models came out byte-identical.' if STP - S["distinct"]["files"].get("model/step", STP) == 1 else '') + '</p>\n')
if PDFS:
    w(f'  <p class="note"><b>The drawings are CAD output.</b> At least {floor_m(pd_lo)} of the {n(NPDF)} PDFs in this tier are drawings, and at least {floor_m(pv_lo)} '
      f'of those are vector drawings &mdash; the geometry and the text are objects in the file, selectable and measurable. About {100 * pn_est:.0f}% are not '
      f'drawings (transmittals, logs and other paperwork). Measured on a random sample of {len(lab)} PDFs ({len(lab) // 2} per disk), weighted by each disk&rsquo;s '
      f'share of the channel, labelled by a rule that agrees with 584 of 600 hand-labelled PDFs (97.3%), taken at the one-sided 95% lower bound, reduced by the '
      f'rule&rsquo;s measured over-count (1.7%) and rounded down.</p>\n')
w('</div>\n')

# ---- Every disk
def ctab(key):
    c = C[key]; bt = c['by_type']; bc = c['by_class']
    t = lambda p_: sum(bt.get(p_, {}).values())
    return c['n'], bc.get('1', 0), bc.get('2', 0), bc.get('3', 0), bt.get('ifc', {}).get('2', 0), bt.get('db1', {}).get('2', 0), bt.get('sds2', {}).get('2', 0)
w('<h2>Every disk</h2>\n<div class="card">\n')
w('  <p class="lead">Two disks were converted in full: <b>data-3</b>, which holds every Disk-2 archive byte for byte plus 510 of its own, and <b>data-4</b>, '
  'which holds every Disk-1 archive plus the TEKLA-HYD/Backup 2026 folder. The &ldquo;from Disk-1/2&rdquo; and &ldquo;only on&rdquo; rows split the disk above them.</p>\n')
w('  <h3>1 · Partial models found on each disk</h3>\n  <div class="tw"><table class="num">\n  <tr><th>Disk</th><th>Models found</th><th>Perfect (class 1)</th>'
  '<th class="g">Partial (class 2)</th><th>of which IFC</th><th>Tekla DB1</th><th>SDS/2</th><th>Bad (class 3)</th></tr>\n')
rows = [('data-4', '<b>Data-4</b>', ''), ('disk-1', ORIG['disk-1'][0], 'sub'), ('data-4-only', ORIG['data-4-only'][0], 'sub'),
        ('data-3', '<b>Data-3</b>', ''), ('disk-2', ORIG['disk-2'][0], 'sub'), ('data-3-only', ORIG['data-3-only'][0], 'sub')]
for key, lbl, cls in rows:
    nn_, c1, c2, c3, i2, d2, s2 = ctab(key)
    w(f'  <tr class="{cls}"><td>{lbl}</td><td>{n(nn_)}</td><td>{n(c1)}</td><td class="g">{n(c2)}</td><td>{n(i2)}</td><td>{n(d2)}</td><td>{n(s2)}</td><td>{n(c3)}</td></tr>\n')
w('  </table></div>\n  <p class="note">Each disk is counted on its own here, so a model present on both disks appears in both rows; the packages below hold each '
  'model once. A Tekla DB1 partial model is packaged with its newest (code-v) conversion only.</p>\n')
w('  <h3>2 · What is packaged in the partial tier, per disk</h3>\n  <div class="tw"><table class="num">\n  <tr><th>Origin</th><th class="g">Projects</th><th>Partial-only</th>'
  '<th>Add-ons</th><th>Partial STEP</th><th>Complete to source</th><th>Approximated</th><th>2D files</th><th>CNC (NC1)</th><th>All files</th><th>Size</th></tr>\n')
for key, lbl, cls in rows + [('all', 'Partial tier', 'tot')]:
    dd = DI if key == 'all' else S['distinct_by_disk'].get(key) or {'files': {}, 'bytes': {}}
    f2, _ = grp(dd, '2d') if dd['files'] else (0, 0); ff, _ = grp(dd, 'fab') if dd['files'] else (0, 0)
    w(f'  <tr class="{cls}"><td>{lbl}</td><td class="g">{n(proj[key])}</td><td>{n(proj[key] - addon[key])}</td><td>{n(addon[key])}</td><td>{n(steps[key])}</td>'
      f'<td>{n(kinds[(key, "complete_to_source")])}</td><td>{n(kinds[(key, "approximated")])}</td><td>{n(f2)}</td><td>{n(ff)}</td>'
      f'<td>{n(sum(dd["files"].values()))}</td><td>{gb(sum(dd["bytes"].values()))}</td></tr>\n')
w('  </table></div>\n  <p class="note">Files are distinct within each row (two copies of the same bytes count once, by SHA-256); the tier row is smaller than the sum '
  'of the disks because the disks share files. Origins are exact: an archive is &ldquo;from Disk-1&rdquo; or &ldquo;from Disk-2&rdquo; when the same path holds a '
  'byte-identical copy (same size) on that disk.</p>\n</div>\n')

# ---- Where the projects come from
w('<h2>Where the projects come from</h2>\n<div class="card">\n')
segs = [('disk-1', 'Disk-1 archives (on data-4)', 'var(--ac)'), ('data-4-only', 'only on data-4', '#7c9cf0'), ('disk-2', 'Disk-2 archives (on data-3)', 'var(--cy)'),
        ('data-3-only', 'only on data-3', '#5fb8c9')]
w(f'  <p class="lead">Every one of the {n(NPROJ)} partial-tier projects, by the disk its archive came from.</p>\n  <div class="stack">')
for k_, lbl, col in segs:
    w(f'<div style="width:{100 * proj[k_] / NPROJ:.2f}%;background:{col}" title="{lbl}: {proj[k_]}"><span>{n(proj[k_]) if proj[k_] / NPROJ > 0.05 else ""}</span></div>')
w('</div>\n  <div class="legend">' + ''.join(f'<span><i style="background:{col}"></i>{lbl} &mdash; <b>{n(proj[k_])}</b></span>' for k_, lbl, col in segs) + '</div>\n')
w('  <h3>By source folder</h3>\n  <div class="tw"><table class="num slim">\n  <tr><th>Disk</th><th style="text-align:left">Folder on the disk</th><th class="g">Projects</th>'
  '<th style="text-align:left">Origin of those projects</th><th>Partial STEP</th><th>All files</th><th>Size</th></tr>\n')
fold = collections.defaultdict(collections.Counter); fsteps = collections.Counter()
for p in P:
    fold[(p['disk'], p.get('src_folder'))][p.get('origin')] += 1; fsteps[(p['disk'], p.get('src_folder'))] += len(p['steps'])
for (dk, fo), og in sorted(fold.items(), key=lambda x: (x[0][0] != 'data-4', -sum(x[1].values()))):
    dd = S['distinct_by_disk'].get(f'src|{dk}|{fo}') or {'files': {}, 'bytes': {}}
    ogs = ' · '.join(f'{n(c)} {ORIG[o_][0].replace("↳ ", "")}' for o_, c in sorted(og.items(), key=lambda x: -x[1]) if o_ in ORIG)
    w(f'  <tr><td>{dk.capitalize()}</td><td class="l">{E(fo or "")}</td><td class="g">{n(sum(og.values()))}</td><td class="l">{ogs}</td><td>{n(fsteps[(dk, fo)])}</td>'
      f'<td>{n(sum(dd["files"].values()))}</td><td>{gb(sum(dd["bytes"].values()))}</td></tr>\n')
w('  </table></div>\n</div>\n')

# ---- How partial is labelled
w('<h2>How &ldquo;partial&rdquo; is labelled</h2>\n<div class="card">\n<div class="grid3">\n')
w('  <div class="step"><div class="sn">1 · Graded against the source</div><p>Every STEP is graded part by part against its source model. A model is '
  '<b>class 2 (partial)</b> when at least one part is not an exact closed solid with the source&rsquo;s volume and placement. Class 1 ships in the perfect pack; '
  'class 3 (failed) ships nowhere. Nothing is remodelled or invented to raise a grade.</p></div>\n')
w(f'  <div class="step"><div class="sn">2 · Complete to source <span class="kb ks">{n(CTS)}</span></div><p>The STEP holds everything the source file holds. The '
  'shortfall is the source&rsquo;s own: parts the source stores only as surface models or open shells, written faithfully as surfaces. Every stand-in in the STEP is a '
  'faithful copy of source geometry.</p></div>\n')
w(f'  <div class="step"><div class="sn">3 · Approximated <span class="kb ka">{n(APX)}</span></div><p>Some parts were left out or stood in by the converter: '
  'nominal bolts and washers, member or joist envelopes, concrete prisms, slots cut round, stud shanks without heads, shells closed by healing. Each STEP row lists '
  'every such shortfall with its part count.</p></div>\n</div>\n')
cat_tot = sum(ISS['categories'].values()) or 1
w('  <h3>What the partial models lack, by source type</h3>\n  <div class="grid3">\n')
for p_, lbl in (('ifc', 'IFC'), ('db1', 'Tekla DB1'), ('sds2', 'SDS/2')):
    nm = ISS['models'].get(p_, 0)
    w(f'  <div class="step"><div class="sn">{lbl} &middot; {n(nm)} models</div><ol class="lacks">')
    for c_, what, v in ISS['issues_top_by_pipeline'].get(p_, [])[:6]:
        w(f'<li><b>{n(v)}</b> &middot; {E(lack_label(what))} <span class="dm">({WHAT.get(c_, c_)})</span></li>')
    w('</ol></div>\n')
w(f'  </div>\n  <p class="note">Counts are packaged partial models that show each shortfall &mdash; all {n(sum(ISS["models"].values()))} counted once each, a shortfall once per model (a model usually shows several) &mdash; read from the final conversion indexes. The '
  'category says where the gap comes from: missing or incomplete in the source itself, a catalog or profile the source does not store, or a converter limitation.</p>\n</div>\n')

# ---- What the dataset is made of
w('<h2>What the dataset is made of</h2>\n<div class="card">\n  <p class="lead">Each channel as a share of the partial tier.</p>\n')
w('  <div class="tw"><table class="num slim"><tr><th>Channel</th><th>share of files</th><th>share of size</th></tr>\n')
for keys, label, g in sorted(CH, key=lambda c: -chsum(DI, c[0])[1]):
    f_, b_ = chsum(DI, keys)
    if f_: w(f'  <tr><td><span class="dot" style="background:{GCOL[g]}"></span>{label}</td><td>{100 * f_ / TOTF:.2f}%</td><td>{100 * b_ / TOTB:.1f}%</td></tr>\n')
w(f'  </table></div>\n  <p class="note">{gb(TOTB)} across {n(TOTF)} distinct files &nbsp;·&nbsp; 3D {100 * B3 / TOTB:.1f}% &nbsp;·&nbsp; 2D {100 * B2 / TOTB:.1f}% &nbsp;·&nbsp; '
  f'tables {100 * BT / TOTB:.1f}% &nbsp;·&nbsp; fabrication {100 * BF / TOTB:.1f}% of the bytes.</p>\n</div>\n')

# ---- 3D live (hero partial model)
hero = MODELS.get('hero')
if hero:
    hp = PBY.get(hero['project_id']); hs = next((s_ for s_ in (hp or {}).get('steps', []) if s_['relpath'] == hero['relpath']), {})
    w('<h2>The 3D channel, live</h2>\n<div class="card">\n  <div id="viewer" data-glb="models/hero.json"><div class="vhint">drag to rotate · scroll to zoom</div>'
      '<button class="vbtn" id="spin" type="button">pause rotation</button></div>\n')
    w(f'  <p class="note">A partial model from this tier, rendered in your browser from the package&rsquo;s own STEP file: <b>{E(hero["relpath"].rsplit("/", 1)[-1][:-5])}</b> '
      f'({hero["disk"]}, from {hero["source"].upper()}), {kind_badge(hero.get("kind"))}, {n(hero["triangles"])} triangles. What it lacks is listed on its manifest row; '
      f'everything shown is the converted geometry, nothing remodelled for this page.</p>\n</div>\n')

# ---- Channel coverage (partial-only projects)
w(f'<h2>Channel coverage</h2>\n<div class="card">\n  <p class="lead">Share of the {n(NSTD)} partial-only projects that carry each channel, measured from the files '
  f'themselves (add-ons are left out: their channels are in the perfect package). Drawings reach {pct(po_draw, NSTD)} and CNC programs {pct(po_nc1, NSTD)}; '
  f'{pct(po_all3, NSTD)} carry drawings, CNC programs and a join table together ({n(po_all3)} projects).</p>\n')
covrows = [('model/ifc', 'IFC models', '3d'), ('model/sds2', 'SDS/2 job zips', '3d'), ('model/db1', 'Tekla model databases', '3d'), ('drawings/pdf', 'Drawings (PDF)', '2d'),
           ('drawings/dg', 'SDS/2 drawing files', '2d'), ('drawings/dxf', 'DXF piece outlines', '2d'), ('drawings/dwg', 'DWG', '2d'), ('drawings/dpm', 'Tekla drawing files', '2d'),
           ('fab/nc1', 'CNC programs (NC1)', 'fab'), ('tables/bom', 'BOM tables', 'tab'), ('tables/kiss', 'KISS join tables', 'tab'), ('tables/abm', 'Excel / ABM sheets', 'tab')]
for k_, lbl, g in sorted(covrows, key=lambda r: -pocov[r[0]]):
    c_ = pocov[k_]
    if not c_: continue
    w(f'  <div class="barrow"><div class="blabel">{lbl}</div><div class="btrack"><div class="bfill" style="width:{100 * c_ / NSTD:.1f}%;background:{GCOL[g]}"></div></div>'
      f'<div class="bval">{pct(c_, NSTD)}</div><div class="bgb">{n(c_)} projects</div></div>\n')
w('</div>\n')

# ---- One job, three ways
if T3:
    w('<h2>One job, three ways</h2>\n<div class="card">\n' + T3['html'] + '\n</div>\n')
    if T3.get('crops'):
        w('<h2>Drawing detail</h2>\n<div class="card">\n  <div class="grid2w">\n')
        for c_ in T3['crops']:
            w(f'  <figure><a class="zoom" href="2d/{c_["name"]}.jpg" target="_blank" rel="noopener"><img src="2d/{c_["name"]}.jpg" alt="{E(c_["caption"])}" loading="lazy">'
              f'<span class="zi">open full size ↗</span></a><figcaption>{c_["caption"]}</figcaption></figure>\n')
        w('  </div>\n</div>\n')

# ---- The join
if J:
    h_ = J['nc1_header']; lines = J['nc1_text_head']
    w('<h2>The join</h2>\n<div class="card">\n')
    w(f'  <p class="lead">One piece, three ways, from a partial-only project. Mark <b>{E(h_.get("mark", J["mark"]))}</b>: the shop drawing dimensions it, the DXF gives '
      f'its cut outline, and the CNC program states the stock it is made from &mdash; all three named for the mark. The project&rsquo;s 3D model is partial; its '
      f'drawings and CNC programs are complete production files.</p>\n  <div class="grid2">\n')
    w(f'  <figure><a class="zoom" href="2d/join_sheet.jpg" target="_blank" rel="noopener"><img src="2d/join_sheet.jpg" alt="Shop drawing" loading="lazy"><span class="zi">open full size ↗</span></a>'
      f'<figcaption>The sheet &mdash; mark <b>{E(h_.get("mark", ""))}</b>, profile <b>{E(h_.get("profile", ""))}</b>, grade <b>{E(h_.get("grade", ""))}</b>, '
      f'quantity <b>{E(h_.get("qty", ""))}</b>. {E(J.get("project_label", ""))}</figcaption></figure>\n')
    ex = J.get('dxf_ext') or [0, 0]
    w(f'  <figure><img src="2d/join_dxf.png" alt="DXF outline" loading="lazy"><figcaption>The outline &mdash; the DXF for the same mark, {ex[0]:.2f} by {ex[1]:.2f} '
      f'{J.get("unit", "in")}.</figcaption></figure>\n  </div>\n')
    w('  <div class="cap" style="margin-top:14px">The CNC program for the same mark, as it ships:</div><pre class="code">' + '\n'.join(E(x.rstrip()) for x in lines[:24]) + '</pre>\n')
    if J.get('arith'): w(f'  <p class="note">{J["arith"]}</p>\n')
    w('</div>\n')

# ---- Range of drawings
if RANGE:
    w('<h2>Range of drawings</h2>\n<div class="card">\n  <div class="grid4">\n')
    for r in RANGE:
        w(f'  <figure><a class="zoom" href="2d/range_{r["n"]:02d}_full.jpg" target="_blank" rel="noopener"><img src="2d/range_{r["n"]:02d}.jpg" alt="{E(r["caption"])}" loading="lazy">'
          f'<span class="zi">open full size ↗</span></a><figcaption>{E(r["caption"])} <span class="ch">{r["disk"]} · {r["w_in"]:.0f} × {r["h_in"]:.0f} in</span></figcaption></figure>\n')
    w(f'  </div>\n  <p class="note">Click any sheet to open it at full size (2800 px). {len(RANGE)} sheets from {len({r["project_id"] for r in RANGE})} different '
      'partial-tier projects, half from each disk. The 3D models of these jobs are partial; the drawings are complete production sheets.</p>\n</div>\n')

# ---- Range of models
tiles = [t for t in ('t1', 't2', 't3', 't4', 't5') if t in MODELS]
if tiles:
    w('<h2>Range of models</h2>\n<div class="card">\n  <p class="lead">A partial model from each of five more partial-only projects, rendered from that package&rsquo;s own '
      'STEP file &mdash; same camera, same scale treatment, same background as the perfect report. Each tile says how the model is partial.</p>\n  <div class="grid5">\n')
    for t in tiles:
        m = MODELS[t]; c = pc(m['project_id']); a1, a2 = counts_line(c, True) if c else ('', '')
        _sa = (PBY.get(m['project_id']) or {}).get('source_archive') or m['project_id']
        _parts = re.split(r'[/\\]', _sa); name = re.sub(r'\.(7z|zip|rar)$', '', _parts[-1], flags=re.I)
        if len(name) < 14 and len(_parts) > 1: name = _parts[-2] + ' / ' + name
        name = name[:46]
        w(f'  <figure class="smp" data-glb="models/{t}.json"><div class="sshell"><img src="models/{t}.jpg" alt="{E(name)} model" loading="lazy">'
          f'<button class="sgo" type="button" disabled>still</button></div><figcaption><span class="pk">{E(m["relpath"].rsplit("/", 1)[-1][:-5][:40])}</span>'
          f'<span class="ch">{kind_badge(m.get("kind"))} {m["disk"]} · from {m["source"].upper() if m["source"] != "db1" else "Tekla DB1"}</span>'
          f'<span class="ch">{E(name)}</span><span class="ch">{a1}</span><span class="ch">{a2}</span></figcaption></figure>\n')
    w('  </div>\n  <p class="note">Each tile is live &mdash; click <b>interact</b> to load the model and drag it around. Rendered directly from the shipped partial '
      'STEP files; nothing was remodelled or redrawn for this page.</p>\n</div>\n')

# ---- Package structure
w('<h2>Package structure</h2>\n<div class="card">\n  <p class="lead">Exactly the perfect pack&rsquo;s package format. A partial-only package carries all its sources; '
  'an add-on carries only its partial STEP files (and SDS/2 job zips the perfect package lacks) and names the perfect package that holds the sources.</p>\n')
tree = [('tf', '▪', 'project.json', 'tier: partial · addon_of (add-ons) · partial_steps by kind · counts · declared gaps'),
        ('tf', '▪', 'manifest.jsonl', 'one line per file — path, bytes, sha256; STEP rows: class 2, partial.kind, issues, missing, stand-ins, converted_from(_package)'),
        ('t3', '●', 'model/', '3D geometry'), ('t3 ts', '└', 'step/', 'class-2 STEP conversions only'), ('t3 ts', '└', 'ifc/  db1/ db2/', 'source models (partial-only projects)'),
        ('t3 ts', '└', 'sds2/', 'SDS/2 job zips; members not found in storage are listed per zip'),
        ('t2', '●', 'drawings/', 'pdf/ dg/ dpm/ dxf/ dwg/ (partial-only projects)'), ('tfb', '●', 'fab/', 'nc1/ (partial-only projects)'),
        ('tt', '●', 'tables/', 'bom/ kiss/ abm/ drawing_index/ (partial-only projects)')]
for cls, ico, nm, desc in tree:
    w(f'  <div class="trow {cls}"><span class="tico">{ico}</span><span class="tname">{nm}</span><span class="tdesc">{desc}</span></div>\n')
w('</div>\n')

# ---- Native files
db = chsum(DI, ['model/db1', 'model/db2']); dpm = chsum(DI, ['drawings/dpm']); dg = chsum(DI, ['drawings/dg']); s2 = chsum(DI, ['model/sds2'])
w('<h2>Native Tekla and SDS/2 files</h2>\n<div class="card">\n')
w(f'  <p class="lead">In this tier: <b>{n(db[0])}</b> Tekla model databases ({gb(db[1])}), <b>{n(dpm[0])}</b> Tekla drawing files ({gb(dpm[1])}), <b>{n(s2[0])}</b> SDS/2 '
  f'job zips ({gb(s2[1])}) and <b>{n(dg[0])}</b> SDS/2 drawing files ({gb(dg[1])}). They are the authoring originals of models that converted only partially '
  f'&mdash; for a buyer with a Tekla Structures or SDS/2 licence, the complete form of those jobs.</p>\n')
w(f'  <p class="note">Of the {n(STP)} partial STEP files, {n(src[("all", "ifc")])} come from IFC, {n(src[("all", "db1")])} from native Tekla databases and '
  f'{n(src[("all", "sds2")])} from SDS/2 models.</p>\n</div>\n')

# ---- Uses
w('<h2>How it can be used</h2>\n<div class="card">\n  <div class="tw"><table><tr><th>Use case</th><th>What supports it</th></tr>\n')
uses = [('Conversion and repair research', f'{n(STP)} STEP files each paired with its source model and an exact, per-part list of what the conversion lacks'),
        ('Geometry learning with known gaps', f'{n(CTS)} STEP files that hold everything their source holds; {n(APX)} with every stand-in labelled'),
        ('Drawing to model grounding', f'{n(DI["files"].get("drawings/pdf", 0))} PDF drawings next to the models of the same job'),
        ('CAD to CNC program generation', f'{n(FF)} NC1 programs with per-piece geometry and hole patterns'),
        ('Native-format learning', f'{n(dg[0])} SDS/2 drawing files, {n(dpm[0])} Tekla drawing files, {n(db[0])} Tekla model databases')]
for u, s_ in uses: w(f'  <tr><td>{u}</td><td>{s_}</td></tr>\n')
w('  </table></div>\n</div>\n')

# ---- Samples
smp = [(MODELS[t]['project_id'], t) for t in ('hero',) + tuple(tiles) if t in MODELS]
if J: smp.append((J['project_id'], 'join'))
if T3: smp.append((T3['project_id'], 'three'))
if smp:
    w('<h2>Samples</h2>\n<div class="card">\n  <div class="tw"><table><tr><th>Sample package</th><th>Disk</th><th>Partial STEP kinds</th><th>Contents</th></tr>\n')
    seen = set()
    for pid, why in smp:
        c = pc(pid)
        if not c or pid in seen: continue
        seen.add(pid)
        kk = ', '.join(f'{n(v)} {k.replace("_", " ")}' for k, v in c['kinds'].items())
        w(f'  <tr><td>{E(pid.split("__", 1)[1][:80])}</td><td>{c["disk"]}</td><td>{kk}</td><td>{counts_line(c)}</td></tr>\n')
    w('  </table></div>\n  <p class="note">Counts are read from the delivered partial packages themselves.</p>\n</div>\n')

# ---- Classification / reference
w('<h2>Classification</h2>\n<div class="card">\n  <table class="meta">\n')
for k_, v_ in (('Asset class', 'Design / CAD'), ('Tier', 'Partial STEP (class 2) — separate from the perfect pack'),
               ('Modality', 'Multimodal — 3D geometry (partial), 2D vector and raster drawings, CNC text, tabular'),
               ('Domain', 'Structural steel detailing and fabrication'), ('Provenance', 'Naturally occurring production work'),
               ('Quality gate', 'Class-2 STEP only, each with its kind and full shortfall list; every package verified (size and SHA-256 of every file)')):
    w(f'  <tr><td>{k_}</td><td>{v_}</td></tr>\n')
w('  </table>\n</div>\n')
w('<h2>Channel reference</h2>\n<div class="card ref">\n')
for k_, v_ in (('Partial STEP', 'Class-2 conversions. complete_to_source: the STEP holds everything the source holds. approximated: some parts left out or stood in, each listed.'),
               ('Source models', 'IFC, Tekla DB1/DB2 and SDS/2 job zips — the authoring data the STEP was converted from (in the perfect package for add-ons).'),
               ('Drawings', 'Shop and erection drawings as PDF, DXF and DWG, plus native SDS/2 and Tekla drawing files.'),
               ('Fabrication output (NC1)', 'DSTV NC1, one file per piece: mark, profile, length, grade and every hole and cut.'),
               ('Tables', 'BOM and KISS assembly-to-submaterial joins and ABM / Excel quantity sheets.')):
    w(f'  <p><b>{k_}</b> &nbsp;{v_}</p>\n')
w(f'</div>\n<p class="foot">Built {STAMP} from the delivered partial packages (stats run {E(S["run"])}, {E(S["at"])}) and the data-3 and data-4 conversion indexes. '
  'Files counted distinct by SHA-256. Companion to the perfect-pack report.</p>\n</div>\n')
w('<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>\n<script>' + open(f'{H}/report.js').read() + '</script>\n')
open(f'{OUT}/index.html', 'w').write(''.join(o))
tot_b = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(OUT) for f in fs)
print('wrote', f'{OUT}/index.html', len(''.join(o)), 'bytes; site', round(tot_b / 1e6, 1), 'MB | projects', NPROJ, 'partial-only', NSTD, 'add-ons', NADD,
      'STEP', STP, 'cts', CTS, 'apx', APX, '| sections: models', len(MODELS), 'range', len(RANGE), 'join', bool(J), 'three', bool(T3), 'pdfs', bool(PDFS))
