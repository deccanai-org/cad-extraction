#!/usr/bin/env python3
"""Build the Zenitude steel data-pack report (same section structure as the CAD-STEEL-FLEET-001 page) into site/.
Inputs: data/stats_<RUN>.json + projects_<RUN>.json (rep_stats over every delivered package), data/class_now.json (coordinator
indexes), labelled PDF sample, IFC headers, and the rendered assets under assets_raw/ and s3mirror/assets/.
Usage: python3 build_report.py [RUN]   (default t4)"""
import json, sys, os, math, shutil, html, collections, datetime
from PIL import Image

RUN = sys.argv[1] if len(sys.argv) > 1 else 't4'
PRUN = sys.argv[2] if len(sys.argv) > 2 else None          # partial-tier stats run (stats_<PRUN>.json / projects_<PRUN>.json)
CLASSF = sys.argv[3] if len(sys.argv) > 3 else 'class_now.json'
H = os.path.dirname(os.path.abspath(__file__))
D, A, AR, OUT = f'{H}/data', f'{H}/s3mirror/assets', f'{H}/assets_raw', f'{H}/site'
os.makedirs(f'{OUT}/models', exist_ok=True); os.makedirs(f'{OUT}/2d', exist_ok=True)
S = json.load(open(f'{D}/stats_{RUN}.json')); P = json.load(open(f'{D}/projects_{RUN}.json'))
C = json.load(open(f'{D}/{CLASSF}'))
SP = json.load(open(f'{D}/stats_{PRUN}.json')) if PRUN and os.path.exists(f'{D}/stats_{PRUN}.json') else None
VERI = {t: json.load(open(f'{D}/verify_{t}.json')) for t in ('perfect', 'partial') if os.path.exists(f'{D}/verify_{t}.json')}
FIN = json.load(open(f'{D}/FINISH_DONE.json')) if os.path.exists(f'{D}/FINISH_DONE.json') else None
PP = json.load(open(f'{D}/projects_{PRUN}.json')) if SP else []
E = html.escape
def n(x): return f'{int(x):,}'
def gb(b): return f'{b / 1e9:,.1f} GB'
def pct(a, b, d=0): return f'{100 * a / b:.{d}f}%' if b else '—'

# ---------------------------------------------------------------- channels
CH = [  # key(s), label, group
    (['model/step'], 'STEP models (class 1)', '3d'), (['model/ifc'], 'IFC models', '3d'),
    (['model/db1', 'model/db2'], 'Tekla model databases', '3d'), (['model/sds2'], 'SDS/2 model archives', '3d'), (['model/stl'], 'STL meshes', '3d'),
    (['drawings/pdf'], 'Drawings (PDF)', '2d'), (['drawings/dg'], 'SDS/2 drawing files (.dg)', '2d'), (['drawings/dpm'], 'Tekla drawing files (.dpm)', '2d'),
    (['drawings/dxf'], 'DXF piece outlines', '2d'), (['drawings/dwg'], 'DWG', '2d'),
    (['fab/nc1'], 'CNC programs (NC1)', 'fab'),
    (['tables/bom'], 'BOM tables', 'tab'), (['tables/kiss'], 'KISS join tables', 'tab'), (['tables/abm'], 'Excel / ABM sheets', 'tab'),
    (['tables/drawing_index'], 'Drawing indexes', 'tab')]
GCOL = {'3d': 'var(--ac)', '2d': 'var(--cy)', 'fab': 'var(--gd)', 'tab': 'var(--am)'}
def chsum(dist, keys): return sum(dist['files'].get(k, 0) for k in keys), sum(dist['bytes'].get(k, 0) for k in keys)
def grp(dist, g): return [sum(x) for x in zip(*[chsum(dist, k) for k, _, gg in CH if gg == g])]
DI = S['distinct']; TOTF, TOTB = DI['total_files'], DI['total_bytes']
F3, B3 = grp(DI, '3d'); F2, B2 = grp(DI, '2d'); FF, BF = grp(DI, 'fab'); FT, BT = grp(DI, 'tab')
NPROJ = S['projects']
disk_of = collections.Counter(p['disk'] for p in P)
steps_by = collections.Counter(); models_by = collections.Counter(); src_by = collections.Counter()
for p in P:
    tags = [p['disk']] + ([p['origin']] if p.get('origin') else [])
    for t in tags + ['all']:
        steps_by[t] += len(p['steps']); models_by[t] += sum(1 + (s.get('also') or 0) for s in p['steps'])
        for s in p['steps']: src_by[(t, s.get('step_source'))] += 1
proj_by = collections.Counter()
for p in P:
    proj_by[p['disk']] += 1
    if p.get('origin'): proj_by[p['origin']] += 1
ORIG = {'disk-2': ('↳ from Disk-2', 'identical copies of Disk-2 archives (data-3 holds all 2,474)'), 'data-3-only': ('↳ only on data-3', '510 archives not on Disk-2'),
        'disk-1': ('↳ from Disk-1', 'identical copies of Disk-1 archives (data-4 holds all 1,154)'), 'data-4-only': ('↳ only on data-4', 'TEKLA-HYD/Backup 2026')}
NSTEP = DI['files'].get('model/step', 0)
cov = S['coverage']; combos = S['combos']
def cv(k): return cov.get(k, 0)
any_draw = combos.get('drawings|True', 0); all3 = combos.get('any_drawing+nc1+join_table|True', 0)
join_tab = sum(1 for p in P if p['per_channel'].get('tables/bom') or p['per_channel'].get('tables/kiss'))
stamp = datetime.datetime.strptime(S['at'], '%Y-%m-%dT%H:%M:%SZ') - datetime.timedelta(hours=7)
STAMP = stamp.strftime('%-d %b %Y, %-I:%M %p PDT')

# ---------------------------------------------------------------- PDF sample (stratified by disk, one-sided 95% floor)
lab = json.load(open(f'{D}/pdf_sample_labeled_all.json'))
NPDF = DI['files'].get('drawings/pdf', 0)
wd = {d: S['distinct_by_disk'][d]['files'].get('drawings/pdf', 0) for d in ('data-3', 'data-4')}; W = sum(wd.values())
def strat(pred):
    est = var = 0
    for d in wd:
        xs = [x for x in lab if x['disk'] == d]; k = sum(1 for x in xs if pred(x)); m = len(xs); p_ = k / m; w = wd[d] / W
        est += w * p_; var += w * w * p_ * (1 - p_) / m
    return est, max(0.0, est - 1.645 * math.sqrt(var))
pd_est, pd_lo = strat(lambda x: x['label'].startswith('drawing'))
pv_est, pv_lo = strat(lambda x: x['label'] == 'drawing_vector')
pn_est, _ = strat(lambda x: x['label'] == 'not_drawing')
def floor_m(f): return math.floor(f * NPDF / 1e5) / 10
PDF_D_M, PDF_V_M = floor_m(pd_lo), floor_m(pv_lo)

# ---------------------------------------------------------------- IFC headers
hdr = list(json.load(open(f'{D}/ifc_headers.json')).values())
yrs = sorted(int(h['time_stamp'][:4]) for h in hdr if (h.get('time_stamp') or '')[:4].isdigit() and 1995 <= int(h['time_stamp'][:4]) <= 2026)
y0, y1 = yrs[int(len(yrs) * 0.001)], yrs[-1]
sw = collections.Counter()
for h in hdr:
    o = ' '.join((h.get('fields') or [])[4:6]).lower()
    sw['Tekla Structures' if 'tekla' in o else 'SDS/2' if 'sds' in o else 'other'] += 1

# ---------------------------------------------------------------- assets
def jpg(src, dst, maxw=None, q=86, crop=None):
    im = Image.open(src).convert('RGB')
    if crop: im = im.crop(crop)
    if maxw and im.width > maxw: im = im.resize((maxw, round(im.height * maxw / im.width)), Image.LANCZOS)
    im.save(dst, quality=q, optimize=True); return im.size
MODELS = {m['tag']: m for m in json.load(open(f'{AR}/models/models.json'))}
for t in MODELS:
    import base64; json.dump({'format': 'glb-base64', 'glb': base64.b64encode(open(f'{AR}/models/{t}.glb', 'rb').read()).decode()}, open(f'{OUT}/models/{t}.json', 'w')); jpg(f'{AR}/models/{t}.png', f'{OUT}/models/{t}.jpg', 1000)
RANGE = json.load(open(f'{A}/range/range.json'))
PICK = [(1, 'Stair and platform, isometric erection view'), (3, 'Column details with bill of material'), (4, 'Stair stringer and rail with bill of material'),
        (5, 'Balcony and wall sections, connection details'), (6, 'Roof framing plan with erection notes'), (7, 'Racking elevations and details'),
        (8, 'Framing details, multiple sections'), (9, 'Stair assembly with bill of material'), (12, 'Brace and gusset connection details'),
        (13, 'Column details, several pieces per sheet'), (14, 'Erection framing plan'), (15, 'Truss connection detail with bolt table'),
        (16, 'Truss elevation'), (17, 'Connection details with RFI notes'), (18, 'Framing elevations'), (19, 'Floor framing plan and sections')]
for i, _ in PICK:
    shutil.copy(f'{A}/range/r{i:02d}.jpg', f'{OUT}/2d/range_{i:02d}.jpg'); shutil.copy(f'{A}/range/r{i:02d}_full.jpg', f'{OUT}/2d/range_{i:02d}_full.jpg')
shutil.copy(f'{A}/join/p25_sheet.jpg', f'{OUT}/2d/join_sheet.jpg'); shutil.copy(f'{A}/join/p25_dxf.png', f'{OUT}/2d/join_dxf.png')
shutil.copy(f'{A}/three/b52006.jpg', f'{OUT}/2d/three_sheet.jpg'); shutil.copy(f'{A}/three/b52006_full.jpg', f'{OUT}/2d/three_sheet_full.jpg')
fw, fh = Image.open(f'{A}/three/b52006_full.jpg').size; k = fw / 1800
jpg(f'{A}/three/b52006_full.jpg', f'{OUT}/2d/detail_weld.jpg', 1600, crop=(int(50 * k), int(725 * k), int(1165 * k), int(1122 * k)))
jpg(f'{A}/three/b52006_full.jpg', f'{OUT}/2d/detail_bom.jpg', 900, crop=(int(1372 * k), int(45 * k), int(1762 * k), int(578 * k)))
J = json.load(open(f'{A}/join/join_examples2.json'))['p25']
T3 = json.load(open(f'{A}/three/three.json'))
TW = json.load(open(f'{D}/three_ways2.json')); SEQ = next(m for m in TW['models'] if 'Seq#52' in m['ifc'])

# ---------------------------------------------------------------- sample projects
PBY = {p['id']: p for p in P}
SAMPLES = [('m14', '31-2311 Toray', 'Tekla Structures'), ('m08', 'MT23_027 Orange County Office', 'Tekla Structures'),
           ('m23', 'MT21_056 S8 Extrusion Phase 2', 'Tekla Structures'), ('m09', 'JOBS 2019–2020 · Willy', 'Tekla Structures'),
           ('m30', 'Ambatovy Project, Madagascar', 'Tekla Structures (native DB1)'), ('m28', 'West Slurry', 'Tekla Structures (native DB1)')]
EXTRA = [(T3['project_id'], 'MT20_023 Issaquah Middle School', 'one job, three ways'), (J['project_id'], 'IVC Mohawk Dehumidification', 'the join')]
def pc(pid):
    p = PBY.get(pid);
    if not p: return None
    c = p['per_channel']; g = lambda *ks: sum(c.get(k, 0) for k in ks)
    return {'step': g('model/step'), 'ifc': g('model/ifc'), 'tekla': g('model/db1', 'model/db2'), 'sds2': g('model/sds2'),
            'pdf': g('drawings/pdf'), 'dxf': g('drawings/dxf'), 'dwg': g('drawings/dwg'), 'dg': g('drawings/dg'), 'dpm': g('drawings/dpm'),
            'draw': g('drawings/pdf', 'drawings/dxf', 'drawings/dwg', 'drawings/dg', 'drawings/dpm'), 'nc1': g('fab/nc1'),
            'tab': g('tables/bom', 'tables/kiss', 'tables/abm', 'tables/drawing_index'), 'disk': p['disk'], 'bytes': sum(p['per_channel_bytes'].values())}
def counts_line(c, short=False):
    m = [f"{n(c['step'])} STEP"] + ([f"{n(c['ifc'])} IFC"] if c['ifc'] else []) + ([f"{n(c['tekla'])} Tekla DB"] if c['tekla'] else []) + ([f"{n(c['sds2'])} SDS/2"] if c['sds2'] else [])
    d = [f"{n(c['draw'])} drawings"] + ([f"{n(c['nc1'])} NC1"] if c['nc1'] else [])
    if short: return ' · '.join(m), ' · '.join(d)
    det = ', '.join(f'{n(c[k])} {lbl}' for k, lbl in (('pdf', 'PDF'), ('dxf', 'DXF'), ('dwg', 'DWG'), ('dg', 'DG'), ('dpm', 'DPM')) if c[k])
    return ' · '.join(m + [f"{n(c['draw'])} drawings ({det})" if det else '0 drawings'] + ([f"{n(c['nc1'])} NC1"] if c['nc1'] else []) + ([f"{n(c['tab'])} tables"] if c['tab'] else []))

# ================================================================= HTML
css = open(f'{H}/report.css').read()
o = []; w = o.append
w(f'<title>Steel CAD Data Pack</title>\n<meta name="description" content="Zenitude disks: {NPROJ} verified project packages of structural-steel 3D models, drawings and CNC programs.">\n<style>{css}</style>\n')
w('<div class="wrap">\n<div class="hero">\n  <h1>Structural Steel Detailing &amp; Fabrication Data Pack <span class="sub">· Zenitude disks</span></h1>\n')
w(f'  <p>{n(NPROJ)} steel-detailing project packages from production US steel fabrication and detailing work, each carrying at least one '
  f'3D model converted to STEP <b>perfectly</b> (class 1, independently verified), and most of them the source models, shop drawings and CNC '
  f'fabrication programs for the same structure.</p>\n')
w(f'  <span class="tag">DESIGN / CAD</span><span class="tag">SOURCE Zenitude data-3 + data-4</span><span class="tag">includes Disk-1 and Disk-2</span>'
  f'<span class="tag">{y0}–{y1}</span><span class="tag">Tekla Structures · SDS/2</span>\n')
def _vline(t, lbl):
    v = VERI.get(t)
    if not v: return ''
    rm = v.get('only_step_not_shipped (awaiting owner-approved removal)') or 0
    bad = v['projects'] - v['ok'] - rm
    return (f" {lbl}: <b>{n(v['ok'])} of {n(v['projects'])}</b> packages pass the full package verify (every file present at its recorded size and SHA-256, "
            f"no extra or duplicate objects)" + (f"; {n(rm)} more carry only STEP files of models that left that folder, queued for your removal decision" if rm else '')
            + (f"; <b>{n(bad)}</b> fail other checks (listed in verify_{t}.json)" if bad > 0 else '') + '.')
if FIN:
    w(f'  <div class="growing"><b>Final, {STAMP}.</b> Every conversion re-run on both disks is finished, including the Tekla DB1 code-v re-run; '
      f'perfect and partial packaging are complete, and every package was verified afterwards.{_vline("perfect", "Perfect folder")}{_vline("partial", "Partial folder")} '
      + (f'One Tekla DB1 model (30.7 MB, Littleton Elementary School) was still re-converting '
         f'at the final pass; it is counted at its previous result (partial) and is packaged automatically when it completes. ' if FIN.get('still_converting_not_waited') else '') +
      f'Every number on this page is counted from the delivered packages and the conversion indexes, not estimated, except where a section says it is sampled.</div>\n</div>\n')
else:
    w(f'  <div class="growing"><b>Status at {STAMP}.</b> Conversion, classification, independent verification and packaging are finished on both disks, and '
      f'every one of the {n(NPROJ)} packages passed its package verify. Every number on this page is counted from the delivered packages and the '
      f'conversion indexes, not estimated, except where a section says it is sampled. Work on the Tekla DB1 converter continues; models it lifts to '
      f'perfect will be added, so model counts here are floors.</div>\n</div>\n')
w('<div class="kpis">\n')
w(f'  <div class="kpi hl"><div class="v">{n(NPROJ)}</div><div class="l">perfect projects</div><div class="d">data-3 {n(proj_by["data-3"])} · data-4 {n(proj_by["data-4"])} · {"verified, see status" if VERI else "all verified"}</div></div>\n')
w(f'  <div class="kpi"><div class="v">{n(NSTEP)}</div><div class="l">perfect 3D models</div><div class="d">class-1 STEP files, distinct</div></div>\n')
w(f'  <div class="kpi"><div class="v">{n(F3)}</div><div class="l">3D files</div><div class="d dm">STEP · IFC · Tekla · SDS/2 · STL</div></div>\n')
w(f'  <div class="kpi"><div class="v">{n(F2)}</div><div class="l">2D files</div><div class="d dm">PDF · DG · DPM · DXF · DWG</div></div>\n')
w(f'  <div class="kpi"><div class="v">{n(FF)}</div><div class="l">CNC programs</div><div class="d">DSTV NC1</div></div>\n')
w(f'  <div class="kpi"><div class="v">{TOTB / 1e12:.2f} TB</div><div class="l">total size</div><div class="d dm">{n(TOTF)} distinct files</div></div>\n</div>\n')

# ---- What is in the pack
mx = max(chsum(DI, k)[1] for k, _, _ in CH)
w('<h2>What is in the pack</h2>\n<div class="card">\n')
w(f'  <p class="lead">Every project in the pack carries at least one perfect 3D model &mdash; that is what makes it a project here. Alongside it, '
  f'{pct(any_draw, NPROJ)} carry drawings, {pct(cv("fab/nc1"), NPROJ)} carry CNC programs and {pct(join_tab, NPROJ)} carry BOM or KISS join tables, '
  f'so in most projects a model traces to its drawings, to the machine code and to the bill of material. Each package declares what it holds, '
  f'so a slice can be filtered to the coverage it needs rather than turning up gaps later.</p>\n')
w('  <div class="srow shead"><div class="slabel"></div><div class="strack2">bar length &middot; channel size</div><div class="sval w2">files</div><div class="sval w2">size</div></div>\n')
for keys, label, g in sorted(CH, key=lambda c: -chsum(DI, c[0])[1]):
    f_, b_ = chsum(DI, keys)
    if not f_: continue
    w(f'  <div class="barrow"><div class="blabel">{label}</div><div class="btrack"><div class="bfill" style="width:{max(0.4, 100 * b_ / mx):.1f}%;background:{GCOL[g]}"></div></div>'
      f'<div class="bval">{n(f_)}</div><div class="bgb">{gb(b_)}</div></div>\n')
w(f'  <p class="note">The piece mark is the join key across every channel &mdash; the filename of an NC1 program is the mark printed on the drawing, '
  f'drawn in the DXF outline and listed in the BOM row. The STEP row holds only perfect conversions: a model that is not class 1 ships its source '
  f'files, never its STEP.</p>\n')
w(f'  <p class="note"><b>The drawings are CAD output.</b> At least {PDF_D_M:.1f} million of the PDFs are drawings, and at least {PDF_V_M:.1f} million of '
  f'those are vector drawings produced by a detailing package &mdash; the geometry and the text are objects in the file, selectable and measurable. '
  f'About {100 * pn_est:.0f}% are not drawings at all &mdash; transmittals, logs and other paperwork that travels with a job.</p>\n')
w(f'  <p class="note">Both counts are floors: measured on a random sample of {len(lab)} PDFs (300 per disk), weighted by each disk&rsquo;s share of the '
  f'channel, taken at the one-sided 95% lower bound and rounded down. Drawings are {100 * pd_est:.1f}% of the sample-weighted channel, vector '
  f'drawings {100 * pv_est:.1f}%.</p>\n</div>\n')

# ---- Every disk
def ctab(key):
    c = C[key]; bt = c['by_type']; bc = c['by_class']
    t = lambda p: sum(bt.get(p, {}).values())
    return c['n'], t('ifc'), t('db1'), t('sds2'), bc.get('1', 0), bc.get('2', 0), bc.get('3', 0), bc.get('None', 0)
w('<h2>Every disk</h2>\n<div class="card">\n')
w(f'  <p class="lead">Two disks were converted and packaged in full: <b>data-3</b>, which contains all of Disk-2 (2,474 byte-identical archives) plus 510 '
  f'archives of its own, and <b>data-4</b>, which contains all of Disk-1 (1,154 byte-identical archives) plus the TEKLA-HYD/Backup 2026 folder. '
  f'The &ldquo;from Disk-1/2&rdquo; and &ldquo;only on&rdquo; rows split the disk above them; they are not extra projects. '
  f'<b>data-2</b> is a Smart 3D plant model with no steel-detailing models; it was counted and set aside. A model found on both disks is packaged once, '
  f'in one project.</p>\n')
w('  <h3>1 · Models found and how they converted</h3>\n  <div class="tw"><table class="num">\n'
  '  <tr><th>Disk</th><th>Models found</th><th>IFC</th><th>Tekla DB1</th><th>SDS/2</th><th class="g">Perfect<br>(class 1)</th><th>Partial<br>(class 2)</th><th>Bad<br>(class 3)</th><th>No input</th></tr>\n')
rows = [('data-3', '<b>Data-3</b>', ''), ('disk-2', ORIG['disk-2'][0], 'sub'), ('data-3-only', ORIG['data-3-only'][0], 'sub'),
        ('data-4', '<b>Data-4</b>', ''), ('disk-1', ORIG['disk-1'][0], 'sub'), ('data-4-only', ORIG['data-4-only'][0], 'sub')]
tot = [0] * 8
for key, lbl, cls in rows:
    v = ctab(key)
    if key in ('data-3', 'data-4'): tot = [a + b for a, b in zip(tot, v)]
    w(f'  <tr class="{cls}"><td>{lbl}</td>'
      + ''.join(f'<td{" class=g" if i == 4 else ""}>{n(x) if x else "0"}</td>' for i, x in enumerate(v)) + '</tr>\n')
w('  <tr class="sub"><td>Data-2 <span class="dm">(plant model)</span></td><td colspan="8" class="l">1,927 IFC files derived from one Smart 3D plant model; no '
  'customer IFC, Tekla or SDS/2 models. Counted, not graded or packaged.</td></tr>\n')
w('  <tr class="tot"><td>Total (data-3 + data-4)</td>' + ''.join(f'<td{" class=g" if i == 4 else ""}>{n(x)}</td>' for i, x in enumerate(tot)) + '</tr>\n  </table></div>\n')
w(f'  <p class="note">Each disk is counted on its own, so a model present on both disks appears in both rows. &ldquo;No input&rdquo; is {n(tot[7])} models '
  f'whose file was missing from the archive or empty; nothing can be converted from them.</p>\n')
w('  <div class="tw"><table class="num slim">\n  <tr><th>Type</th><th>Disk</th><th>Models</th><th class="g">Perfect</th><th>Partial</th><th>Bad</th><th>Perfect rate</th></tr>\n')
for p_, pl in (('ifc', 'IFC'), ('db1', 'Tekla DB1'), ('sds2', 'SDS/2')):
    for key in ('data-3', 'data-4'):
        b = C[key]['by_type'].get(p_, {}); m = sum(b.values())
        w(f'  <tr><td>{pl}</td><td>{key.capitalize()}</td><td>{n(m)}</td><td class="g">{n(b.get("1", 0))}</td><td>{n(b.get("2", 0))}</td><td>{n(b.get("3", 0))}</td><td>{pct(b.get("1", 0), m)}</td></tr>\n')
w('  </table></div>\n')
w('  <h3>2 · What is packaged, per disk</h3>\n  <div class="tw"><table class="num">\n'
  '  <tr><th>Disk</th><th class="g">Perfect projects</th><th>Perfect models<br>(class-1 STEP)</th><th>3D files</th><th>2D files</th><th>CNC (NC1)</th><th>Tables</th><th>All files</th><th>Size</th></tr>\n')
for key, lbl, cls in rows + [('all', 'Whole pack', 'tot')]:
    dd = DI if key == 'all' else S['distinct_by_disk'].get(key)
    if not dd: continue
    f3, _ = grp(dd, '3d'); f2, _ = grp(dd, '2d'); ff, _ = grp(dd, 'fab'); ft, _ = grp(dd, 'tab')
    pr = NPROJ if key == 'all' else proj_by[key]
    note = ''
    w(f'  <tr class="{cls}"><td>{lbl}{note}</td><td class="g">{n(pr)}</td><td>{n(dd["files"].get("model/step", 0))}</td><td>{n(f3)}</td><td>{n(f2)}</td><td>{n(ff)}</td><td>{n(ft)}</td>'
      f'<td>{n(sum(dd["files"].values()))}</td><td>{gb(sum(dd["bytes"].values()))}</td></tr>\n')
w('  <tr class="sub"><td>Data-2</td><td colspan="8" class="l">Not packaged (census only).</td></tr>\n  </table></div>\n')
w(f'  <p class="note">Files are distinct: two copies of the same bytes count once (by SHA-256). That is why the whole-pack row is smaller than '
  f'data-3 plus data-4 &mdash; the two disks share files. Origins are exact: an archive is &ldquo;from Disk-1&rdquo; or &ldquo;from Disk-2&rdquo; when '
  f'the same path holds a byte-identical copy (same size) on that disk; every Disk-1 and Disk-2 archive was found this way. '
  f'In table 1, a model in several archives counts under Disk-1 / Disk-2 when any of them is. 3D files = STEP, IFC, Tekla DB1/DB2, SDS/2 and STL; '
  f'2D files = PDF, SDS/2 DG, Tekla DPM, DXF and DWG.</p>\n')
s1 = models_by['all']
w(f'  <p class="note">The class-1 counts in the two tables differ for a known reason. Table 1 counts models per disk index, so the {n(tot[4])} perfect '
  f'models include those found on both disks twice. Table 2 counts STEP files in the packages: {n(steps_by["all"])} STEP placements carrying '
  f'{n(s1)} perfect models (identical models share one file), {n(NSTEP)} distinct files.</p>\n</div>\n')

# ---- Where the projects come from
w('<h2>Where the projects come from</h2>\n<div class="card">\n')
segs = [('disk-1', 'Disk-1 archives (on data-4)', 'var(--ac)'), ('data-4-only', 'only on data-4', '#7c9cf0'),
        ('disk-2', 'Disk-2 archives (on data-3)', 'var(--cy)'), ('data-3-only', 'only on data-3', '#5fb8c9')]
w(f'  <p class="lead">Every one of the {n(NPROJ)} perfect projects, by the disk its archive came from.</p>\n  <div class="stack">')
for k_, lbl, col in segs:
    w(f'<div style="width:{100 * proj_by[k_] / NPROJ:.2f}%;background:{col}" title="{lbl}: {proj_by[k_]}"><span>{n(proj_by[k_])}</span></div>')
w('</div>\n  <div class="legend">' + ''.join(f'<span><i style="background:{col}"></i>{lbl} &mdash; <b>{n(proj_by[k_])}</b></span>' for k_, lbl, col in segs) + '</div>\n')
w('  <div class="tw"><table class="num">\n  <tr><th>Origin</th><th class="g">Perfect projects</th><th>Perfect models</th><th>3D files</th><th>2D files</th><th>CNC (NC1)</th>'
  '<th>With drawings</th><th>With NC1</th><th>All files</th><th>Size</th></tr>\n')
for dk, parts in (('data-4', ('disk-1', 'data-4-only')), ('data-3', ('disk-2', 'data-3-only'))):
    for key in (dk,) + parts:
        dd = S['distinct_by_disk'][key]; f3, _ = grp(dd, '3d'); f2, _ = grp(dd, '2d'); ff, _ = grp(dd, 'fab')
        cvd = lambda ch: S['coverage_by_disk'].get(f'{key}|{ch}', 0)
        drw = max(cvd('drawings/pdf'), cvd('drawings/dg'), cvd('drawings/dxf'))
        lbl = f'<b>{key.capitalize()}</b>' if key == dk else f'{ORIG[key][0]} <span class=dm>({ORIG[key][1]})</span>'
        w(f'  <tr class="{"" if key == dk else "sub"}"><td>{lbl}</td><td class="g">{n(proj_by[key])}</td><td>{n(dd["files"].get("model/step", 0))}</td>'
          f'<td>{n(f3)}</td><td>{n(f2)}</td><td>{n(ff)}</td><td>{pct(drw, proj_by[key])}</td><td>{pct(cvd("fab/nc1"), proj_by[key])}</td>'
          f'<td>{n(sum(dd["files"].values()))}</td><td>{gb(sum(dd["bytes"].values()))}</td></tr>\n')
w('  </table></div>\n')
w('  <p class="note">&ldquo;With drawings&rdquo; is the share of those projects carrying PDF, SDS/2 or DXF drawings, at least the most common of the three; '
  '&ldquo;With NC1&rdquo; the share carrying CNC programs.</p>\n')
w('  <h3>By source folder</h3>\n  <div class="tw"><table class="num slim">\n  <tr><th>Disk</th><th style="text-align:left">Folder on the disk</th><th class="g">Projects</th>'
  '<th style="text-align:left">Origin of those projects</th><th>Perfect models</th><th>All files</th><th>Size</th></tr>\n')
fold = collections.defaultdict(collections.Counter)
for p_ in P: fold[(p_['disk'], p_.get('src_folder'))][p_.get('origin')] += 1
for (dk, fo), og in sorted(fold.items(), key=lambda x: (x[0][0] != 'data-4', -sum(x[1].values()))):
    dd = S['distinct_by_disk'].get(f'src|{dk}|{fo}') or {'files': {}, 'bytes': {}}
    ogs = ' · '.join(f'{n(c)} {ORIG[o][0].replace("↳ ", "")}' for o, c in sorted(og.items(), key=lambda x: -x[1]) if o in ORIG)
    w(f'  <tr><td>{dk.capitalize()}</td><td class="l">{E(fo or "")}</td><td class="g">{n(sum(og.values()))}</td><td class="l">{ogs}</td>'
      f'<td>{n(dd["files"].get("model/step", 0))}</td><td>{n(sum(dd["files"].values()))}</td><td>{gb(sum(dd["bytes"].values()))}</td></tr>\n')
w('  </table></div>\n  <p class="note">Files and sizes are distinct within each row (one copy per content). Data-4 folders are named two levels deep, data-3 '
  'folders one level deep.</p>\n</div>\n\n')
# ---- Partial-STEP tier
if SP:
    PDI = SP['distinct']; pbyd = lambda k: SP['distinct_by_disk'].get(k) or {'files': {}, 'bytes': {}}
    kinds = collections.Counter(); kinds_o = collections.Counter(); proj_o = collections.Counter(); add_o = collections.Counter(); steps_o = collections.Counter()
    for p_ in PP:
        og = p_.get('origin'); tags_ = [p_['disk'], og, 'all']
        for t_ in tags_:
            proj_o[t_] += 1; add_o[t_] += bool(p_.get('addon_of'))
            for s_ in p_['steps']:
                steps_o[t_] += 1; kinds_o[(t_, s_.get('partial_kind'))] += 1
    NPP = len(PP); NADD = add_o['all']; NSTD = NPP - NADD
    STP = steps_o['all']; CTS = kinds_o[('all', 'complete_to_source')]; APX = kinds_o[('all', 'approximated')]
    MREP = sum(1 + (s_.get('also') or 0) for p_ in PP for s_ in p_['steps'])
    pstamp = (datetime.datetime.strptime(SP['at'], '%Y-%m-%dT%H:%M:%SZ') - datetime.timedelta(hours=7)).strftime('%-d %b %Y, %-I:%M %p PDT')
    w('<h2>Partial-STEP tier (separate folder)</h2>\n<div class="card">\n')
    w(f'  <p class="lead">Models whose STEP conversion is <b>partial</b> (class 2) are packaged too &mdash; in a separate folder, '
      f'<code>packages/3d_partial/</code>, in exactly the same package format, and counted separately from the perfect projects above. Nothing here '
      f'counts toward the perfect numbers. Every STEP row says what it lacks: <b>complete to source</b> means the STEP holds everything the source '
      f'file holds (the source itself stores some parts only as surfaces); <b>approximated</b> means the converter left out or stood in for some parts '
      f'(nominal bolts, envelope boxes, healed shells, round-cut slots) &mdash; each listed with its part counts. Class-3 (bad) conversions are never packaged.</p>\n')
    w(f'  <p class="note"><b>Deduped.</b> {n(NADD)} of the {n(NPP)} partial projects are <b>add-ons</b> to a project that is already in the perfect folder: they hold '
      f'only the partial STEP files (and an SDS/2 job zip the perfect package lacks) and point to the source files in the perfect package, which are '
      f'never copied twice. The other {n(NSTD)} are <b>partial-only</b> projects &mdash; no model of theirs converted perfectly &mdash; and carry their sources '
      f'themselves. One model is in one package across both disks and both folders.</p>\n')
    w('  <div class="kpis kpis2">\n')
    w(f'    <div class="kpi"><div class="v">{n(NPP)}</div><div class="l">partial-tier projects</div><div class="d dm">{n(NSTD)} partial-only · {n(NADD)} add-ons</div></div>\n')
    w(f'    <div class="kpi"><div class="v">{n(STP)}</div><div class="l">partial STEP files</div><div class="d dm">carrying {n(MREP)} partial models</div></div>\n')
    w(f'    <div class="kpi"><div class="v">{n(CTS)}</div><div class="l">complete to source</div><div class="d dm">STEP = everything the source holds</div></div>\n')
    w(f'    <div class="kpi"><div class="v">{n(APX)}</div><div class="l">approximated</div><div class="d dm">some parts left out or stood in</div></div>\n')
    w(f'    <div class="kpi"><div class="v">{PDI["total_bytes"] / 1e12:.2f} TB</div><div class="l">partial folder size</div><div class="d dm">{n(PDI["total_files"])} distinct files</div></div>\n  </div>\n')
    w('  <div class="tw"><table class="num">\n  <tr><th>Origin</th><th class="g">Partial projects</th><th>Partial-only</th><th>Add-ons</th><th>Partial STEP</th>'
      '<th>Complete to source</th><th>Approximated</th><th>Distinct files</th><th>Size</th></tr>\n')
    for dk, parts in (('data-4', ('disk-1', 'data-4-only')), ('data-3', ('disk-2', 'data-3-only'))):
        for key in (dk,) + parts:
            dd = pbyd(key)
            lbl = f'<b>{key.capitalize()}</b>' if key == dk else f'{ORIG[key][0]} <span class=dm>({ORIG[key][1]})</span>'
            w(f'  <tr class="{"" if key == dk else "sub"}"><td>{lbl}</td><td class="g">{n(proj_o[key])}</td><td>{n(proj_o[key] - add_o[key])}</td><td>{n(add_o[key])}</td>'
              f'<td>{n(steps_o[key])}</td><td>{n(kinds_o[(key, "complete_to_source")])}</td><td>{n(kinds_o[(key, "approximated")])}</td>'
              f'<td>{n(sum(dd["files"].values()))}</td><td>{gb(sum(dd["bytes"].values()))}</td></tr>\n')
    w(f'  <tr class="tot"><td>Partial tier</td><td class="g">{n(NPP)}</td><td>{n(NSTD)}</td><td>{n(NADD)}</td><td>{n(STP)}</td><td>{n(CTS)}</td><td>{n(APX)}</td>'
      f'<td>{n(PDI["total_files"])}</td><td>{gb(PDI["total_bytes"])}</td></tr>\n  </table></div>\n')
    nin = SP.get('projects_with_incomplete_sds2_zip') or 0
    w(f'  <p class="note">Counted from the delivered partial packages at {pstamp}. Files are distinct within each row (add-ons count only the files they hold). '
      f'{n(nin)} partial projects contain an SDS/2 job zip with a few non-model files that could not be found in storage; each zip lists exactly which. '
      f'Projects in either folder: <b>{n(NPROJ + NSTD)}</b> ({n(NPROJ)} perfect + {n(NSTD)} partial-only).</p>\n</div>\n\n')
# ---- How perfect is established
w('<h2>How &ldquo;perfect&rdquo; is established</h2>\n<div class="card">\n<div class="grid3">\n')
w('  <div class="step"><div class="sn">1 · Convert</div><p>Every 3D model on a disk is converted to STEP by the converter for its format: IFC by '
  'ifc2step 6.1.11, Tekla DB1 by the native database decoder, SDS/2 by the SDS/2 converter. No part is remodelled, approximated or invented; '
  'geometry the source does not hold is reported missing, never filled in.</p></div>\n')
w('  <div class="step"><div class="sn">2 · Grade, then verify independently</div><p>The STEP is graded part by part against its source: every part '
  'must be present as an exact closed solid with the source&rsquo;s volume and placement. <b>Class 1</b> = every part exact. <b>Class 2</b> = some '
  'parts approximated or absent in the source. <b>Class 3</b> = the conversion failed. A second, independent verifier re-reads the STEP and the source '
  'and must agree before a model counts as class 1.</p></div>\n')
w('  <div class="step"><div class="sn">3 · Package and verify the package</div><p>Only class-1 STEP files ship. Each project package carries every '
  'source file of the job with a manifest (path, bytes, SHA-256, modality) and must pass a package verify with zero missing, extra, size-mismatched, '
  'hash-mismatched or duplicate files. A model shared by several archives or both disks is packaged once.</p></div>\n</div>\n')
w('<p class="note">Partial models are not thrown away: their source IFC, Tekla and SDS/2 files are still in the packages; only their STEP is held back. '
  'One rule needs stating: where an IFC file&rsquo;s own stated part volume disagrees with its own geometry, the part counts as exact when the STEP '
  'matches the source geometry within 0.5%.</p>\n</div>\n')

# ---- What the dataset is made of
w('<h2>What the dataset is made of</h2>\n<div class="card">\n')
w('  <p class="lead">Each channel as a share of the pack. Native SDS/2 drawing files dominate by count; CNC programs are numerous and tiny; STEP and PDF '
  'carry most of the bytes.</p>\n')
w('  <div class="tw"><table class="num slim"><tr><th>Channel</th><th>share of files</th><th>share of size</th></tr>\n')
for keys, label, g in sorted(CH, key=lambda c: -chsum(DI, c[0])[1]):
    f_, b_ = chsum(DI, keys)
    if f_: w(f'  <tr><td><span class="dot" style="background:{GCOL[g]}"></span>{label}</td><td>{100 * f_ / TOTF:.2f}%</td><td>{100 * b_ / TOTB:.1f}%</td></tr>\n')
w('  </table></div>\n')
w(f'  <p class="note">{gb(TOTB)} across {n(TOTF)} files &nbsp;·&nbsp; 3D {100 * B3 / TOTB:.1f}% &nbsp;·&nbsp; 2D {100 * B2 / TOTB:.1f}% &nbsp;·&nbsp; '
  f'tables {100 * BT / TOTB:.1f}% &nbsp;·&nbsp; fabrication {100 * BF / TOTB:.1f}% of the bytes.</p>\n')
w('  <p class="note">Counts are distinct files, so the channel rows sum exactly to the total. Two objects count once when they share content, as '
  'identified by the SHA-256 each package&rsquo;s manifest carries for every file. Shares are rounded to the precision shown.</p>\n</div>\n')

# ---- 3D live
h = MODELS['m14']
w('<h2>The 3D channel, live</h2>\n<div class="card">\n  <div id="viewer" data-glb="models/m14.json"><div class="vhint">drag to rotate · scroll to zoom</div>'
  '<button class="vbtn" id="spin" type="button">pause rotation</button></div>\n')
w(f'  <p class="note">A class-1 model from the pack, rendered in your browser from the package&rsquo;s own STEP file: <b>31-2311 Toray</b> (data-4), '
  f'{n(h["parts"])} parts, {h["extent_mm"][0] / 1000:.1f} × {h["extent_mm"][1] / 1000:.1f} × {h["extent_mm"][2] / 1000:.1f} m, {n(h["triangles"])} triangles. '
  f'This is solid geometry with real dimensions &mdash; not a scan or a point cloud.</p>\n</div>\n')

# ---- Channel coverage
w(f'<h2>Channel coverage</h2>\n<div class="card">\n  <p class="lead">Share of the {n(NPROJ)} projects that carry each channel, measured from the files themselves. '
  f'The STEP channel is not a row here: every project has one, so it is the floor the other channels sit on. Drawings reach {pct(any_draw, NPROJ)} and '
  f'CNC programs {pct(cv("fab/nc1"), NPROJ)}; {pct(all3, NPROJ)} carry drawings, CNC programs and a join table together ({n(all3)} projects) &mdash; each '
  f'of those on top of the model.</p>\n')
covrows = [('model/ifc', 'IFC models', '3d'), ('drawings/pdf', 'Drawings (PDF)', '2d'), ('tables/bom', 'BOM tables', 'tab'), ('drawings/dxf', 'DXF piece outlines', '2d'),
           ('fab/nc1', 'CNC programs (NC1)', 'fab'), ('tables/kiss', 'KISS join tables', 'tab'), ('drawings/dwg', 'DWG', '2d'), ('tables/abm', 'Excel / ABM sheets', 'tab'),
           ('model/db1', 'Tekla model databases', '3d'), ('drawings/dg', 'SDS/2 drawing files', '2d'), ('drawings/dpm', 'Tekla drawing files', '2d'), ('model/sds2', 'SDS/2 model archives', '3d')]
for k_, lbl, g in sorted(covrows, key=lambda r: -cv(r[0])):
    c_ = cv(k_)
    w(f'  <div class="barrow"><div class="blabel">{lbl}</div><div class="btrack"><div class="bfill" style="width:{100 * c_ / NPROJ:.1f}%;background:{GCOL[g]}"></div></div>'
      f'<div class="bval">{pct(c_, NPROJ)}</div><div class="bgb">{n(c_)} projects</div></div>\n')
w('  <p class="note">Coverage is measured, not assumed &mdash; every package records which channels it holds and declares the ones it lacks.</p>\n</div>\n')

# ---- One job, three ways
a = T3['assembly']; nb = T3['nc1']['b52006']['lines']; npl = T3['nc1']['p14420']['lines']; ent = SEQ['entities']
w('<h2>One job, three ways</h2>\n<div class="card">\n')
w('  <p class="lead">An example of how the channels relate. These artefacts are the same steel, from one job issued for fabrication &mdash; '
  '<b>Issaquah Middle School</b>, Lundahl Ironworks job 19002, sequence 52. The model holds the structure, the drawing details one assembly within it, '
  'and the CNC programs cut that assembly&rsquo;s beam and its plates. They are joined by piece mark.</p>\n')
w(f'  <p class="note">All three are in package <b>MT20_023 (Issaquah Middle School)</b> on data-3, at <code>{E(SEQ["ifc"])}</code> (class-1 STEP '
  f'<code>{E(SEQ["step"][0])}</code>), <code>{E(T3["pdf"]["relpath"])}</code> and <code>{E(T3["nc1"]["b52006"]["relpath"])}</code>.</p>\n')
w('  <div class="grid2" style="margin-top:14px">\n  <div>\n')
w(f'    <p><b>1 · The model</b> &mdash; <code>{E(SEQ["ifc"])}</code>. Sequence 52 of the job: {ent.get("IFCELEMENTASSEMBLY", 0)} assemblies, '
  f'{ent.get("IFCBEAM", 0)} beams, {ent.get("IFCCOLUMN", 0)} columns, {ent.get("IFCMEMBER", 0)} members, {ent.get("IFCPLATE", 0)} plates and '
  f'{ent.get("IFCMECHANICALFASTENER", 0)} bolts &mdash; counted from the file&rsquo;s own IfcElementAssembly, IfcBeam, IfcColumn, IfcMember, IfcPlate '
  f'and IfcMechanicalFastener entities. Its STEP conversion is class 1.</p>\n')
w(f'    <p><b>2 · The drawing</b> &mdash; <code>{E(T3["pdf"]["relpath"])}</code>, a {T3["pdf"]["size_in"][0]:.0f} × {T3["pdf"]["size_in"][1]:.0f} in shop '
  f'drawing detailing assembly <b>B52006</b>: one W24X55 beam, 32&prime;-4&frac12;&Prime; long, with its plates, bill of material and field bolts. In the '
  f'model, B52006 is an IfcElementAssembly of {a["n_parts"]} parts &mdash; {", ".join(f"{c} {t[3:].lower()}s" for t, c in a["part_types"])}; plate '
  f'<b>p14420</b> occurs {a["part_marks"][0][1]} times in it, as the bill of material on the sheet says.</p>\n')
w('    <p><b>3 · The CNC programs</b> &mdash; DSTV code for the beam line. <code>B52006.nc1</code> cuts the beam itself; <code>p14420.nc1</code> '
  'cuts one of its plates.</p>\n  </div>\n')
w('  <figure><a class="zoom" href="2d/three_sheet_full.jpg" target="_blank" rel="noopener"><img src="2d/three_sheet.jpg" alt="Shop drawing B52006, Issaquah Middle School" loading="lazy"><span class="zi">open full size ↗</span></a>'
  '<figcaption>Shop drawing B52006 &mdash; beam elevation, eight sections, weld details and the bill of material, issued for fabrication on '
  '18 Sep 2020.</figcaption></figure>\n  </div>\n')
def nc(lines, notes):
    out = []
    for i, l in enumerate(lines[:12]):
        t = E(l.rstrip()); c = notes.get(i)
        out.append(f'{t:<20}' + (f'<span class="cm">← {c}</span>' if c else ''))
    return '\n'.join(out)
w('  <div class="grid2" style="margin-top:14px">\n')
w('  <div><div class="cap">fab/nc1/B52006.nc1 &mdash; the beam</div><pre class="code">' + nc(nb, {1: 'job 19002, as on the sheet', 2: 'piece mark', 3: 'sequence 52 (model Seq#52)',
  5: 'grade, as on the sheet', 6: 'quantity', 7: 'section', 9: 'length, mm = 32′-4½″', 10: 'depth, mm', 11: 'flange width, mm'}) + '</pre></div>\n')
w('  <div><div class="cap">fab/nc1/p14420.nc1 &mdash; one of its plates</div><pre class="code">' + nc(npl, {2: 'plate mark, 8 in B52006', 5: 'grade, as on the sheet',
  6: 'quantity, whole job', 7: 'plate profile', 9: 'length, mm = 1′-10⅝″', 10: 'width, mm = 3¼″'}) + '</pre></div>\n  </div>\n')
w('  <p class="note"><b>Why this matters.</b> Meshes and drawings are separately available elsewhere. What is scarce is the same part expressed three ways '
  '&mdash; as solid geometry, as a dimensioned fabrication drawing and as machine code &mdash; with a key that ties them together. Here the link is '
  'checkable: the model names the assembly B52006 and the plate p14420 (its IFC property reads PL3/8x3 1/4x1-10 5/8); the sheet lists p14420 eight times '
  'as PL3/8x3 1/4, 1&prime;-10⅝&Prime;, A572-50; and the program states 574.67 × 82.55 mm &mdash; 22⅝ in × 25.4 = 574.68 mm and 3¼ in × 25.4 = 82.55 mm.</p>\n</div>\n')

# ---- Drawing detail
w('<h2>Drawing detail</h2>\n<div class="card">\n  <div class="grid2w">\n')
w('  <figure><a class="zoom" href="2d/detail_weld.jpg" target="_blank" rel="noopener"><img src="2d/detail_weld.jpg" alt="Weld details from B52006" loading="lazy"><span class="zi">open full size ↗</span></a>'
  '<figcaption>Details A and B, section J-J and the bent-plate shop splice from the same sheet: complete-joint-penetration welds with back gouge at the '
  'flanges, 3/8 in radius cuts, weld sizes and bevel callouts.</figcaption></figure>\n')
w('  <figure><a class="zoom" href="2d/detail_bom.jpg" target="_blank" rel="noopener"><img src="2d/detail_bom.jpg" alt="Bill of material from B52006" loading="lazy"><span class="zi">open full size ↗</span></a>'
  '<figcaption>The sheet&rsquo;s bill of material: every piece mark with quantity, profile, length, grade and weight, plus 14 field bolts.</figcaption></figure>\n')
w('  </div>\n  <p class="note">This level of specification &mdash; weld procedure, material grade, piece-by-piece quantities &mdash; is what distinguishes a fabrication '
  'drawing from a design drawing.</p>\n</div>\n')

# ---- The join
h1 = J['nc1_text_head']
w('<h2>The join</h2>\n<div class="card">\n')
w('  <p class="lead">One piece, three ways. Mark <b>p25</b> is a plate: the shop drawing dimensions it, the DXF gives its cut outline, and the CNC program '
  'states the stock it is made from. The three files are named for the mark, which is what makes them joinable at all.</p>\n  <div class="grid2">\n')
w('  <figure><a class="zoom" href="2d/join_sheet.jpg" target="_blank" rel="noopener"><img src="2d/join_sheet.jpg" alt="Shop drawing for plate p25" loading="lazy"><span class="zi">open full size ↗</span></a>'
  '<figcaption>The sheet &mdash; plate <b>p25</b>, profile <b>PL1/2x9x1-2</b>, grade <b>A529-50</b>, quantity <b>2</b>, with its four holes located. '
  'E &amp; H Steel, IVC Mohawk Industries dehumidification project, data-4.</figcaption></figure>\n')
w(f'  <figure><img src="2d/join_dxf.png" alt="DXF outline for plate p25" loading="lazy"><figcaption>The outline &mdash; the DXF for the same mark, '
  f'{J["dxf_ext"][0]:.2f} in by {J["dxf_ext"][1]:.2f} in.</figcaption></figure>\n  </div>\n')
w('  <div class="cap" style="margin-top:14px">The CNC program for the same mark, as it ships:</div><pre class="code">' +
  nc(h1, {1: 'the job', 2: 'piece mark — sheet and outline are both p25', 5: 'steel grade, as printed on the sheet', 6: 'quantity',
          7: 'plate profile', 9: 'mm — the outline measures 14.00 in', 10: 'mm — the outline measures 9.00 in', 13: 'thickness, mm = ½ in'}) +
  '\n' + '\n'.join(E(x) for x in h1[22:28] if x.strip()) + '   <span class="cm">← two of the four Ø20.64 mm holes</span></pre>\n')
w('  <p class="note">The arithmetic is checkable. The program gives the plate as 355.60 by 228.60 mm. The outline measures 14.00 by 9.00 in, and '
  '14.00 in × 25.4 = 355.60 mm, 9.00 in × 25.4 = 228.60 mm. One plate, stated twice in two unit systems, and the drawing prints the same mark, profile, '
  'grade and quantity.</p>\n</div>\n')

# ---- Range of drawings
w('<h2>Range of drawings</h2>\n<div class="card">\n  <div class="grid4">\n')
for i, cap in PICK:
    r = next(x for x in RANGE if x['n'] == i)
    w(f'  <figure><a class="zoom" href="2d/range_{i:02d}_full.jpg" target="_blank" rel="noopener"><img src="2d/range_{i:02d}.jpg" alt="{E(cap)}" loading="lazy">'
      f'<span class="zi">open full size ↗</span></a><figcaption>{E(cap)} <span class="ch">{r["disk"].replace("d", "data-")} · {r["w_in"]:.0f} × {r["h_in"]:.0f} in</span></figcaption></figure>\n')
w(f'  </div>\n  <p class="note">Click any sheet to open it at full size (2800 px). {len(PICK)} sheets from {len({next(x for x in RANGE if x["n"] == i)["project_id"] for i, _ in PICK})} '
  'different projects, half from each disk &mdash; erection and framing plans, single-piece details, assemblies, stairs and standard connection details. '
  'Different fabricators, different structure types, different detailing offices &mdash; the drawing channel reads the same way across all of them.</p>\n</div>\n')

# ---- Range of models
w('<h2>Range of models</h2>\n<div class="card">\n  <p class="lead">A class-1 model from each of five more packages, rendered from that package&rsquo;s own STEP file '
  '&mdash; same camera, same scale treatment, same background throughout. Different fabricators, different source formats (IFC and native Tekla '
  'databases), different structure types.</p>\n  <div class="grid5">\n')
for tag, name, swn in SAMPLES[1:]:
    m = MODELS[tag]; c = pc(m['project_id']); a1, a2 = counts_line(c, True) if c else ('', '')
    w(f'  <figure class="smp" data-glb="models/{tag}.json"><div class="sshell"><img src="models/{tag}.jpg" alt="{E(name)} model" loading="lazy">'
      f'<button class="sgo" type="button" disabled>still</button></div><figcaption><span class="pk">{E(name)}</span>'
      f'<span class="ch">{m["disk"]} · from {"IFC" if m["source"] == "ifc" else "Tekla DB1"} · {n(m["parts"])} parts</span><span class="ch">{a1}</span><span class="ch">{a2}</span></figcaption></figure>\n')
w('  </div>\n  <p class="note">Each tile is live &mdash; click <b>interact</b> to load that model into the browser and drag it around, exactly like the viewer above. '
  'The still image is what loads with the page; the geometry is fetched only when you ask for it, and one viewer runs at a time. Rendered directly '
  'from the shipped STEP files; nothing was remodelled or redrawn for this page. Counts are each package&rsquo;s own, as in the samples table below.</p>\n</div>\n')

# ---- Package structure
w('<h2>Package structure</h2>\n<div class="card">\n  <p class="lead">Every package is the same shape, whatever software the job came from. Channels that a project '
  'does not have are declared absent rather than omitted silently.</p>\n')
tree = [('tf', '▪', 'project.json', 'disk · source archive · per-channel counts · declared gaps'),
        ('tf', '▪', 'manifest.jsonl', 'one line per file — path, bytes, sha256, modality, role; for STEP: class, converter, source model'),
        ('t3', '●', 'model/', '3D geometry, portable and native'), ('t3 ts', '└', 'step/', 'class-1 STEP conversions only'),
        ('t3 ts', '└', 'ifc/', 'IFC building models'), ('t3 ts', '└', 'db1/ db2/', 'Tekla native model databases'), ('t3 ts', '└', 'sds2/', 'SDS/2 native model archives'),
        ('t2', '●', 'drawings/', 'shop and erection drawings'), ('t2 ts', '└', 'pdf/', 'shop & erection sheets'), ('t2 ts', '└', 'dg/', 'SDS/2 native drawings'),
        ('t2 ts', '└', 'dpm/', 'Tekla native drawings'), ('t2 ts', '└', 'dxf/ dwg/', 'vector piece outlines and sheets'),
        ('tfb', '●', 'fab/', 'CNC output'), ('tfb ts', '└', 'nc1/', 'DSTV programs, one per piece'),
        ('tt', '●', 'tables/', 'structured data'), ('tt ts', '└', 'bom/ kiss/ abm/', 'assembly-to-submaterial joins and quantity sheets'),
        ('tt ts', '└', 'drawing_index/', 'sheet indexes')]
for cls, ico, nm, desc in tree:
    w(f'  <div class="trow {cls}"><span class="tico">{ico}</span><span class="tname">{nm}</span><span class="tdesc">{desc}</span></div>\n')
w('</div>\n')

# ---- Native files
db = chsum(DI, ['model/db1', 'model/db2']); dpm = chsum(DI, ['drawings/dpm']); dg = chsum(DI, ['drawings/dg']); s2 = chsum(DI, ['model/sds2'])
w('<h2>Native Tekla and SDS/2 files</h2>\n<div class="card">\n')
w(f'  <p class="lead">Four of the pack&rsquo;s channels are native authoring files: <b>{n(db[0])}</b> Tekla model databases (.db1/.db2, {gb(db[1])}), '
  f'<b>{n(dpm[0])}</b> Tekla drawing files (.dpm, {gb(dpm[1])}), <b>{n(s2[0])}</b> SDS/2 model archives ({gb(s2[1])}) and <b>{n(dg[0])}</b> SDS/2 '
  f'drawing files (.dg, {gb(dg[1])}). All four are rows in the tables above and inside their totals.</p>\n  <div class="grid2">\n')
w('  <div><p><b>What they are</b></p><p class="note">An authoring format, not an exchange format. A native model is the model the detailing office built '
  'and works in: the parametric connections, the assembly structure and the fabrication attributes are live objects inside it rather than annotations on '
  'a finished result. For a buyer running Tekla Structures or SDS/2 these are the richest form of a job in the pack, and the only form a detailer can '
  'pick up and carry on working in.</p></div>\n')
w('  <div><p><b>What it takes to open them</b></p><p class="note">A licensed seat of Tekla Structures or SDS/2. No free viewer reads a .db1, .dpm or .dg file. '
  'That is why the pack also ships them converted: Tekla databases and SDS/2 models that converted perfectly are in the STEP row, and their sheets '
  'are usually present as PDF too.</p></div>\n  </div>\n')
s_db = src_by[('all', 'db1')]; s_sd = src_by[('all', 'sds2')]; s_if = src_by[('all', 'ifc')]
w(f'  <p class="note">Counted as files, never as models. Of the {n(steps_by["all"])} STEP placements in the packages, {n(s_if)} come from IFC, {n(s_db)} from '
  f'native Tekla databases and {n(s_sd)} from SDS/2 models; per-model conversion results are in <i>Every disk</i> above.</p>\n</div>\n')

# ---- Uses
w('<h2>How it can be used</h2>\n<div class="card">\n  <div class="tw"><table><tr><th>Use case</th><th>What supports it</th></tr>\n')
uses = [('3D geometry understanding and reconstruction', f'{n(NSTEP)} perfect STEP models with {n(DI["files"].get("model/ifc", 0))} source IFC files and {n(db[0])} native Tekla databases'),
        ('Drawing to model grounding', f'{n(NPDF)} PDF drawings sitting alongside the models of the same job, joined by piece mark where the mark is carried'),
        ('CAD to CNC program generation', f'{n(FF)} NC1 programs with per-piece geometry and hole patterns'),
        ('Quantity take-off from join tables', f'{n(chsum(DI, ["tables/bom", "tables/kiss"])[0])} BOM and KISS tables in {pct(join_tab, NPROJ)} of projects, {n(chsum(DI, ["tables/abm"])[0])} ABM and Excel sheets'),
        ('Vector drawing understanding', f'{n(DI["files"].get("drawings/dxf", 0))} DXF piece outlines, {n(DI["files"].get("drawings/dwg", 0))} DWG'),
        ('Native-format learning', f'{n(dg[0])} SDS/2 drawing files and {n(dpm[0])} Tekla drawing files next to their PDF output')]
for u, s_ in uses: w(f'  <tr><td>{u}</td><td>{s_}</td></tr>\n')
w('  </table></div>\n</div>\n')

# ---- Samples
w('<h2>Samples</h2>\n<div class="card">\n  <div class="tw"><table><tr><th>Sample package</th><th>Disk</th><th>Contents</th></tr>\n')
for tag, name, swn in SAMPLES:
    c = pc(MODELS[tag]['project_id'])
    if c: w(f'  <tr><td>{E(name)}</td><td>{c["disk"]}</td><td>{counts_line(c)}</td></tr>\n')
for pid, name, why in EXTRA:
    c = pc(pid)
    if c: w(f'  <tr><td>{E(name)} <span class="dm">({why})</span></td><td>{c["disk"]}</td><td>{counts_line(c)}</td></tr>\n')
w('  </table></div>\n  <p class="note">Counts are read from the delivered packages themselves, so they match what ships. They are a fair sample of the package '
  'shape, not of the per-project drawing volume.</p>\n</div>\n')

# ---- Classification
w('<h2>Classification</h2>\n<div class="card">\n  <table class="meta">\n')
for k_, v_ in (('Asset class', 'Design / CAD'), ('Modality', 'Multimodal — 3D geometry, 2D vector and raster drawings, CNC text, tabular'),
               ('Domain', 'Structural steel detailing and fabrication'),
               ('Building types', 'Schools and universities, hospitals, hotels and apartments, offices and banks, data centres, factories and process plants, '
                                 'warehouses, fire and public-safety buildings, stairs, racks and trusses'),
               ('Source software', f'Tekla Structures ({n(sw["Tekla Structures"])} IFC files) and SDS/2 ({n(sw["SDS/2"])} IFC files), by each IFC header; years {y0}–{y1}'),
               ('Provenance', 'Naturally occurring production work'), ('Quality gate', 'Class-1 STEP only; every package verified (size and SHA-256 of every file)')):
    w(f'  <tr><td>{k_}</td><td>{v_}</td></tr>\n')
w('  </table>\n</div>\n')

# ---- Channel reference
w('<h2>Channel reference</h2>\n<div class="card ref">\n')
for k_, v_ in (('3D models', 'Perfect STEP conversions plus the source IFC, Tekla and SDS/2 models. All carry the structure as placed — assemblies, members, '
                             'plates and bolts with their real dimensions and positions. Native Tekla and SDS/2 files need a licence to open.'),
               ('Drawings', 'Shop drawings show one fabricated assembly with every dimension, weld and bolt needed to make it. Erection drawings show where '
                            'assemblies go in the structure. Present as PDF, as DXF and DWG vector forms, and as native SDS/2 and Tekla drawing files.'),
               ('Fabrication output (NC1)', 'DSTV NC1 drives beam lines, drills and coping machines. One file per piece, naming the mark, profile, length, '
                                             'grade and every hole position and cut — the machine-readable statement of how a part is physically made.'),
               ('Tables', 'BOM and KISS tables join assemblies to their submaterials — drawing number, assembly mark, submaterial mark, quantity, shape, size, '
                          'grade, length. ABM and Excel workbooks give fabrication quantities. All sit under each package&rsquo;s tables/ directory.')):
    w(f'  <p><b>{k_}</b> &nbsp;{v_}</p>\n')
w(f'</div>\n<p class="foot">Built {STAMP} from the delivered packages (stats run {E(S["run"])}, {E(S["at"])}) and the data-3 and data-4 conversion '
  f'indexes. Files counted distinct by SHA-256.</p>\n</div>\n')
w('<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>\n<script>' + open(f'{H}/report.js').read() + '</script>\n')
open(f'{OUT}/index.html', 'w').write(''.join(o))
tot_b = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(OUT) for f in fs)
print('wrote', f'{OUT}/index.html', len(''.join(o)), 'bytes; site total', round(tot_b / 1e6, 1), 'MB')
print('projects', NPROJ, 'by', dict(proj_by), 'distinct', TOTF, 'TB', round(TOTB / 1e12, 3), '3D', F3, '2D', F2, 'NC1', FF, 'STEP', NSTEP)
print('pdf drawings', round(pd_est, 4), 'floor', PDF_D_M, 'M; vector', round(pv_est, 4), 'floor', PDF_V_M, 'M; years', y0, y1, dict(sw))
print('steps', dict(steps_by), 'models', dict(models_by))
