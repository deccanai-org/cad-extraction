#!/usr/bin/env python3
"""make_issues.py - the issue maker of the partial-tier pipeline (runs on Modal after the pipeline's verify step).

From what is RECORDED about one converted model it writes:
  <out-sched>/issues.json         every flagged part: id, name, colour, every flag (category, reason, evidence), label,
                                  where it is; counts per colour for both modes of build_issues_model.py; the partial
                                  record reconciled against our counts; the checks made / not made and why
  <out-sched>/missing_parts.json  the parts the conversion DROPPED, each with the geometry its SOURCE records (an IFC
                                  product of our schedules, a DB1 record's outline + thickness, an axis + diameter, a
                                  section named in the source along its recorded axis) or a labelled marker where the
                                  source records a position but no size; never invented geometry
  <out-issues>/WHERE_TO_LOOK.md   plain language for a non-CAD reviewer: per colour what / where (landmarks + mm
                                  coordinates) / why, counts, legend

usage:
  make_issues.py --job JOB.json --sched PIPE_OUT_DIR --delivered DELIVERED.step --out-sched DIR --out-issues DIR
                 [--conv DIR] [--db1-facts skipped_records.json] [--sds2-facts sds2_facts.json] [--model-name NAME]

  JOB.json       the job row: model_id, pid, relpath, step_source (ifc|db1|sds2), converter, partial {kind, issues,
                 missing, standins}, grader, verify_codes, model_folder (the manifest row of the package works too)
  PIPE_OUT_DIR   the pipeline's output folder: schedules (parts.csv ...) + verification.csv (+ verification_summary.json)
  --conv DIR     conversion detail files, any of: <id>*.parts.json, <id>*.check.json, <id>.json (conversion result),
                 <id>*.step_parts.jsonl.gz, <id>*.src_parts.jsonl.gz, decoded_parts.json.gz (DB1);
                 SDS/2: <step stem>_pieces.csv, <step stem>_skipped.csv, <step stem>.log (siblings of the shipped STEP),
                 <id>.stage2_pieces.csv / .stage2_skipped.csv (fleet detail)
  --db1-facts    src_db1's skipped_records.json (pmp.src_db1.skipped_records/1)
  --sds2-facts   src_sds2's facts JSON (instances, skipped pieces with recorded geometry, holes ...); optional

Deterministic (sorted output, no wall times). Pure Python + issues_lib (no CAD kernel needed).
"""
import argparse
import collections
import csv
import fnmatch
import glob
import gzip
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import issues_lib as lib  # noqa: E402

MAKER_VERSION = 'make_issues 1.1'
IN = 25.4


# ======================================================================================== small helpers
def fmt_mm(v):
    return f'{v:,.0f}'


def fmt_pt(p):
    return '(' + ' / '.join(fmt_mm(x) for x in p) + ')'


def parse_xyz(s):
    if s is None or s == '':
        return None
    try:
        v = [float(x) for x in str(s).split()]
        return v if len(v) == 3 else None
    except ValueError:
        return None


def fnum(x, default=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def bbox_union(boxes):
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return [min(b[i] for b in boxes) for i in range(3)] + [max(b[i + 3] for b in boxes) for i in range(3)]


def centre(b):
    return [(b[i] + b[i + 3]) / 2 for i in range(3)]


def read_csv(path):
    if not path or not os.path.exists(path) or os.path.getsize(path) == 0:
        return []
    with open(path, newline='', encoding='utf-8', errors='replace') as f:
        return list(csv.DictReader(f))


def jsonl(path):
    if not path or not os.path.exists(path):
        return []
    op = gzip.open if path.endswith('.gz') else open
    with op(path, 'rt', encoding='utf-8') as f:
        return [json.loads(l) for l in f if l.strip()]


def frac_in(x):
    """inches as a fraction string (1/16 resolution)"""
    for den in (16, 8, 4, 2, 1):
        n = round(x * den)
        if abs(n / den - x) < 1e-4:
            w, n2 = divmod(n, den)
            g = math.gcd(n2, den) if n2 else den
            return ((f'{w} ' if w else '') + (f'{n2 // g}/{den // g}' if n2 else '')).strip() or '0'
    return f'{x:.3f}'


def parse_inch_number(s):
    """'1 1/2' -> 1.5, '35 13/16' -> 35.8125, '3/4' -> 0.75, '6' -> 6.0"""
    s = s.strip()
    m = re.fullmatch(r'(\d+(?:\.\d+)?)?\s*(?:(\d+)/(\d+))?', s)
    if not m or (m.group(1) is None and m.group(2) is None):
        return None
    v = float(m.group(1) or 0)
    if m.group(2):
        v += float(m.group(2)) / float(m.group(3))
    return v


# ======================================================================================== flags
class Flags:
    def __init__(self):
        self.f = collections.defaultdict(list)          # part id -> [flag]
        self.checks = []

    def add(self, pid, colour, category, reason, evidence=None):
        """one flag per (part, category): a second rule naming the same category adds its reason / evidence to it"""
        if not pid:
            return
        for x in self.f[pid]:
            if x['category'] == category:
                if reason != x['reason'] and reason not in x.get('also', []):
                    x.setdefault('also', []).append(reason)
                if evidence and evidence != x['evidence']:
                    x.setdefault('more_evidence', []).append(evidence)
                if lib.PRECEDENCE.index(colour) < lib.PRECEDENCE.index(x['colour']):
                    x['colour'] = colour
                return
        self.f[pid].append(dict(colour=colour, category=category, reason=reason, evidence=evidence or {}))

    def check(self, name, status, n=None, why=None, source=None):
        self.checks.append(dict(check=name, status=status, flagged=n, why=why, source=source))


# ======================================================================================== context
class Ctx:
    def __init__(self, a):
        self.a = a
        job = json.load(open(a.job, encoding='utf-8'))
        self.job = job
        self.model_id = job.get('model_id')
        self.source = job.get('step_source')
        self.relpath = job.get('relpath') or job.get('step')
        self.partial = job.get('partial') or {}
        self.name = a.model_name or job.get('model_folder') or re.sub(r'[^A-Za-z0-9._-]+', '_',
                                                                         os.path.splitext(os.path.basename(self.relpath))[0])
        self.title = os.path.splitext(os.path.basename(self.relpath))[0]
        S = a.sched
        self.sched_parts = read_csv(os.path.join(S, 'parts.csv'))
        self.sp = {p['part_id']: p for p in self.sched_parts}
        vpath = os.path.join(S, 'verification.csv')
        if not os.path.exists(vpath) and os.path.exists(os.path.join(S, 'verification', 'verification.csv')):
            vpath = os.path.join(S, 'verification', 'verification.csv')
        self.ver_rows = read_csv(vpath)
        self.ver = {r['part_id']: r for r in self.ver_rows}
        self.ver_summary = lib.load_json(os.path.join(os.path.dirname(vpath), 'verification_summary.json'), {}) or {}
        # delivered STEP (text only)
        self.sf = lib.StepFile(a.delivered)
        self.scheme = 'sds2label' if self.source == 'sds2' else 'product_id'
        self.dparts = self.sf.part_ids(self.scheme)                  # [(part dict, id)]
        self.d_ids = collections.Counter(pid for _, pid in self.dparts)
        self.d_label = {}
        for p, pid in self.dparts:
            self.d_label.setdefault(pid, p['label'])
        m = re.search(rb"FILE_NAME\s*\(\s*'(?:[^']|'')*'\s*,\s*'([^']*)'", self.sf.header)
        ts = m.group(1).decode('latin-1') if m else ''
        self.step_time = ts if re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d.*', ts) else lib.FIXED_TIME
        # conversion detail
        self.conv = sorted(glob.glob(os.path.join(a.conv, '*'))) if a.conv and os.path.isdir(a.conv) else []
        self.parts_json = self._pick(['*.parts.json'], json_load=True)
        self.check_json = self._pick(['*.check.json'], json_load=True)
        self.result_json = None
        for p in self.conv:
            if p.endswith('.json') and not p.endswith(('.parts.json', '.check.json', '.census.json')):
                d = lib.load_json(p)
                if isinstance(d, dict) and ('join' in d or 'decoded' in d or 'convert' in d):
                    self.result_json = d
                    break
        self.step_parts = jsonl(self._first(['*step_parts.jsonl.gz', '*step_parts.jsonl']))
        self.src_parts = jsonl(self._first(['*src_parts.jsonl.gz', '*src_parts.jsonl']))
        self.db1 = lib.load_json(a.db1_facts) if a.db1_facts else None
        self.sds2 = lib.load_json(a.sds2_facts) if a.sds2_facts else None
        # bboxes per part id (mm): delivered > source > rebuild
        self.bbox = {}
        for r in self.ver_rows:
            for lo_k, hi_k in (('d_lo', 'd_hi'), ('s_lo', 's_hi'), ('lo', 'hi')):
                lo, hi = parse_xyz(r.get(lo_k)), parse_xyz(r.get(hi_k))
                if lo and hi:
                    self.bbox[r['part_id']] = lo + hi
                    break
        for x in self.step_parts:
            if x.get('pid') and x.get('bbox') and x['pid'] not in self.bbox:
                self.bbox[x['pid']] = [float(v) for v in x['bbox']]
        for x in ((self.sds2 or {}).get('instances') or []):          # SDS/2: the converter's placed instance boxes
            b = x.get('bbox_mm') if isinstance(x, dict) else None
            if x and x.get('guid') and b and len(b) == 2 and x['guid'] not in self.bbox:
                self.bbox[x['guid']] = [float(v) for v in b[0]] + [float(v) for v in b[1]]
        self.sbox = {}                                     # source bbox (markers for parts we fail to build)
        for r in self.ver_rows:
            lo, hi = parse_xyz(r.get('s_lo')), parse_xyz(r.get('s_hi'))
            if lo and hi:
                self.sbox[r['part_id']] = lo + hi
        self.inputs = {}
        for k, p in (('delivered_step', a.delivered), ('verification.csv', vpath), ('parts.csv', os.path.join(S, 'parts.csv')),
                     ('db1_facts', a.db1_facts), ('sds2_facts', a.sds2_facts), ('source_ifc', a.source_ifc)):
            if p and os.path.exists(p):
                self.inputs[k] = lib.sha256_file(p)
        for p in self.conv:
            self.inputs['conv/' + os.path.basename(p)] = lib.sha256_file(p)

    def _first(self, pats):
        for pat in pats:
            for p in self.conv:
                if fnmatch.fnmatch(os.path.basename(p), pat):
                    return p
        return None

    def _pick(self, pats, json_load=False):
        p = self._first(pats)
        return lib.load_json(p) if (p and json_load) else p

    def part_name(self, pid):
        p = self.sp.get(pid)
        if p:
            return p.get('name') or pid
        return self.d_label.get(pid) or pid

    def marks(self, pid):
        p = self.sp.get(pid) or {}
        m = [x for x in (p.get('assembly_mark'), p.get('part_mark')) if x]
        return ' / '.join(dict.fromkeys(m))


# ======================================================================================== rules: our pipeline (all sources)
def rule_verification(C, F):
    n = 0
    for r in C.ver_rows:
        st, pid = r.get('status'), r['part_id']
        if st == 'match':
            continue
        if st == 'no_delivered_part':
            sc = r.get('source_check')
            if sc and sc not in ('exact', 'n/a', 'source_open'):
                F.add(pid, 'PURPLE', 'our_script_differs', f'our rebuild of this missing part differs from the source ({sc})',
                      dict(source='verification.csv', status=st, source_check=sc))
            continue
        if st == 'MISMATCH':
            reason = mismatch_reason(r)
        elif st == 'INVALID_SOLID':
            reason = f"our rebuild gives {r.get('invalid_solids') or 'an'} invalid solid(s) (BRepCheck)"
        elif st in ('BUILD_ERROR', 'BUILD_CRASH'):
            reason = f"our script fails to build it ({lib.ascii_text(r.get('error') or st, 120)})"
        else:
            reason = f'our verification status {st}'
        F.add(pid, 'PURPLE', 'our_script_' + st.lower(), reason,
              dict(source='verification.csv', status=st, source_check=r.get('source_check'),
                   delivered_check=r.get('delivered_check')))
        n += 1
    F.check('our build123d rebuild vs source and delivered (verification.csv)', 'evaluated' if C.ver_rows else 'not_evaluated',
            n, None if C.ver_rows else 'verification.csv missing: the pipeline verify step did not run', 'verification.csv')


def mismatch_reason(r):
    sc, dc = r.get('source_check'), r.get('delivered_check')

    def pct(k):
        v = fnum(r.get(k))
        return None if v is None else f'{v * 100:.2f} %'

    def mm(k):
        v = fnum(r.get(k))
        return None if v is None else f'{v:.2f} mm'
    if sc and sc not in ('exact', 'n/a', 'source_open'):
        bits = [x for x in (pct('src_vol_rel_diff') and 'volume ' + pct('src_vol_rel_diff'),
                            mm('src_centroid_diff_mm') and 'centre ' + mm('src_centroid_diff_mm'),
                            mm('src_bbox_diff_mm') and 'outline ' + mm('src_bbox_diff_mm')) if x]
        return 'our rebuild differs from the source: ' + (', '.join(bits) or sc)
    bits = [x for x in (pct('vol_rel_diff') and 'volume ' + pct('vol_rel_diff'),
                        mm('centroid_diff_mm') and 'centre ' + mm('centroid_diff_mm'),
                        mm('bbox_diff_mm') and 'outline ' + mm('bbox_diff_mm')) if x]
    return f'our rebuild differs from the delivered part ({dc}): ' + (', '.join(bits) or 'see verification.csv')


def rule_missing_from_schedules(C, F, M, not_drawn):
    """parts of our schedules (= the source) the delivered STEP lacks: their id is not among the delivered part ids
    (verification.csv says no_delivered_part for those it could build). Drawn from their schedules (the source
    geometry) by steelbuild; where our script cannot build them, the source bounding box as a marker; else listed."""
    dropped = {}
    if C.db1:
        for d in C.db1.get('dropped_by_step_writer') or []:
            if isinstance(d, dict) and d.get('gid'):
                dropped[d['gid']] = d
    n = 0
    for p in C.sched_parts:
        pid = p['part_id']
        if pid in C.d_ids:
            continue
        r = C.ver.get(pid) or {}
        st = r.get('status')
        nm = p.get('name') or pid
        cls = p.get('ifc_class') or r.get('ifc_class') or ''
        if C.source == 'db1':
            d = dropped.get(pid)
            why = (f"decoded from the DB1 (record {d.get('record')}) into the IFC but dropped by the STEP writer" if d else
                   'in the IFC regenerated from the DB1, not in the delivered STEP')
        elif C.source == 'sds2':
            why = 'in the IFC emitted from the SDS/2 job, not in the delivered STEP'
        else:
            why = 'in the source IFC, not in the delivered STEP'
        F.add(pid, 'RED', 'dropped_by_conversion', why, dict(source='delivered STEP ids vs schedules/parts.csv',
                                                            verification_status=st,
                                                            db1_record=(dropped.get(pid) or {}).get('record')))
        n += 1
        sb = C.sbox.get(pid)
        base = dict(part_id=pid, category='dropped_by_conversion', colour='RED', reason=why, source_ref=f'schedules part {pid}',
                    evidence=dict(source='delivered STEP ids vs schedules/parts.csv', verification_status=st), bbox=sb)
        if st in ('BUILD_ERROR', 'BUILD_CRASH'):
            if sb:
                M.append(dict(base, label=(f'MISSING {nm} ({cls}) - {why}; MARKER ONLY: its source bounding box (our script '
                                           f'does not build it: {st}) [{pid}]'),
                              geometry=dict(kind='bbox_frame', lo=sb[:3], hi=sb[3:]), marker=True))
            else:
                not_drawn.append(f'{pid} {nm}: {why}; our script does not build it ({st}) and no box is recorded')
            continue
        M.append(dict(base, label=f'MISSING {nm} ({cls}) - {why}; rebuilt from the source schedules [{pid}]',
                      geometry=dict(kind='schedule_part', part_id=pid),
                      fallback=dict(kind='bbox_frame', lo=sb[:3], hi=sb[3:]) if sb else None,
                      fallback_label=(f'MISSING {nm} ({cls}) - {why}; MARKER ONLY: its source bounding box (our script '
                                      f'could not build it) [{pid}]'), marker=False))
    F.check('parts of the source missing from the delivered STEP (schedule ids not among the delivered part ids)',
            'evaluated' if C.sched_parts else 'not_evaluated', n, None if C.sched_parts else 'no schedules/parts.csv',
            'parts.csv + delivered STEP')


# ======================================================================================== rules: converter part log (ifc2step6)
IFC_TAG_RULES = [
    # tag, colour, category, reason
    ('L4-surface', 'ORANGE', 'surface_model', 'written as a surface model, no solid (the source body is not a closed solid)'),
    ('L3-partial-surface', 'ORANGE', 'partial_surface', 'partly written as open surfaces (fallback level L3)'),
    ('L2-alt-source', 'ORANGE', 'alt_source', 'written from an alternative source representation (fallback level L2)'),
    ('L1-triangulated', 'ORANGE', 'triangulated', 'written as a triangulated mesh instead of its exact faces (fallback level L1)'),
    ('open_in_source', 'YELLOW', 'open_in_source', 'the source body is open (leaky); the delivered solid(s) are not proven closed'),
    ('sewn', 'YELLOW', 'sewn_by_converter', 'the converter closed small gaps in the source body itself (sewn)'),
    ('stray-faces', 'YELLOW', 'stray_faces', 'carries loose surface patches besides its solid'),
    ('open-surface', 'YELLOW', 'open_surface', 'has open surfaces besides its solid'),
    ('opening-tool-repaired', 'YELLOW', 'opening_repaired', 'the converter repaired an opening tool before cutting'),
    ('unverified', 'YELLOW', 'unverified', "not verified by the converter's read-back"),
    ('kernel_memory_exceeded', 'YELLOW', 'kernel_memory', 'the geometry kernel ran out of memory on this part'),
    ('excluded-corrupt-coordinates', 'YELLOW', 'corrupt_coordinates', 'source coordinates corrupt: excluded by the converter'),
]


def rule_converter_parts(C, F, notes):
    pj = C.parts_json
    if not pj and C.source == 'sds2':
        F.check("converter's per-part log (*.parts.json)", 'not_applicable', None,
                'written by the IFC -> STEP converter only; SDS/2 conversions are covered by the piece table below', None)
        return
    if not pj:
        F.check("converter's per-part log (*.parts.json: fallback levels, tags)", 'not_evaluated', None,
                'no *.parts.json among the conversion detail files', None)
        return
    n = 0
    curved = 0
    for x in pj.get('parts', []):
        gid = x.get('gid')
        tags = set(x.get('tags') or [])
        if 'approx-curved' in tags:
            curved += 1
        if x.get('level') == 4 and 'L4-surface' not in tags:
            tags.add('L4-surface')
        if (x.get('surface_models') or 0) > 0 and not (x.get('solids') or 0):
            tags.add('L4-surface')
        why = [w for w in (x.get('why') or []) if w]
        for tag, col, cat, reason in IFC_TAG_RULES:
            if tag in tags:
                r = reason
                if tag == 'open_in_source' and (x.get('solids') or 0) > 1:
                    r += f" (written as {x['solids']} solids)"
                if why:
                    r += ' [' + ', '.join(map(str, why))[:80] + ']'
                F.add(gid, col, cat, r, dict(source=os.path.basename(C._first(['*.parts.json']) or 'parts.json'),
                                             tags=sorted(tags), level=x.get('level'), solids=x.get('solids'),
                                             surface_models=x.get('surface_models')))
                n += 1
    if curved:
        notes.append(f"{curved} parts carry the converter's 'approx-curved' tag: their curved faces (fillets, round "
                     'bars, tube corners) are stored as flat facets, as every curved face of a faceted STEP is. Not '
                     'coloured: it is the file format, not a defect of the part (our rebuild has the true curves).')
    F.check("converter's per-part log (*.parts.json: fallback levels L1-L4, open / sewn / stray faces)", 'evaluated', n,
            None, os.path.basename(C._first(['*.parts.json'])))


def rule_converter_checks(C, F):
    ck = C.check_json or (C.result_json or {}).get('validate') or {}
    if C.source == 'sds2' and not ck:
        F.check("converter's read-back check (duplicates, invalid / stray parts)", 'not_applicable', None,
                'the SDS/2 converter writes no check.json; its own read-back is in the conversion log', None)
        return
    if not ck:
        F.check("converter's read-back check (*.check.json)", 'not_evaluated', None, 'no check.json', None)
        return
    n = 0
    # duplicated ids
    dup = [pid for pid, k in C.d_ids.items() if k > 1]
    for pid in dup:
        F.add(pid, 'YELLOW', 'duplicate_id', f'{C.d_ids[pid]} delivered parts share this id (the source reuses it)',
              dict(source='delivered STEP product ids'))
        n += 1
    # coincident duplicates: same name, same box (1 mm), same volume (100 mm3)
    if C.step_parts:
        groups = collections.defaultdict(list)
        for x in C.step_parts:
            if x.get('bbox') is None:
                continue
            groups[(x.get('name'), tuple(round(float(v)) for v in x['bbox']), round(float(x.get('volume') or 0), -2))].append(x['pid'])
        for k, v in sorted(groups.items(), key=lambda kv: kv[1]):
            if len(v) > 1 and len(set(v)) > 1:
                for pid in v:
                    F.add(pid, 'YELLOW', 'duplicate', f'DUPLICATE: the same part {len(v)} times at the same spot '
                          f'(records {", ".join(sorted(set(v)))[:120]})', dict(source='step_parts', group=sorted(v)))
                    n += 1
    elif (ck.get('coincident_duplicates') or 0) > 0:
        F.check('coincident duplicates (step_parts)', 'not_evaluated', None,
                f"check.json reports {ck['coincident_duplicates']} but no step_parts list to locate them", 'check.json')
    for ex in ck.get('invalid_examples') or []:
        pid = ex.get('pid') if isinstance(ex, dict) else None
        if pid:
            F.add(pid, 'YELLOW', 'invalid_delivered', 'its delivered solid is not valid (BRepCheck)', dict(source='check.json'))
            n += 1
    for ex in ck.get('stray_examples') or []:
        pid = ex.get('pid') if isinstance(ex, dict) else None
        if pid:
            F.add(pid, 'YELLOW', 'stray_part', 'stray part far from the model (check.json)', dict(source='check.json'))
            n += 1
    F.check("converter's read-back check (duplicates, invalid / stray parts)", 'evaluated', n, None, 'check.json')


def rule_volume_outliers(C, F):
    j = (C.result_json or {}).get('join') or {}
    worst = (j.get('volume') or {}).get('worst') or []
    n = 0
    for w in worst:
        if not isinstance(w, dict):
            continue
        pid = w.get('gid') or w.get('pid')
        ratio = fnum(w.get('ratio')) or fnum(w.get('rel'))
        if not pid or ratio is None:
            continue
        if abs(ratio - 1) > 0.05:
            F.add(pid, 'ORANGE', 'volume_off', f'BROKEN?: volume {ratio:.3f} x the source volume (converter check, > 5 % off)',
                  dict(source='conversion result join.volume.worst', ratio=ratio))
            n += 1
    F.check("converter's volume check against the source (> 5 % off)",
            'evaluated' if j else ('not_applicable' if C.source == 'sds2' else 'not_evaluated'), n,
            None if j else 'no conversion result JSON with a join section', 'conversion result')


def rule_split_parts(C, F):
    """a part (not a bolt group) written as several solids: s4's 'base plate written as 3 pieces' (W_PRODUCT_SOLID_COUNT)"""
    pj = (C.parts_json or {}).get('parts') or []
    n = 0
    for x in pj:
        if (x.get('solids') or 0) > 1 and x.get('cls') not in ('IfcMechanicalFastener', 'IfcFastener', 'IfcDiscreteAccessory') \
                and 'open_in_source' not in (x.get('tags') or []) and not str(x.get('name', '')).upper().startswith('BOLT'):
            F.add(x['gid'], 'YELLOW', 'split_in_pieces', f"one part written as {x['solids']} separate solids",
                  dict(source='parts.json', solids=x['solids'], cls=x.get('cls')))
            n += 1
    F.check('parts written as several separate solids (not bolt groups)',
            'evaluated' if pj else ('not_applicable' if C.source == 'sds2' else 'not_evaluated'), n,
            None if pj else 'no parts.json', 'parts.json')


# ======================================================================================== rules: DB1
APPROX_CATS = [
    ('fitting / line cut not applied', 'fitting_not_applied'), ('slotted holes cut as round', 'slotted_holes_round'),
    ('head and nut nominal', 'bolt_nominal_head_nut'), ('washer thickness nominal', 'washer_nominal'),
    ('washer 2 side inferred', 'washer_side_inferred'), ('axial position unknown', 'bolt_axial_unknown'),
    ('axial position fitted', 'bolt_axial_fitted'), ('axial position from the connected plies', 'bolt_axial_fitted'),
    ('axial position as recorded', 'bolt_axial_recorded'), ('hole = d + standard clearance', 'hole_clearance_nominal'),
    ('bar grating written as a solid plate', 'grating_solid_plate'), ('stud written as its shank only', 'stud_shank_only'),
    ('panel read from an AxB name', 'panel_from_name'), ('corner radii', 'section_derived'), ('root radius', 'section_derived'),
    ('equal-leg angle', 'section_derived'), ('EN 10219', 'section_derived'), ('UPN', 'section_derived'),
    ('polybeam', 'polybeam_straight_segments'), ('curved beam', 'curved_beam_arc'),
    ('cut outline self-crossing', 'cut_outline_repaired'), ('coincident bolt holes merged', 'holes_merged'),
]
_APPROX = re.compile(r'\[approx:\s*([^\]]*)\]?')


def approx_tags(name):
    out = []
    for m in _APPROX.finditer(name or ''):
        for t in m.group(1).split(';'):
            t = t.strip()
            if t:
                out.append(t)
    return out


def rule_approx_names(C, F):
    """'[approx: ...]' in the delivered part names: the converter's own approximation tags (DB1 converter; any source)"""
    n = 0
    names = {}
    for p, pid in C.dparts:
        names.setdefault(pid, p['label'])
    for x in (C.parts_json or {}).get('parts', []):
        if x.get('gid') and '[approx' in (x.get('name') or ''):
            names.setdefault(x['gid'], x['name'])
    for pid, nm in sorted(names.items()):
        for t in approx_tags(nm):
            cat = next((c for k, c in APPROX_CATS if k in t), 'converter_approx')
            F.add(pid, 'ORANGE', cat, t, dict(source='delivered part name [approx: ...] tag'))
            n += 1
    F.check("converter's own '[approx: ...]' tags in the delivered part names", 'evaluated', n, None, 'delivered STEP names')


def rule_db1_facts(C, F, M, notes, not_drawn):
    d = C.db1
    if not d:
        if C.source == 'db1':
            F.check('DB1 records the conversion skipped / cut bodies not applied / slotted plies (src_db1 skipped_records.json)',
                    'not_evaluated', None, 'no skipped_records.json from the DB1 source stage', None)
        return
    usable = bool(d.get('usable_for_red_parts'))
    status = d.get('status')
    # orange: cut bodies not applied to a written parent
    n_cut = 0
    for c in d.get('cut_bodies') or []:
        if c.get('built'):
            continue
        for q in c.get('parents') or []:
            if q.get('written') and q.get('gid'):
                F.add(q['gid'], 'ORANGE', 'cut_not_applied',
                      f"opening / cut NOT applied: DB1 cut record {c['record']} was not built ({c.get('unbuilt_reason')})",
                      dict(source='skipped_records.json cut_bodies', record=c['record']))
                n_cut += 1
    F.check('DB1 cut bodies the converter could not build (their parents keep the material)', 'evaluated', n_cut, None,
            'skipped_records.json')
    # orange: plies of slotted groups whose holes were cut round
    n_ply = 0
    for g in d.get('bolt_groups') or []:
        if (g.get('slot') or {}).get('decision') != 'undecided_holes_cut_round':
            continue
        nb = len(g.get('bolts') or []) or g.get('count') or '?'
        for q in g.get('plies') or []:
            if q.get('written') and q.get('gid'):
                F.add(q['gid'], 'ORANGE', 'slotted_ply_round_holes',
                      f"holes cut ROUND where bolt group {g['record']} ({nb} bolts) is slotted: which plies Tekla slots is not decoded",
                      dict(source='skipped_records.json bolt_groups', group=g['record']))
                n_ply += 1
        if g.get('gid') and g.get('in_shipped_step'):
            F.add(g['gid'], 'ORANGE', 'slotted_holes_round', f"slotted bolt group {g['record']}: holes cut round",
                  dict(source='skipped_records.json bolt_groups', group=g['record']))
    F.check('plies of slotted bolt groups whose holes were cut round', 'evaluated', n_ply, None, 'skipped_records.json')
    # orange: Tekla fittings / line cuts decoded but not applied (also tagged '[approx: ...]' in the delivered names)
    n_fit = 0
    for q in d.get('fittings_not_applied') or []:
        if not isinstance(q, dict) or not q.get('gid') or q.get('in_shipped_step') is False:
            continue
        nf, nl = len(q.get('fittings') or []), len(q.get('line_cuts') or [])
        F.add(q['gid'], 'ORANGE', 'fitting_not_applied',
              f"Tekla fitting / line cut not applied: the member keeps its full length / square ends where Tekla trims it "
              f"({nf} fitting plane(s), {nl} line cut(s) decoded from DB1 record {q.get('record')})",
              dict(source='skipped_records.json fittings_not_applied', record=q.get('record'), fittings=nf, line_cuts=nl))
        n_fit += 1
    F.check('members whose Tekla fittings / line cuts were decoded but not applied', 'evaluated', n_fit, None,
            'skipped_records.json')
    # red: skipped records
    sk = d.get('skipped') or []
    if not usable:
        F.check('DB1 records the conversion skipped -> RED parts', 'not_evaluated', None,
                f"skipped_records.json status {status!r}: its decode is not proven equal to the conversion's, so its "
                'geometry is not used for red parts (listed in WHERE_TO_LOOK as not drawn)', 'skipped_records.json')
        for r in sk:
            notes.append(f"DB1 record {r.get('record')} ({r.get('profile') or 'no profile'}, {r.get('reason')}) was skipped "
                         'by the conversion; not drawn (decode not proven)')
        return
    n = 0
    for r in sk:
        e = db1_missing(r)
        if e is None:
            not_drawn.append(f"DB1 record {r.get('record')} ({r.get('profile') or 'no profile'}, skipped: {r.get('reason')}): "
                             f"the record holds no position or size ({r.get('geometry_recorded') or 'none'})")
            continue
        M.append(e)
        n += 1
    F.check('DB1 records the conversion skipped -> RED parts from their recorded geometry', 'evaluated', n,
            (f'{len(sk) - n} skipped record(s) hold no geometry: listed as not drawn' if len(sk) > n else None),
            'skipped_records.json')


REBAR = re.compile(r'#\s*(\d+)\s*(DEFORMED\s+BAR|BAR|REBAR)?', re.I)
HSS_RECT = re.compile(r'^HSS\s*([\d./-]+)\s*[Xx]\s*([\d./-]+)\s*[Xx]\s*([\d./-]+)$')
HSS_ROUND = re.compile(r'^(?:HSS|PIPE)\s*([\d.]+)\s*[Xx]\s*([\d.]+)$')
ROD = re.compile(r'^(?:ROD|RD|D|Ø)\s*([\d.]+)$', re.I)


def _inch(s):
    """'3-1/2' / '3 1/2' / '3/16' / '4' -> inches"""
    s = s.replace('-', ' ')
    return parse_inch_number(s)


def db1_missing(r):
    """one skipped DB1 record -> missing_parts entry from what the record holds (or None when it holds nothing)"""
    seq, prof, reason = r.get('record'), (r.get('profile') or '').strip(), r.get('reason')
    ax = r.get('axis') or {}
    O, E = ax.get('O'), ax.get('E')
    L = fnum(ax.get('L'))
    attrs = r.get('attributes')
    strings = []
    if isinstance(attrs, list):
        for rec in attrs:
            strings += [s for _, s in (rec.get('strings') or [])] + list(rec.get('rest') or [])
    elif isinstance(attrs, dict):
        strings += [str(v) for v in attrs.values() if v]
    flat = ' | '.join(strings)
    what = None
    for key, nm in (('SLAB', 'concrete slab'), ('WALL', 'concrete wall'), ('FOOTING', 'concrete footing'), ('GROUT', 'grout pad'),
                    ('ANCHOR', 'anchor rod'), ('NUT', 'nut'), ('WASHER', 'washer'), ('REBAR', 'rebar'), ('DEFORMED', 'rebar'),
                    ('CONC', 'concrete part'), ('STUD', 'stud')):
        if key in flat.upper() or key in prof.upper():
            what = nm
            break
    base = dict(category='skipped_by_converter', colour='RED', source_ref=f'DB1 record {seq}',
                reason=f"the converter skipped this DB1 record ({reason})",
                evidence=dict(source='skipped_records.json skipped', record=seq, reason=reason, profile=prof,
                              geometry_recorded=r.get('geometry_recorded'), attribute_strings=strings[:12]),
                bbox=r.get('bbox_world'))
    mat = next((s for s in strings if re.match(r'^(A\d{2,4}|F\d{4}|\d{4} ?PSI|GR ?\d+)', s.strip().upper())), '')
    marker_line = dict(kind='line_marker', start=O, end=E, radius=25.0) if (O and E and L and L > 1) else \
        (dict(kind='marker', at=O, size=100.0) if O else None)
    # 1. contour outline + the number in the profile name (the converter's contour-plate rule: centred on the plane)
    t = fnum(r.get('profile_number_mm'))
    bare = r.get('profile_is_bare_number')
    if bare is None:
        bare = bool(re.fullmatch(r'\s*[\d.]+\s*', prof or ''))
    if r.get('outline_world') and len(r['outline_world']) >= 3 and t and t > 0 and bare:
        z = ax.get('z')
        if z:
            return dict(base, label=(f"MISSING {what or 'contour plate / concrete part'} {prof} mm{(' ' + mat) if mat else ''} - "
                                     f"outline of {len(r['outline_world'])} points from the DB1 record, extruded {t:g} mm (the "
                                     f"number in its profile name), centred on its plane like every contour plate (DB1 record {seq})"),
                        geometry=dict(kind='prism_world', outline_world=r['outline_world'], normal=z, thickness=t, offset=-t / 2),
                        fallback=marker_line, marker=False)
    # 2. rebar #n: diameter n/8 in along the recorded axis
    m = REBAR.search(prof)
    if m and O and E and ('BAR' in prof.upper() or what == 'rebar'):
        d = int(m.group(1)) / 8.0 * IN
        return dict(base, label=f"MISSING rebar {prof}{(' ' + mat) if mat else ''} dia {d:.2f} (#{m.group(1)} = {m.group(1)}/8 in) "
                                f"L={L or 0:.0f} on the recorded axis (DB1 record {seq})",
                    geometry=dict(kind='cylinder', start=O, end=E, radius=d / 2), fallback=marker_line, marker=False)
    # 3. HSS rectangular / round from the profile name (converter's HSS rule: outer radius 2t, inner t)
    m = HSS_RECT.match(prof.upper().replace(' ', ''))
    if m and O and E:
        a_, b_, t_ = (_inch(x) for x in m.groups())
        if a_ and b_ and t_:
            A, B, T = a_ * IN, b_ * IN, t_ * IN
            return dict(base, label=(f"MISSING {prof} tube {A:.1f} x {B:.1f} x {T:.2f} from the profile name (corner radii "
                                     f"2t / t, the converter's HSS rule), L={L or 0:.0f} on the recorded axis (DB1 record {seq})"),
                        geometry=dict(kind='profile', start=O, end=E, x_dir=ax.get('y'),
                                      profile=dict(kind='RHS', b=B, d=A, t=T, r_outer=2 * T, r_inner=T)),
                        fallback=marker_line, marker=False)
    m = HSS_ROUND.match(prof.upper().replace(' ', ''))
    if m and O and E:
        D, T = float(m.group(1)) * IN, float(m.group(2)) * IN
        return dict(base, label=f"MISSING {prof} round tube {D:.1f} x {T:.2f} from the profile name, L={L or 0:.0f} (DB1 record {seq})",
                    geometry=dict(kind='profile', start=O, end=E, x_dir=ax.get('y'), profile=dict(kind='CHS', radius=D / 2, t=T)),
                    fallback=marker_line, marker=False)
    # 4. a named size in a side record (user-profile hardware: anchor rods / nuts / washers), s4's zero-byte case
    size = next((s for s in strings if re.fullmatch(r"\s*\d+(?:/\d+)?\s*(?:''|\")\s*", s)), None)
    if size and O and E and what in ('anchor rod', 'nut', 'washer'):
        dia = parse_inch_number(size.replace("''", '').replace('"', '')) * IN
        if what == 'anchor rod':
            return dict(base, label=(f"MISSING anchor rod {size.strip()} dia{(' ' + mat) if mat else ''} L={L or 0:.1f} - Tekla user "
                                     f"profile not decoded: plain dia {dia:.2f} rod on the recorded axis (DB1 record {seq})"),
                        geometry=dict(kind='cylinder', start=O, end=E, radius=dia / 2), fallback=marker_line, marker=True)
        return dict(base, label=(f"MISSING {size.strip()} {what} - marker only: real outline not decoded, drawn as dia "
                                 f"{2 * dia:.1f} x {L or 0:.2f} disc on the recorded axis (DB1 record {seq})"),
                    geometry=dict(kind='cylinder', start=O, end=E, radius=dia), fallback=marker_line, marker=True)
    # 5. a skipped bolt group: each bolt's shank over its recorded grip (head / nut / washers are not drawn)
    bg = r.get('bolt_group') if isinstance(r.get('bolt_group'), dict) else None
    if bg and bg.get('bolts'):
        cyl = []
        for b in bg['bolts']:
            c, u, dd, gr = b.get('centre'), b.get('axis'), fnum(b.get('d')), b.get('grip')
            if not (c and u and dd and gr and len(gr) == 2 and abs(float(gr[1]) - float(gr[0])) > 0.1):
                cyl = []
                break
            cyl.append(dict(start=[c[i] + float(gr[0]) * u[i] for i in range(3)],
                            end=[c[i] + float(gr[1]) * u[i] for i in range(3)], radius=dd / 2))
        if cyl:
            return dict(base, label=(f"MISSING bolt group {prof} ({len(cyl)} bolts, dia {fnum(bg['bolts'][0].get('d')):.2f}) - "
                                     f"shanks over the recorded grip only; head, nut and washers not drawn (DB1 record {seq})"),
                        geometry=dict(kind='cylinders', items=cyl), fallback=None, marker=False)
        pts = [b.get('centre') for b in bg['bolts'] if b.get('centre')]
        if pts:
            return dict(base, label=(f"MISSING bolt group {prof} ({len(bg['bolts'])} bolts) - MARKER ONLY at the recorded "
                                     f"bolt positions (no usable grip recorded) (DB1 record {seq})"),
                        geometry=dict(kind='markers', at=pts, size=30.0), fallback=None, marker=True)
    # 6. anything else with an axis: a marker along it; a point: a marker there
    if marker_line:
        desc = f"{what} " if what else ''
        return dict(base, label=(f"MISSING {desc}{prof or 'part without profile'} - MARKER ONLY (size unknown: "
                                 f"{'profile not in the catalogue' if prof else 'no profile in the DB1'}); axis and length "
                                 f"{L or 0:.0f} mm as recorded (DB1 record {seq})"),
                    geometry=marker_line, fallback=None, marker=True)
    return None


# ======================================================================================== rules: SDS/2
LABEL_RE = re.compile(r'^\s*(.*?)\s*#\s*(\d+)\s*/\s*(.*?)\s*\(piece\s+(\d+),\s*inst\s+(\d+)\)')
GRATING = re.compile(r'^(GT|GR)\d')
# src_sds2 facts category (what the converter recorded for an instance) -> colour, category, reason
SDS2_CATEGORY = {
    'nominal_bolt': ('ORANGE', 'bolt_from_hole_stack', 'bolt guessed from a hole stack (no SDS/2 bolt record read): '
                     'diameter and grip from the holes; length, head side and washers guessed'),
    'joist_envelope': ('ORANGE', 'joist_envelope', 'joist written as its envelope box: SDS/2 stores only the designation '
                       '(the joist is vendor-designed)'),
    'joist_standin': ('ORANGE', 'joist_standin', 'open-web joist rebuilt from its designation: chord and web sizes are an '
                      'estimate (no joist data in the job)'),
    'member_envelope': ('ORANGE', 'member_envelope', 'member written as its work-line envelope: the job has no fabricated '
                        'pieces for it'),
    'concrete_prism': ('ORANGE', 'concrete_prism', 'concrete written as its L x W x T prism (volume = the SDS/2 quantity)'),
    'flagged_exact': ('ORANGE', 'converter_note', 'the converter attached a stand-in / approximation note to this piece'),
}
SDS2_NOT_COLOURED = {'exact': 'built exactly from its SDS/2 piece', 'sds2_bolt': 'bolt from its SDS/2 bolt record',
                     'turned_primitive': 'stud / rod / anchor built as a turned primitive from its recorded size'}


def sds2_key_of_label(lab):
    m = LABEL_RE.match(lab or '')
    if not m:
        return None
    return (int(m.group(2)), int(m.group(4)), int(m.group(5)))


def rule_sds2(C, F, M, notes, not_drawn):
    if C.source != 'sds2':
        return
    facts = C.sds2 or {}
    weight = sds2_log_weights(C)
    # 1. per instance: what the converter recorded for it (src_sds2 facts: builder / kind / stand-in note -> category)
    inst = [r for r in (facts.get('instances') or []) if isinstance(r, dict) and r.get('guid')]
    n = collections.Counter()
    unknown = collections.Counter()
    for r in inst:
        cat = r.get('category')
        pid = r['guid']
        if cat == 'approximated':
            b = r.get('builder') or ''
            nm = r.get('name') or ''
            if b == 'plate_fallback':
                reason = 'plate approximated by the fallback builder: outline only, no holes'
            else:
                reason = f'piece approximated by the converter (builder {b or "?"})'
            w = weight.get(sds2_piece(r))
            if w:
                reason += f" (its solid is {w} lb heavier than the SDS/2 piece weight: the converter log's largest difference)"
            F.add(pid, 'ORANGE', 'plate_fallback' if b == 'plate_fallback' else 'piece_approx', reason,
                  dict(source='sds2_facts.json instances', builder=b, category=cat))
            n['plate_fallback' if b == 'plate_fallback' else 'piece_approx'] += 1
            if GRATING.match(nm):
                F.add(pid, 'ORANGE', 'grating_solid_panel', 'bar grating written as a solid panel (the bars are not modelled)',
                      dict(source='sds2_facts.json instances', name=nm))
                n['grating_solid_panel'] += 1
            continue
        if cat in SDS2_CATEGORY:
            col, c2, reason = SDS2_CATEGORY[cat]
            if cat == 'flagged_exact' and r.get('standin'):
                reason += f" ({lib.ascii_text(r['standin'], 100)})"
            F.add(pid, col, c2, reason, dict(source='sds2_facts.json instances', builder=r.get('builder'), category=cat))
            n[c2] += 1
        elif cat not in SDS2_NOT_COLOURED:
            unknown[cat] += 1
    if inst:
        F.check("SDS/2 converter's record per instance (src_sds2 facts: builder / stand-in category)", 'evaluated',
                sum(n.values()), ('not coloured, category without a rule: ' + ', '.join(f'{k} x{v}' for k, v in sorted(unknown.items(), key=str))
                                  if unknown else None), 'sds2_facts.json')
        for k, v in sorted(unknown.items(), key=str):
            notes.append(f'{v} instance(s) of facts category {k!r} are not coloured: no rule maps it to a colour (listed for review)')
    else:
        F.check("SDS/2 converter's record per instance (src_sds2 facts)", 'not_evaluated', None,
                'no sds2_facts.json instances from the SDS/2 source stage: only the labels and the piece table are used', None)
    # 2. stand-ins named in the delivered labels (also where the facts are missing)
    k2 = collections.Counter()
    for p, pid in C.dparts:
        L = (p['label'] + ' || ' + (p.get('name') or '')).upper()
        if 'NOMINAL HEAVY HEX' in L:
            F.add(pid, 'ORANGE', 'bolt_from_hole_stack', SDS2_CATEGORY['nominal_bolt'][2], dict(source='delivered label'))
            k2['bolt_from_hole_stack'] += 1
        if '(MEMBER ENVELOPE)' in L:
            c2 = 'joist_envelope' if L.lstrip().startswith('JOIST') else 'member_envelope'
            F.add(pid, 'ORANGE', c2, SDS2_CATEGORY[c2][2], dict(source='delivered label'))
            k2[c2] += 1
        if 'JOIST STAND-IN' in L:
            F.add(pid, 'ORANGE', 'joist_standin', SDS2_CATEGORY['joist_standin'][2], dict(source='delivered label'))
            k2['joist_standin'] += 1
        if '[DERIVED: BOLT RECORD + COAXIAL HOLE' in L:
            F.add(pid, 'YELLOW', 'derived_hole', 'carries a hole the converter derived from a bolt (SDS/2 stores no hole record '
                  'for it)', dict(source='delivered label'))
            k2['derived_hole'] += 1
        if '[APPROX' in L:
            for t in approx_tags(p['label']):
                F.add(pid, 'ORANGE', 'converter_approx', t, dict(source='delivered label [approx: ...] tag'))
                k2['converter_approx'] += 1
    F.check('SDS/2 stand-ins named in the delivered labels (nominal bolts, envelopes, joist stand-ins, derived holes)',
            'evaluated', sum(k2.values()), None, 'delivered STEP labels')
    # 3. the converter's piece table (builder / stand-in per piece instance), the table of the shipped run
    by_key = collections.defaultdict(list)
    for p, pid in C.dparts:
        k = sds2_key_of_label(p['label'])
        if k:
            by_key[k].append(pid)
    stem = os.path.splitext(os.path.basename(C.job.get('step_key') or ''))[0]
    pieces_p = None
    if stem:
        pieces_p = next((p for p in C.conv if os.path.basename(p) == stem + '_pieces.csv'), None)
    pieces_p = pieces_p or C._first(['*_stage2_pieces.csv', '*pieces.csv'])
    rows = read_csv(pieces_p)
    nb = collections.Counter()
    unmatched = 0
    for r in rows:
        try:
            k = (int(r['member']), int(r['piece']), int(r['inst']))
        except (KeyError, ValueError, TypeError):
            continue
        pids = by_key.get(k)
        if not pids:
            unmatched += 1
            continue
        b, kind, nm = (r.get('builder') or ''), (r.get('kind') or ''), (r.get('name') or '')
        why = (r.get('standin') or '').strip()
        hits = []
        if b == 'plate_fallback':
            hits.append(('ORANGE', 'plate_fallback', 'plate approximated by the fallback builder: outline only, no holes'))
            if GRATING.match(nm):
                hits.append(('ORANGE', 'grating_solid_panel', 'bar grating written as a solid panel (the bars are not modelled)'))
        elif b in ('profile_fallback', 'bent_plate_fallback', 'piece_table_standin', 'plate_from_vertices', 'approx'):
            hits.append(('ORANGE', 'piece_approx', f'piece approximated by the converter (builder {b})'))
        elif kind == 'concrete':
            hits.append(('ORANGE', 'concrete_prism', why or SDS2_CATEGORY['concrete_prism'][2]))
        elif why and b not in ('joist_envelope_approx', 'member_envelope', 'joist_openweb_standin'):
            hits.append(('ORANGE', 'converter_note', why))
        for col, cat, reason in hits:
            for pid in pids:
                F.add(pid, col, cat, reason, dict(source=os.path.basename(pieces_p), builder=b, kind=kind, piece=k[1]))
                nb[cat] += 1
    if rows:
        F.check("SDS/2 converter's piece table (builder / stand-in per instance)", 'evaluated', sum(nb.values()),
                (f'{unmatched} table rows have no delivered instance with their label' if unmatched else None),
                os.path.basename(pieces_p))
    else:
        F.check("SDS/2 converter's piece table", 'not_evaluated', None, 'no *_pieces.csv among the conversion files', None)
    # 4. pieces the converter did not build -> RED from the geometry the SDS/2 job records (src_sds2 facts), else a
    #    marker of the recorded extent; the converter's _skipped.csv when the facts are missing
    sk = [r for r in (facts.get('skipped') or []) if isinstance(r, dict)]
    src = 'sds2_facts.json skipped'
    if not sk and not facts:
        sk_p = next((p for p in C.conv if stem and os.path.basename(p) == stem + '_skipped.csv'), None) or \
            C._first(['*_stage2_skipped.csv', '*skipped.csv'])
        sk = read_csv(sk_p)
        src = os.path.basename(sk_p) if sk_p else None
    nr = 0
    for r in sk:
        e = sds2_missing(r)
        if e:
            e['evidence']['table'] = src
            M.append(e)
            nr += 1
        else:
            not_drawn.append(f"SDS/2 piece {r.get('piece')} '{r.get('name')}' (member #{r.get('member')}) was not built by the "
                             f"converter ({r.get('reason')}); the job records no usable position or extent for it")
    rec_n = (facts.get('counts') or {}).get('skipped')
    F.check('SDS/2 pieces the converter did not build -> RED', 'evaluated' if (sk or facts) else 'not_evaluated', nr,
            (f'{len(sk) - nr} not drawn (no recorded position / extent)' if len(sk) > nr else None), src)
    if rec_n is not None and rec_n != len(sk):
        notes.append(f'sds2_facts counts {rec_n} skipped pieces but lists {len(sk)}')
    # 5. members the converter wrote nothing for -> RED marker along the work line the job records
    for mm in facts.get('members_without_geometry') or []:
        p1, p2 = mm.get('p1_mm'), mm.get('p2_mm')
        sec = (mm.get('section') or {}).get('name') or 'no section'
        ref = f"SDS/2 {mm.get('type', '')} #{mm.get('member')}".replace('  ', ' ')
        why = 'the converter wrote nothing for this member (no piece rows, not skipped)'
        if p1 and p2 and math.dist(p1, p2) > 1:
            M.append(dict(category='member_not_written', colour='RED', source_ref=ref, reason=why,
                          label=(f"MISSING {ref} {sec} - {why}; MARKER ONLY along its work line "
                                 f"({math.dist(p1, p2):.0f} mm; the section is not drawn)"),
                          evidence=dict(source='sds2_facts.json members_without_geometry', member=mm.get('member'),
                                        section=mm.get('section')),
                          geometry=dict(kind='line_marker', start=p1, end=p2, radius=25.0), marker=True))
        else:
            not_drawn.append(f'{ref} {sec}: {why}; no usable work line recorded')
    if facts:
        F.check('SDS/2 members the converter wrote nothing for -> RED work-line markers', 'evaluated',
                len(facts.get('members_without_geometry') or []), None, 'sds2_facts.json')


def sds2_piece(r):
    try:
        return int(r.get('piece'))
    except (TypeError, ValueError):
        return None


def sds2_log_weights(C):
    """converter log 'largest differences (lb, piece, name, builder): [(721, 520, 'GR..', 'approx'), ...]' -> {piece: lb}"""
    out = {}
    stem = os.path.splitext(os.path.basename(C.job.get('step_key') or ''))[0]
    logs = [p for p in C.conv if p.endswith('.log') and (not stem or os.path.basename(p).startswith(stem))]
    for p in logs:
        for line in open(p, encoding='utf-8', errors='replace'):
            if 'largest differences' in line:
                for lb, piece in re.findall(r'\((\-?\d+(?:\.\d+)?),\s*(\d+),', line):
                    if float(lb) >= 50:
                        out[int(piece)] = int(round(float(lb)))
    return out


def sds2_missing(r):
    """one skipped SDS/2 piece -> missing_parts entry: the solid src_sds2 confirmed from the job's own records
    (geometry), else a MARKER of the extent of its recorded vertices (placed by the member file), else None"""
    nm, reason = r.get('name') or '', r.get('reason') or 'not built'
    ref = f"SDS/2 {r.get('member_type', '')} #{r.get('member')}, piece {r.get('piece')}, inst {r.get('inst')}".replace('  ', ' ')
    why = {'fallback_over_5x_source_weight': 'its plate fallback came out over 5x the SDS/2 piece weight, so the '
                                              'converter left it out'}.get(reason, reason)
    ev = r.get('source_evidence') or {}
    base = dict(category='not_built_by_converter', colour='RED', source_ref=ref,
                reason=f'the converter did not build this piece ({reason})',
                evidence=dict(source='converter skipped table', member=r.get('member'), piece=r.get('piece'),
                              inst=r.get('inst'), name=nm, reason=reason, piece_table=ev.get('piece_table'),
                              geometry_checks=r.get('geometry_checks'), geometry_withheld=r.get('geometry_withheld')))
    g = r.get('geometry') if isinstance(r.get('geometry'), dict) else None
    pl, vx = ev.get('placement') or {}, ev.get('vertices') or {}
    marker = None
    lb = vx.get('local_bbox_in')
    if pl.get('origin_mm') and pl.get('rows_of_M') and lb and len(lb) == 2:
        Mx = pl['rows_of_M']
        lo, hi = [v * IN for v in lb[0]], [v * IN for v in lb[1]]
        if all(hi[i] - lo[i] > 0.01 for i in range(3)):
            marker = dict(kind='obox_frame', origin=pl['origin_mm'], x=Mx[0], y=Mx[1], lo=lo, hi=hi)
            ext = ' x '.join(f'{frac_in(b - a)}' for a, b in zip(lb[0], lb[1]))
    if marker is None and vx.get('world_bbox_mm') and len(vx['world_bbox_mm']) == 2:
        wb = vx['world_bbox_mm']
        if all(wb[1][i] - wb[0][i] > 0.01 for i in range(3)):
            marker = dict(kind='bbox_frame', lo=wb[0], hi=wb[1])
            ext = 'its world box'
    if g and g.get('kind') in ('prism_world', 'cylinder', 'profile'):
        what = g.get('what') or g['kind']
        return dict(base, label=f"MISSING {nm} ({ref}) - not built by the converter: {why}; drawn as {what}",
                    geometry={k: v for k, v in g.items() if k not in ('what', 'basis')}, geometry_basis=g.get('basis'),
                    fallback=marker, marker=False, bbox=r.get('bbox'))
    if marker:
        held = r.get('geometry_withheld')
        return dict(base, label=(f"MISSING {nm} ({ref}) - not built by the converter: {why}; MARKER ONLY: the extent of "
                                 f"its {vx.get('n') or ''} recorded vertices ({ext} in)"
                                 + (f'; no solid drawn: {held}' if held else '')),
                    geometry=marker, marker=True)
    return None


# ======================================================================================== geometry bboxes of missing entries
def missing_bbox(m):
    if m.get('bbox'):
        return [float(v) for v in m['bbox']]
    g = m['geometry']
    k = g['kind']
    try:
        if k == 'prism_world':
            n = lib._unit(g['normal'])
            t = float(g['thickness'])
            off = float(g.get('offset', -t / 2))
            pts = [lib._add(q, lib._mul(n, off)) for q in g['outline_world']] + \
                  [lib._add(q, lib._mul(n, off + t)) for q in g['outline_world']]
        elif k in ('cylinder', 'line_marker', 'profile'):
            r = float(g.get('radius') or 0) or max(float((g.get('profile') or {}).get(x) or 0) for x in ('b', 'd', 'radius'))
            pts = [lib._add(g['start'], [s * r for s in sg]) for sg in ((1, 1, 1), (-1, -1, -1))] + \
                  [lib._add(g['end'], [s * r for s in sg]) for sg in ((1, 1, 1), (-1, -1, -1))]
        elif k == 'marker':
            h = float(g.get('size', 100)) / 2
            pts = [[x - h for x in g['at']], [x + h for x in g['at']]]
        elif k == 'bbox_frame':
            pts = [g['lo'], g['hi']]
        elif k == 'obox_frame':
            x = lib._unit(g['x'])
            y = lib._unit(lib._sub(g['y'], lib._mul(x, lib._dot(x, g['y']))))
            z = lib._cross(x, y)
            pts = [lib._add(g['origin'], lib._add(lib._mul(x, a), lib._add(lib._mul(y, b), lib._mul(z, c))))
                   for a in (g['lo'][0], g['hi'][0]) for b in (g['lo'][1], g['hi'][1]) for c in (g['lo'][2], g['hi'][2])]
        elif k == 'cylinders':
            pts = []
            for c in g['items']:
                r = float(c['radius'])
                for q in (c['start'], c['end']):
                    pts += [[v - r for v in q], [v + r for v in q]]
        elif k == 'markers':
            h = float(g.get('size', 30)) / 2
            pts = [[v + sg * h for v in q] for q in g['at'] for sg in (-1, 1)]
        else:
            return None
        return [min(p[i] for p in pts) for i in range(3)] + [max(p[i] for p in pts) for i in range(3)]
    except Exception:
        return None


# ======================================================================================== landmarks
class Landmarks:
    def __init__(self, C):
        self.C = C
        boxes = {pid: b for pid, b in C.bbox.items()}
        self.extent = bbox_union(boxes.values())
        cols, beams = [], []
        for pid, b in boxes.items():
            p = C.sp.get(pid, {})
            cls = p.get('ifc_class', '')
            lab = C.d_label.get(pid, '')
            dx, dy, dz = b[3] - b[0], b[4] - b[1], b[5] - b[2]
            horiz = max(dx, dy)
            if cls == 'IfcColumn' or lab.upper().startswith('COLUMN') or (dz > 2000 and dz > 4 * horiz and p.get('role', 'member') == 'member'):
                cols.append((pid, b))
            elif (cls in ('IfcBeam', '') and dz < 600 and horiz > 1500 and p.get('role', 'member') in ('member', '')):
                beams.append((pid, b))
        self.cols = cols
        tops = sorted(round(b[5]) for _, b in beams)
        levels = []
        for z in tops:
            if levels and z - levels[-1][-1] <= 300:
                levels[-1].append(z)
            else:
                levels.append([z])
        thr = max(3, int(0.03 * len(tops)))
        self.levels = [sorted(g)[len(g) // 2] for g in levels if len(g) >= thr]
        self.ground = min((b[2] for _, b in cols), default=self.extent[2] if self.extent else 0.0)

    def colname(self, pid):
        C = self.C
        mk = C.marks(pid)
        nm = C.part_name(pid)
        if C.source == 'sds2':
            lab = C.d_label.get(pid, nm)
            m = re.match(r'^\s*(COLUMN\s*#\s*\d+)', lab, re.I)
            return m.group(1) if m else lab[:40]
        return f'{nm} ({mk})' if mk else nm

    def where(self, b):
        if not b:
            return 'position not recorded'
        c = centre(b)
        bits = []
        if self.levels:
            z = min(self.levels, key=lambda L: abs(L - c[2]))
            if abs(z - b[5]) < 400 or abs(z - c[2]) < 400:
                k = self.levels.index(z) + 1
                bits.append(f'at level {k} (beam tops z ~ {fmt_mm(z)})')
        if self.cols:
            pid, cb = min(self.cols, key=lambda pc: math.hypot(centre(pc[1])[0] - c[0], centre(pc[1])[1] - c[1]))
            cc = centre(cb)
            d = math.hypot(cc[0] - c[0], cc[1] - c[1])
            if d < 600:
                bits.append(f'at column {self.colname(pid)} (x {fmt_mm(cc[0])}, y {fmt_mm(cc[1])})')
            else:
                bits.append(f'{d / 1000:.1f} m from column {self.colname(pid)} (x {fmt_mm(cc[0])}, y {fmt_mm(cc[1])})')
        if self.extent:
            e = self.extent
            for i, ax in ((0, 'X'), (1, 'Y')):
                span = e[i + 3] - e[i]
                if span > 0:
                    if c[i] - e[i] < 0.1 * span:
                        bits.append(f'near the low-{ax} edge')
                    elif e[i + 3] - c[i] < 0.1 * span:
                        bits.append(f'near the high-{ax} edge')
        return '; '.join(bits) if bits else 'inside the model'

    def describe(self):
        C = self.C
        e = self.extent
        if not e:
            return ['(no part positions recorded)']
        out = [f'Coordinates are millimetres in the model\'s own frame, Z up, as the viewer shows them. The model spans '
               f'x {fmt_mm(e[0])} to {fmt_mm(e[3])}, y {fmt_mm(e[1])} to {fmt_mm(e[4])}, z {fmt_mm(e[2])} to {fmt_mm(e[5])} '
               f'(about {(e[3] - e[0]) / 1000:.1f} m x {(e[4] - e[1]) / 1000:.1f} m, {(e[5] - e[2]) / 1000:.1f} m high).']
        if self.levels:
            out.append('Levels (where most beam tops sit): ' + ', '.join(f'level {k + 1} z ~ {fmt_mm(z)}'
                                                                       for k, z in enumerate(self.levels)) + '.')
        if self.cols:
            out.append(f'{len(self.cols)} columns stand from z ~ {fmt_mm(self.ground)}; the notes name the nearest one '
                       f'(name, and marks where the source has them).')
        out.append("'Low-X edge' and similar mean the part sits in the outer tenth of the model on that side.")
        return out


# ======================================================================================== record reconciliation
STANDIN_CATS = {
    'v6_L4-surface': ['surface_model'], 'v6_L3-partial-surface': ['partial_surface'], 'v6_L2-alt-source': ['alt_source'],
    'v6_L1-triangulated': ['triangulated'],
    'hole_slotted_cut_round': ['slotted_holes_round', 'slotted_ply_round_holes'],
    'bolt_nominal_head_nut': ['bolt_nominal_head_nut'], 'washer_nominal': ['washer_nominal'],
    'washer_side_inferred': ['washer_side_inferred'], 'section_parametric_grating': ['grating_solid_plate'],
    'section_parametric_hss': ['section_derived'], 'section_parametric_rhs': ['section_derived'],
    'section_parametric_angle': ['section_derived'], 'bolt_axial_position_fitted': ['bolt_axial_fitted'],
    'bolt_axial_unknown': ['bolt_axial_unknown'], 'stud_shank_only': ['stud_shank_only'], 'panel_from_name': ['panel_from_name'],
    'nominal_bolt_from_hole_stack': ['bolt_from_hole_stack'], 'nominal_bolt': ['bolt_from_hole_stack'],
    'joist_as_envelope_box': ['joist_envelope'], 'joist_openweb_standin': ['joist_standin'],
    'member_as_envelope': ['member_envelope'], 'concrete_as_prism': ['concrete_prism'],
    'plate_fallback_approximate_no_holes': ['plate_fallback'], 'grating_as_solid_panel': ['grating_solid_panel'],
}
UNIT_NOTES = {
    'hole_slotted_cut_round': 'the record counts bolt holes (bolts) of slotted groups; the overlay colours the bolt-group '
                              'products and the plies whose holes were cut round',
    'bolt_nominal_head_nut': 'the record counts bolts; the overlay colours each bolt-group product once',
    'washer_nominal': 'the record counts washers; the overlay colours each bolt-group product once',
    'washer_side_inferred': 'the record counts bolts; the overlay colours each bolt-group product once',
    'bolt_axial_position_fitted': 'the record counts bolts; the overlay colours each bolt-group product once',
}


# categories our rules find that partial records do not list as such, and why
EXTRA_NOTES = {
    'fitting_not_applied': "the partial record does not list fittings / line cuts not applied: the converter reports them "
                           "only in the delivered part names ('[approx: Tekla fitting / line cut not applied ...]')",
    'slotted_ply_round_holes': 'the plies (plates / members) bolted by a slotted group: the record counts the bolts of '
                               'slotted groups; these are the parts whose holes were cut round',
    'duplicate': "the converter's read-back check counts coincident duplicates; the partial record does not list them",
    'duplicate_id': 'several delivered parts share one id (the source reuses it); the partial record does not list them',
    'split_in_pieces': "verify code W_PRODUCT_SOLID_COUNT (a product written as several solids); the record lists it as "
                       "a model-level verifier warning only",
    'open_in_source': "the converter's part log tags the source body as open; the record lists only parts written as "
                      "surfaces",
    'sewn_by_converter': "the converter's part log: it closed gaps in the source body itself; not a stand-in",
    'opening_repaired': "the converter's part log: it repaired an opening tool; not a stand-in",
    'derived_hole': 'a hole the converter derived from a bolt; the record counts holes per piece type, not per instance',
    'converter_approx': "an '[approx: ...]' tag in the delivered name without a matching record item",
    'converter_note': "a stand-in note in the converter's piece table without a matching record item",
    'volume_off': "the converter's volume check (> 5 % off the source)",
    'delivered_part_not_in_schedules': 'delivered parts our schedules lack (our script does not build them)',
}


def _record_count(m):
    cnt = m.get('count')
    if cnt is not None:
        return cnt
    w = m.get('what') or ''
    x = re.search(r':(\d+)\s*$', w) or re.match(r'^\s*(\d+)\s', w)
    return int(x.group(1)) if x else None


def reconcile(C, parts_flags, missing, counts_by_cat):
    """every item of the partial record next to our colour categories and counts, every difference explained; then our
    categories the record does not list"""
    rec = []
    P = C.partial or {}
    covered = set()
    for s_ in P.get('standins') or []:
        t, cnt = s_.get('type'), s_.get('count')
        cats = STANDIN_CATS.get(t, [])
        covered.update(cats)
        ours = sum(counts_by_cat.get(c, 0) for c in cats)
        if not cats:
            expl = 'no rule maps this stand-in type to a colour yet: NOT coloured (listed for review)'
        elif ours == cnt:
            expl = 'same count'
        else:
            per = ', '.join(f'{c} {counts_by_cat.get(c, 0)}' for c in cats)
            expl = (UNIT_NOTES.get(t) or 'different count') + f' ({per})'
        rec.append(dict(record_item=f"standin {t}: {s_.get('real_type')}", record_count=cnt, our_categories=cats,
                        our_count=ours, explanation=expl))
    g = C.job.get('grader') or {}
    gap = (g.get('parts_source') - g.get('parts_step')) if isinstance(g.get('parts_source'), int) and \
        isinstance(g.get('parts_step'), int) else None
    n_red = len(missing)
    red_cats = sorted({m['category'] for m in missing})
    for m in P.get('missing') or []:
        what = m.get('what') or ''
        cnt = _record_count(m)
        low = what.lower()
        if 'not built' in low or 'profiles missing from the catalog' in low or 'not in the step' in low or \
                'skipped' in low or 'dropped' in low:
            covered.update(red_cats)
            if cnt == n_red:
                expl = 'same count'
            else:
                expl = (f"the overlay draws {n_red} missing part(s) in RED from the source records; the record "
                        + ('gives no count' if cnt is None else f'says {cnt}'))
            if gap is not None:
                expl += f" (grader: {g['parts_source']} source parts - {g['parts_step']} in the STEP = {gap})"
            rec.append(dict(record_item=what, record_count=cnt, our_categories=['RED: ' + ', '.join(red_cats)],
                            our_count=n_red, explanation=expl))
        elif 'weight' in low:
            rec.append(dict(record_item=what, record_count=cnt, our_categories=[], our_count=None,
                            explanation='a model-level check (total steel weight); the pieces behind it are coloured '
                                        'where the converter log names them (largest differences)'))
        elif what == 'verify':
            rec.append(dict(record_item='verify (the conversion verifier warned)', record_count=cnt, our_categories=[],
                            our_count=None, explanation='model-level verifier code(s): ' + ', '.join(C.job.get('verify_codes') or [])))
        else:
            rec.append(dict(record_item=what, record_count=cnt, our_categories=[], our_count=None,
                            explanation='the same items as a stand-in row above (the record lists them in both its '
                                        'missing and standins lists)'))
    for cat, n in sorted(counts_by_cat.items()):
        if cat in covered or cat.startswith('our_script') or cat == 'dropped_by_conversion':
            continue
        rec.append(dict(record_item='(not in the record)', record_count=None, our_categories=[cat], our_count=n,
                        explanation=EXTRA_NOTES.get(cat, 'found by our rules; the partial record does not list this category')))
    ours = sum(n for c, n in counts_by_cat.items() if c.startswith('our_script'))
    if ours:
        rec.append(dict(record_item='(not in the record)', record_count=None,
                        our_categories=sorted(c for c in counts_by_cat if c.startswith('our_script')), our_count=ours,
                        explanation='our own build123d script (verification.csv): not a property of the delivered STEP'))
    return rec


# ======================================================================================== WHERE_TO_LOOK.md
COLOUR_WORD = {'RED': 'missing', 'ORANGE': 'approximated by the converter', 'YELLOW': 'to check',
               'PURPLE': 'our build123d script does not rebuild them perfectly yet', 'GREY': 'fine'}


def where_to_look(C, LM, issues, missing, rec, notes):
    name = C.name
    cr, cd = issues['counts']['rebuild'], issues['counts']['delivered']
    L = []
    L.append(f'# {C.title}: where to look')
    L.append('')
    L.append(f"Delivered STEP: `{C.relpath}` (converted from {C.source.upper()}: `{C.job.get('converted_from') or ''}`), "
             f"model id `{C.model_id}`. The partial record calls it **{(C.partial or {}).get('kind', '?')}**.")
    L.append('')
    L.append('**Legend:** GREY = fine. RED = MISSING: the conversion dropped it; drawn here only from geometry the source '
             'records ("marker only" = the source records where it is but not its size). ORANGE = APPROX: the converter '
             'approximated it. YELLOW = CHECK: suspicious. PURPLE = OUR-SCRIPT-NOT-PERFECT: our build123d script does '
             'not rebuild it to "match" yet. A part with several problems shows one colour (RED > YELLOW > ORANGE > '
             'PURPLE: a problem of the delivered STEP shows before a shortfall of our own script) and its name lists '
             'every reason.')
    L.append('')
    L.append('## Files')
    L.append(f'- `{name}_ISSUES_highlighted.step`: the whole model rebuilt from `schedules/` by our script, every part '
             'coloured, one folder per colour in the part tree (hide the GREY folder to see only the problems). Made by '
             '`python build_issues_model.py`.')
    if missing:
        L.append(f'- `{name}_MISSING_parts_only.step`: only the {len(missing)} RED parts (use it to find small ones).')
    L.append(f'- `{name}_ISSUES_on_delivered.step` (not shipped; one command): the delivered STEP itself with the same '
             'colours. Only part names change and colours are added; the delivered geometry stays byte for byte as '
             'delivered and the red parts are added. Make it with `python build_issues_model.py --from-delivered` '
             f"(it reads `../../{C.relpath}`).")
    L.append('- `schedules/issues.json` lists every coloured part with its id, colour, every reason and the evidence; '
             '`schedules/missing_parts.json` lists every red part with the source geometry it is drawn from.')
    L.append('- In the viewer\'s part list search for `MISSING`, `APPROX`, `CHECK` or `OUR-SCRIPT-NOT-PERFECT`.')
    L.append('')
    L.append('## Counts')
    L.append('| colour | rebuilt model | delivered STEP coloured | what |')
    L.append('|---|---|---|---|')
    for c in lib.COLOURS:
        L.append(f'| {c} | {cr.get(c, 0):,} | {cd.get(c, 0):,} | {COLOUR_WORD[c]} |')
    L.append(f'| total | {sum(cr.values()):,} | {sum(cd.values()):,} | |')
    sf_ = issues.get('script_shortfall') or {}
    if sf_.get('parts'):
        other = ', '.join(f'{v} {k}' for k, v in sorted(sf_.get('shown_in', {}).items()))
        L.append('')
        L.append(f"Our build123d script does not rebuild {sf_['parts']:,} part(s) perfectly: {sf_.get('shown_purple', 0):,} "
                 f"shown PURPLE" + (f', the others shown in a colour that wins over purple ({other}); their names list that '
                                    'reason too ("our rebuild ..." / "our script ...")' if other else '') + '.')
    if issues.get('not_drawn'):
        L.append('')
        L.append(f"Not drawn ({len(issues['not_drawn'])}; no geometry and no recorded box to mark): "
                 + '; '.join(issues['not_drawn'][:10]) + (' ...' if len(issues['not_drawn']) > 10 else '') + '.')
    L.append('')
    L.append('## Finding your way around')
    for s in LM.describe():
        L.append('- ' + s)
    L.append('')
    by_col = collections.defaultdict(lambda: collections.defaultdict(list))
    for pid, e in issues['parts'].items():
        for f in e['flags']:
            if f['colour'] == e['colour']:
                by_col[e['colour']][f['category']].append((pid, e, f))
    for m in missing:
        if not m.get('part_id'):                     # schedule parts are listed with their flags above
            by_col['RED'][m['category']].append((m['id'], m, m))
    for d in issues.get('delivered_only', []):
        by_col[d['colour']]['delivered_part_not_in_schedules'].append((d['id'], d, d))
    for col in ('RED', 'ORANGE', 'YELLOW', 'PURPLE'):
        cats = by_col.get(col)
        n = cr.get(col, 0) if col != 'GREY' else 0
        L.append(f'## {col}: {COLOUR_WORD[col]} ({cd.get(col, 0):,} in the delivered STEP coloured, {n:,} in the rebuilt model)')
        if not cats:
            L.append('None.')
            L.append('')
            continue
        for cat, items in sorted(cats.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            reasons = collections.Counter(it[2].get('reason', '') for it in items)
            top = reasons.most_common(1)[0][0]
            L.append(f'### {cat.replace("_", " ")} ({len(items)})')
            L.append(f'**Why:** {top}' + (f' (and {len(reasons) - 1} variants of this reason, see issues.json)' if len(reasons) > 1 else ''))
            ev = items[0][2].get('evidence') or {}
            if ev.get('source'):
                L.append(f"**Evidence:** {ev['source']}.")
            boxes = []
            for pid, e, f in items:
                b = e.get('bbox') or C.bbox.get(pid)
                boxes.append((pid, e, b))
            if len(items) <= 12:
                L.append('**Where:**')
                for pid, e, b in boxes:
                    nm = e.get('name') or C.part_name(pid)
                    mk = C.marks(pid)
                    pos = (f'x {fmt_mm(b[0])}..{fmt_mm(b[3])}, y {fmt_mm(b[1])}..{fmt_mm(b[4])}, z {fmt_mm(b[2])}..{fmt_mm(b[5])}'
                           if b else 'position not recorded')
                    L.append(f'- `{lib.ascii_text(nm, 70)}`' + (f' (mark {mk})' if mk else '') + f': {pos}; {LM.where(b)}.')
            else:
                ub = bbox_union(b for _, _, b in boxes)
                if ub:
                    L.append(f'**Where:** spread over x {fmt_mm(ub[0])}..{fmt_mm(ub[3])}, y {fmt_mm(ub[1])}..{fmt_mm(ub[4])}, '
                             f'z {fmt_mm(ub[2])}..{fmt_mm(ub[5])}.')
                lv = collections.Counter()
                for _, _, b in boxes:
                    if b and LM.levels:
                        z = min(LM.levels, key=lambda q: abs(q - centre(b)[2]))
                        lv[f'level {LM.levels.index(z) + 1} (z ~ {fmt_mm(z)})' if abs(z - centre(b)[2]) < 1500 else 'between levels'] += 1
                if lv:
                    L.append('By height: ' + ', '.join(f'{k}: {v}' for k, v in sorted(lv.items())) + '.')
                names = collections.Counter(lib.ascii_text((e.get('name') or C.part_name(pid)).split(' [approx')[0], 40)
                                            for pid, e, _ in boxes)
                L.append('By name: ' + ', '.join(f'{k} x{v}' for k, v in names.most_common(8)) +
                         (f', ... ({len(names)} names)' if len(names) > 8 else '') + '.')
                L.append('First 8 (all are in issues.json):')
                for pid, e, b in boxes[:8]:
                    nm = e.get('name') or C.part_name(pid)
                    L.append(f'- `{lib.ascii_text(nm, 60)}` at {fmt_pt(centre(b)) if b else "?"}: {LM.where(b)}.')
            L.append('')
    L.append('## Checked against the partial record')
    L.append('| record says | count | our colour categories | our count | why they differ |')
    L.append('|---|---|---|---|---|')
    for r in rec:
        L.append(f"| {lib.ascii_text(r['record_item'], 120)} | {r['record_count'] if r['record_count'] is not None else '-'} | "
                 f"{', '.join(r['our_categories']) or '-'} | {r['our_count'] if r['our_count'] is not None else '-'} | "
                 f"{r['explanation']} |")
    L.append('')
    L.append('## What was checked')
    for ck in issues['checks']:
        st = ck['status'].replace('_', ' ')
        L.append(f"- {ck['check']}: {st}" + (f", {ck['flagged']} flags" if ck.get('flagged') is not None else '') +
                 (f" ({ck['why']})" if ck.get('why') else '') + '.')
    if notes:
        L.append('')
        L.append('## Not coloured (for information)')
        for n_ in notes[:40]:
            L.append('- ' + n_)
        if len(notes) > 40:
            L.append(f'- ... and {len(notes) - 40} more (issues.json "notes")')
    L.append('')
    L.append(f'_Made by {MAKER_VERSION} / {lib.VERSION} from the files listed in issues.json "inputs" (sha256)._')
    return '\n'.join(L) + '\n'


# ======================================================================================== main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--job', required=True)
    ap.add_argument('--sched', required=True)
    ap.add_argument('--delivered', required=True)
    ap.add_argument('--out-sched', required=True)
    ap.add_argument('--out-issues', required=True)
    ap.add_argument('--conv', default=None)
    ap.add_argument('--db1-facts', default=None)
    ap.add_argument('--sds2-facts', default=None)
    ap.add_argument('--source-ifc', default=None, help='the source IFC our schedules were extracted from (its sha256 is '
                                                      'recorded in issues.json inputs)')
    ap.add_argument('--model-name', default=None)
    a = ap.parse_args()
    C = Ctx(a)
    F = Flags()
    M = []
    notes = []
    not_drawn = []
    # ---- id mapping sanity: the delivered ids must be our schedule ids
    sched_ids = set(C.sp)
    d_ids = set(C.d_ids)
    overlap = len(d_ids & sched_ids)
    if d_ids and sched_ids and overlap < 0.5 * min(len(d_ids), len(sched_ids)):
        sys.exit(f'id scheme {C.scheme!r}: only {overlap} of {len(d_ids)} delivered part ids are schedule ids - refusing to '
                 'colour a model whose parts cannot be matched')
    # ---- rules
    rule_verification(C, F)
    rule_missing_from_schedules(C, F, M, not_drawn)
    rule_converter_parts(C, F, notes)
    rule_converter_checks(C, F)
    rule_volume_outliers(C, F)
    rule_split_parts(C, F)
    rule_approx_names(C, F)
    rule_db1_facts(C, F, M, notes, not_drawn)
    rule_sds2(C, F, M, notes, not_drawn)
    # delivered parts our schedules lack -> PURPLE (our script does not build them)
    for pid in sorted(d_ids - sched_ids):
        F.add(pid, 'PURPLE', 'delivered_part_not_in_schedules', 'our script does not build this delivered part (it is '
              'not in our schedules)', dict(source='delivered STEP ids vs schedules'))
    # ---- resolve colours
    parts = {}
    counts_by_cat = collections.Counter()
    for pid in sorted(F.f):
        flags = sorted(F.f[pid], key=lambda x: (lib.PRECEDENCE.index(x['colour']), x['category'], x['reason']))
        col = lib.resolve_colour({x['colour'] for x in flags})
        in_del = pid in d_ids
        in_sched = pid in C.sp
        if not in_del and not in_sched:
            notes.append(f'{len(flags)} flag(s) for id {pid}, which is neither a delivered part nor a schedule part: not '
                         f"coloured ({'; '.join(x['reason'] for x in flags)[:200]})")
            continue
        reasons = []
        for x in flags:
            for r_ in [x['reason']] + x.get('also', []):
                if r_ not in reasons:
                    reasons.append(r_)
        st = (C.ver.get(pid) or {}).get('status')
        mb, mwhat = (C.sbox.get(pid), 'its source bounding box') if C.sbox.get(pid) else \
            ((C.bbox.get(pid), 'its delivered bounding box') if C.bbox.get(pid) else (None, None))
        e = dict(colour=col, name=C.part_name(pid), marks=C.marks(pid) or None, in_delivered=in_del, in_schedules=in_sched,
                 delivered_label=C.d_label.get(pid), verification_status=st, reasons=reasons, flags=flags,
                 bbox=C.bbox.get(pid), marker_bbox=mb, marker_what=mwhat)
        if st == 'BUILD_CRASH':
            e['no_build'] = True                 # its build crashes the process: build_issues_model.py does not build it
        if in_sched and st in ('BUILD_ERROR', 'BUILD_CRASH') and not mb:
            e['not_drawn'] = True
            if pid in d_ids:
                not_drawn.append(f'{pid} {C.part_name(pid)}: our script does not build it ({st}) and no box is recorded '
                                 '(it is in the delivered STEP; colour it there with --from-delivered)')
        parts[pid] = e
        for x in flags:
            counts_by_cat[x['category']] += 1
    delivered_only = []
    for pid in sorted(d_ids - sched_ids):
        e = parts.get(pid)
        if e:
            delivered_only.append(dict(id=pid, colour=e['colour'], label=lib.label_for(e, C.d_label.get(pid, pid), pid, True),
                                       bbox=C.bbox.get(pid)))
    # ---- missing entries: ids, bboxes, labels
    M.sort(key=lambda m: (m['category'], str(m.get('source_ref')), str(m.get('part_id') or '')))
    for k, m in enumerate(M, 1):
        m['id'] = f'M{k:04d}'
        m['bbox'] = missing_bbox(m)
        if not m['label'].startswith('MISSING'):
            m['label'] = 'MISSING ' + m['label']
        if m.get('fallback') is None:
            m.pop('fallback', None)
        if m.get('part_id') and m['part_id'] in parts:
            parts[m['part_id']]['missing_entry'] = m['id']
    # ---- counts (what build_issues_model.py writes: one leaf part per count)
    cnt_d = collections.Counter()
    for p, pid in C.dparts:
        e = parts.get(pid)
        cnt_d[e['colour'] if e else 'GREY'] += 1
    cnt_d['RED'] += len(M)
    cnt_r = collections.Counter()
    for p in C.sched_parts:
        pid = p['part_id']
        e = parts.get(pid)
        if e and e.get('not_drawn'):
            if pid not in d_ids:
                pass                              # a missing part without geometry: already listed by its rule
            continue
        cnt_r[e['colour'] if e else 'GREY'] += 1
    cnt_r['RED'] += sum(1 for m in M if not m.get('part_id'))
    for d in delivered_only:
        if d.get('bbox'):
            cnt_r[d['colour']] += 1
        else:
            not_drawn.append(f"{d['id']} (delivered part not in our schedules, no recorded box): not in the rebuilt model")
    # our script's shortfall in total (PURPLE shows only where nothing worse applies)
    ours = sorted(pid for pid, e in parts.items() if any(f['colour'] == 'PURPLE' for f in e['flags']))
    script_shortfall = dict(parts=len(ours), shown_purple=sum(1 for pid in ours if parts[pid]['colour'] == 'PURPLE'),
                            shown_in=dict(collections.Counter(parts[pid]['colour'] for pid in ours if parts[pid]['colour'] != 'PURPLE')))
    # categories summary
    cats = []
    seen = collections.defaultdict(lambda: [0, ''])
    for pid, e in parts.items():
        for f in e['flags']:
            k = (f['colour'], f['category'])
            seen[k][0] += 1
            seen[k][1] = seen[k][1] or f['reason']
    for m in M:
        if m.get('part_id'):
            continue                              # counted with its schedule part's flag
        k = ('RED', m['category'])
        seen[k][0] += 1
        seen[k][1] = seen[k][1] or m['reason']
    for (col, cat), (n, what) in sorted(seen.items(), key=lambda kv: (lib.PRECEDENCE.index(kv[0][0]), kv[0][1])):
        cats.append(dict(colour=col, category=cat, count=n, what=what))
    rec = reconcile(C, parts, M, counts_by_cat + collections.Counter(m['category'] for m in M if not m.get('part_id')))
    issues = collections.OrderedDict(
        schema='pmp-issues/1', version=lib.VERSION, maker=MAKER_VERSION, model_id=C.model_id, model_name=C.name,
        title=C.title, step_source=C.source, pid=C.job.get('pid') or C.job.get('project_id'),
        delivered=dict(relpath=C.relpath, sha256=C.sf.sha256, id_scheme=C.scheme, parts=len(C.dparts),
                       distinct_ids=len(d_ids), ids_in_schedules=overlap),
        step_time=C.step_time, units='mm', colours={k: list(v) for k, v in lib.COLOURS.items()},
        precedence=lib.PRECEDENCE, label_prefix=lib.PREFIX,
        counts=dict(rebuild={c: cnt_r.get(c, 0) for c in lib.COLOURS}, delivered={c: cnt_d.get(c, 0) for c in lib.COLOURS}),
        categories=cats, parts=parts, delivered_only=delivered_only, missing=[m['id'] for m in M], not_drawn=not_drawn,
        script_shortfall=script_shortfall,
        record=C.partial, verify_codes=C.job.get('verify_codes'), reconciliation=rec, checks=F.checks, notes=notes,
        inputs=dict(sorted(C.inputs.items())))
    missing = dict(schema='pmp-missing/1', version=lib.VERSION, model_id=C.model_id, units='mm',
                   conventions=dict(
                       schedule_part='a part of schedules/parts.csv (the source) built by steelbuild exactly as build_model.py',
                       prism_world='outline_world points on the record plane, extruded thickness along normal from offset',
                       cylinder='start / end / radius: a round bar on the recorded axis',
                       profile='a section (profiles.csv-style row) from start to end, section x axis along x_dir',
                       line_marker='MARKER ONLY: a 50 mm rod along the recorded axis (size unknown)',
                       marker='MARKER ONLY: a 100 mm cube at the recorded point (size unknown)',
                       bbox_frame='MARKER ONLY: the 12 edges of a recorded bounding box',
                       obox_frame='MARKER ONLY: the 12 edges of a recorded extent in its own frame (origin, x, y; local lo..hi)',
                       cylinders='several round bars (start / end / radius each), e.g. the bolt shanks of a bolt group',
                       markers='MARKER ONLY: a small cube at each recorded point (e.g. bolt positions without a usable grip)',
                       fallback='the marker drawn when the geometry does not make a valid solid'),
                   parts=M)
    os.makedirs(a.out_sched, exist_ok=True)
    os.makedirs(a.out_issues, exist_ok=True)
    LM = Landmarks(C)
    for e in parts.values():
        e['where'] = LM.where(e.get('bbox'))
    for m in M:
        m['where'] = LM.where(m.get('bbox'))
    with open(os.path.join(a.out_sched, 'issues.json'), 'w', encoding='utf-8') as f:
        json.dump(issues, f, indent=1, sort_keys=False, default=str)
        f.write('\n')
    with open(os.path.join(a.out_sched, 'missing_parts.json'), 'w', encoding='utf-8') as f:
        json.dump(missing, f, indent=1, default=str)
        f.write('\n')
    with open(os.path.join(a.out_issues, 'WHERE_TO_LOOK.md'), 'w', encoding='utf-8') as f:
        f.write(where_to_look(C, LM, issues, M, rec, notes))
    print(json.dumps(dict(model_id=C.model_id, source=C.source, rebuild=issues['counts']['rebuild'],
                          delivered=issues['counts']['delivered'], missing=len(M), flagged=len(parts),
                          not_drawn=len(not_drawn), checks_not_evaluated=[c['check'] for c in F.checks
                                                                          if c['status'] != 'evaluated'])))


if __name__ == '__main__':
    main()
