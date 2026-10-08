#!/usr/bin/env python3
"""Independent checksum of a rebuilt model against the fabricator's KISS files.

A KISS file (Tekla Structures "KISS" export, .kss) carries no geometry and no positions. Per assembly mark it lists the
number of assemblies, every piece (piece mark, quantity, shape, size, grade, length, finish, name), the bolts and the
hole / weld / cut counts. This tool compares those numbers with the schedules the model is rebuilt from:

  assembly level  presence of the mark, number of assemblies, sequences (S records)
  piece level     presence and quantity of every piece mark, preliminary marks (A records), name, profile designation,
                  section dimensions measured on the rebuilt section, grade, length measured on the rebuilt solid
                  (+-2 mm), plate thickness / width / length, hole count and hole sizes
  connections     bolts per assembly (count, diameter x length, grade, field / shop), welds per assembly (count, length)
  weight          rebuilt weight per assembly (KISS has none); per preliminary mark against an advance bill (--weights)

Several KISS files may repeat or revise an assembly mark (submittals, "galvanized" / "painted" member lists, re-exports).
Rule: per (job number, assembly mark) the version from the file with the latest export time (H record date + time) is
used; ties are broken by file name, then by position in the file. Optionally only files exported at or before --asof
are used. Every mark that occurs in more than one file is reported with what changed between the versions, and every
disagreement lists the other KISS versions of the same item that would agree with the model.

The tool reads CSV / JSON / KISS text only (no IFC, no CAD kernel); the model side comes from the schedule folder:
parts.csv, solids.csv, profiles.csv, profile_outlines.json, openings.csv, cuts.csv, part_properties.jsonl,
verification.csv (rebuilt volumes) and exact_geometry.jsonl (for parts built from exact faces).

usage: kiss_check.py SCHEDULE_DIR KSS_FILE [KSS_FILE ...] [--asof DATE] [--model-date DATE | --ifc MODEL.ifc]
                     [--weights ABM.csv ...] [--out NAME] [--length-tol MM]
writes SCHEDULE_DIR/kiss_check.csv (one row per comparison) and SCHEDULE_DIR/kiss_summary.json
"""
import argparse, collections, csv, datetime, hashlib, json, math, os, re, sys, zipfile

VERSION = 'kiss_check 1.0 (2026-10-06)'
LENGTH_TOL = 2.0          # mm, piece length (task specification)
DIM_TOL = 0.5             # mm, section / plate dimensions measured on the rebuilt geometry
PLATE_W_TOL = 1.5975      # mm, plate width: in KISS it is the designation text, rounded to 1/16 in (1.5875 mm)
NUM_TOL = 0.011           # mm, two KISS numbers are "the same" (exports round 9.525 to 9.52 or 9.53)
HOLE_TOL = 0.05           # mm, hole diameter
BOLT_TOL = 0.1            # mm, bolt diameter / length (bolt property sets are rounded to 0.1 mm)
WELD_TOL = 0.1            # mm, weld length / size (weld property sets are rounded to 0.1 mm)
STEEL_DENSITY = 7.85e-6   # kg / mm3
LB = 0.45359237           # kg
INCH = 25.4
WEIGHT_TOL = 0.03         # relative, linear weight against an advance bill of materials (see REPORT)

# ====================================================================================== small helpers


def fnum(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def inum(v):
    x = fnum(v)
    return None if x is None else int(round(x))


def fmt(v, nd=2):
    if v is None:
        return ''
    if isinstance(v, float):
        s = ('%.' + str(nd) + 'f') % v
        return s.rstrip('0').rstrip('.') if '.' in s else s
    return str(v)


def close(a, b, tol):
    return a is not None and b is not None and abs(a - b) <= tol


def parse_dt(s):
    """'2022-03-29', '2022-03-29T17:36', '2022-03-29 17:36:05', '03/29/22 17:36' -> datetime"""
    if s is None:
        return None
    s = s.strip()
    for f in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d', '%m/%d/%y %H:%M',
              '%m/%d/%Y %H:%M'):
        try:
            return datetime.datetime.strptime(s, f)
        except ValueError:
            pass
    raise ValueError('unrecognised date ' + repr(s))


def dts(d):
    return d.strftime('%Y-%m-%d %H:%M') if d else ''


# ====================================================================================== imperial sizes

_NUM = r'(?:\d+\.\d*|\.\d+|\d+)'


def parse_inch(tok):
    """'3-1/4', '3 1/4', '3/8', '14', '0.280', '1\'-2', '1\'-2 1/2"' -> inches (float) or None"""
    t = (tok or '').strip().replace('"', '').replace('″', '').strip()
    if not t:
        return None
    feet = 0.0
    m = re.fullmatch(r"(%s)\s*'\s*-?\s*(.*)" % _NUM, t)
    if m:
        feet = float(m.group(1))
        t = m.group(2).strip()
        if not t:
            return feet * 12.0
    m = re.fullmatch(r'(\d+)\s*/\s*(\d+)', t)
    if m:
        return feet * 12.0 + float(m.group(1)) / float(m.group(2)) if float(m.group(2)) else None
    m = re.fullmatch(r'(%s)(?:(?:\s*-\s*|\s+)(\d+)\s*/\s*(\d+))?' % _NUM, t)
    if not m:
        return None
    v = float(m.group(1))
    if m.group(2):
        if not float(m.group(3)):
            return None
        v += float(m.group(2)) / float(m.group(3))
    return feet * 12.0 + v


# KISS shape code / designation prefix -> family. Evidence: the shapes used in the 117 KISS files of the three Tekla
# sample packages and the profile names in their models (REPORT.md, "Field meanings").
FAMILY = {'W': 'W', 'M': 'M', 'S': 'S', 'HP': 'HP', 'C': 'C', 'MC': 'MC', 'L': 'L', 'WT': 'WT', 'MT': 'MT', 'ST': 'ST',
          'HSS': 'HSS', 'TS': 'HSS', 'PIPE': 'PIPE', 'P': 'PIPE', 'PL': 'PL', 'FL': 'PL', 'FLT': 'PL', 'BPL': 'PL',
          'RB': 'RB', 'ROD': 'RB', 'BAR': 'RB', 'DBA': 'DBA', 'STUD': 'STUD', 'STUD_': 'STUD', 'HS': 'BOLT', 'MB': 'BOLT',
          'PD': 'PD', '#': '#', 'GRTG': 'GRTG'}
DIMENSIONED = {'L', 'HSS', 'PL', 'RB', 'DBA', 'STUD', 'PD', '#'}    # families whose size string is a list of dimensions
NOMINAL = {'W', 'M', 'S', 'HP', 'C', 'MC', 'WT', 'MT', 'ST'}   # depth x weight per foot: needs a catalogue, not dims


def split_size(size):
    """'3/8X3-1/4' -> ['3/8', '3-1/4']; '3/4-DIA' -> ['3/4']; 'PL1/2"X12 9/16"' style tokens are handled by callers"""
    s = (size or '').upper().replace('"', '').replace('×', 'X').replace('*', 'X').strip()
    s = re.sub(r'-?DIA\.?$', '', s).strip()
    return [x.strip() for x in s.split('X') if x.strip()]


def designation_key(family, size):
    """(family, dims in inches or None, normalised text) for one profile"""
    fam = FAMILY.get(family.upper(), family.upper()) if family else ''
    toks = split_size(size)
    dims = [parse_inch(t) for t in toks]
    text = fam + 'X'.join(re.sub(r'\s+', ' ', t) for t in toks)
    if not toks or any(d is None for d in dims):
        dims = None
    return fam, (tuple(dims) if dims else None), text


def kiss_designation(shape, size):
    return designation_key(shape, size)


def model_designation(desig):
    """'PL3/8"X3 1/4"', 'W14X30', 'L4X4X5/16', 'RB3/4"', 'HSS6X3X1/4', 'DBA3/4', 'FL1/4"X3"' -> designation_key"""
    d = (desig or '').strip().upper().replace('"', '')
    if not d:
        return None
    m = re.match(r'^([A-Z#_]+?)\s*(?=[\d.])', d)
    if not m:
        return designation_key('', d) if d else None
    return designation_key(m.group(1), d[m.end():])


def same_designation(k, m):
    """k, m: designation_key tuples. Family must agree; dimensions within 0.001 in when both parse, else text."""
    if k is None or m is None:
        return False
    if k[0] != m[0]:
        return False
    if k[1] is not None and m[1] is not None:
        if len(k[1]) != len(m[1]):
            return False
        if k[0] == 'L' and len(k[1]) == 3:      # angle legs may be listed in either order
            return close(k[1][2], m[1][2], 1e-3) and sorted(k[1][:2]) == sorted(m[1][:2]) or \
                all(close(a, b, 1e-3) for a, b in zip(k[1], m[1]))
        return all(close(a, b, 1e-3) for a, b in zip(k[1], m[1]))
    return k[2] == m[2]


def norm_grade(g):
    """'STEEL/A992' -> 'A992'; 'A500-GR.B' -> 'A500B'; 'A572 GR 50' -> 'A57250'; 'ASTM F1852' -> 'F1852'"""
    s = (g or '').upper()
    if '/' in s:
        s = s.split('/')[-1]
    s = s.replace('ASTM', '')
    s = re.sub(r'GRADE|GR\.?', '', s)
    return re.sub(r'[^A-Z0-9]', '', s)


def norm_bolt_grade(g):
    s = norm_grade(g)
    m = re.fullmatch(r'(A325|A490)(N|X|SC|T)?', s)
    return m.group(1) if m else s


def norm_text(s):
    return re.sub(r'\s+', ' ', (s or '').strip().upper())


# ====================================================================================== KISS files


def read_kiss(path):
    """Parse one KISS file. Record layout (evidence in REPORT.md):
       KISS,<version>,<generator>
       H,<job number>,<job name>,,<MM/DD/YY>,<HH:MM>,F             export date and time
       D,<drawing>,<rev>,<main mark>,<piece mark>,<qty>,<shape>,<size>,<grade>,<length mm>,<finish>,<name>
            piece mark empty -> bolt line (shape MB/HS, name Field/Shop); qty = total over all assemblies of the mark
       A,<preliminary mark>       belongs to the D record above it, one per piece (qty records)
       S,<sequence>,<qty>         one per assembly of the mark
       L,Holes,<count>,<dia mm>,<thickness mm>,Round|Slotted / L,Weld,<count>,<length mm>,<size mm>,<type> /
       L,Cuts,<count>,0,0, / L,Camber,...  -> belong to the D record above them; counts are totals over its qty
       *                          block separator: one block per assembly mark"""
    raw = open(path, 'rb').read()
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        text = raw.decode('latin-1')
    kf = dict(path=path, file=os.path.basename(path), sha256=hashlib.sha256(raw).hexdigest(), generator='', job='',
              job_name='', exported=None, exported_raw='', blocks=[], problems=[])
    cur = last = None
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        f = next(csv.reader([line]))
        t = f[0].strip()
        if t == 'KISS':
            kf['generator'] = ','.join(f[1:]).strip()
        elif t == 'H':
            f += [''] * (7 - len(f))
            kf['job'], kf['job_name'] = f[1].strip(), f[2].strip()
            kf['exported_raw'] = (f[4].strip() + ' ' + f[5].strip()).strip()
            try:
                kf['exported'] = datetime.datetime.strptime(kf['exported_raw'], '%m/%d/%y %H:%M')
            except ValueError:
                kf['problems'].append(f'line {n}: H record date/time not MM/DD/YY HH:MM: {kf["exported_raw"]!r}')
        elif t == '*':
            cur = last = None
        elif t == 'D':
            if len(f) < 12:
                kf['problems'].append(f'line {n}: D record with {len(f)} fields')
                f += [''] * (12 - len(f))
            d = dict(dwg=f[1].strip(), rev=f[2].strip(), main=f[3].strip(), piece=f[4].strip(), qty=inum(f[5]),
                     shape=f[6].strip(), size=f[7].strip(), grade=f[8].strip(), length=fnum(f[9]), finish=f[10].strip(),
                     name=f[11].strip(), holes=[], welds=[], cuts=0, camber=[], other=[], prelim=[], line=n)
            if cur is None or d['main'] != cur['mark']:
                if cur is not None:
                    kf['problems'].append(f'line {n}: main mark {d["main"]} inside the block of {cur["mark"]} (new block)')
                cur = dict(mark=d['main'], dwg=d['dwg'], line=n, main=None, pieces=[], bolts=[], prelim=[], seq=[], revs=set())
                kf['blocks'].append(cur)
            cur['revs'].add(d['rev'])
            if d['piece'] == '':
                cur['bolts'].append(d)
            else:
                cur['pieces'].append(d)
                if d['piece'] == d['main'] and cur['main'] is None:
                    cur['main'] = d
            last = d
        elif t == 'A':
            if cur is None or last is None:
                kf['problems'].append(f'line {n}: A record outside a block')
            else:
                last['prelim'].append(f[1].strip() if len(f) > 1 else '')
        elif t == 'S':
            if cur is None:
                kf['problems'].append(f'line {n}: S record outside a block')
            else:
                cur['seq'].append((f[1].strip() if len(f) > 1 else '', inum(f[2]) if len(f) > 2 else None))
        elif t == 'L':
            if last is None:
                kf['problems'].append(f'line {n}: L record before any D record')
                continue
            f += [''] * (6 - len(f))
            k = f[1].strip()
            if k == 'Holes':
                last['holes'].append(dict(count=inum(f[2]) or 0, dia=fnum(f[3]), thk=fnum(f[4]), kind=f[5].strip()))
            elif k == 'Weld':
                last['welds'].append(dict(count=inum(f[2]) or 0, length=fnum(f[3]), size=fnum(f[4]), type=f[5].strip()))
            elif k == 'Cuts':
                last['cuts'] += inum(f[2]) or 0
            elif k == 'Camber':
                last['camber'].append(','.join(f[2:]).strip(','))
            else:
                last['other'].append(','.join(f))
        else:
            kf['problems'].append(f'line {n}: unknown record {t!r}')
    for b in kf['blocks']:
        b['rev'] = b['main']['rev'] if b['main'] else sorted(b['revs'])[-1]
        b['qty'] = b['main']['qty'] if b['main'] else None
        if b['main'] is None:
            kf['problems'].append(f'block {b["mark"]} (line {b["line"]}): no main piece line')
        b['prelim'] = list(b['main']['prelim']) if b['main'] else []
        for d in b['pieces'] + b['bolts']:
            if d['prelim'] and d['qty'] is not None and len(d['prelim']) != d['qty']:
                kf['problems'].append(f'block {b["mark"]} piece {d["piece"] or "(bolt)"}: {len(d["prelim"])} A records for quantity {d["qty"]}')
        if b['seq'] and b['qty'] is not None and sum(q or 0 for _, q in b['seq']) != b['qty']:
            kf['problems'].append(f'block {b["mark"]}: S quantities sum to {sum(q or 0 for _, q in b["seq"])} for quantity {b["qty"]}')
    return kf


def _ml(items, keyf, numf):
    """multiset helper: list of (key, numbers) sorted"""
    return sorted((keyf(x), numf(x)) for x in items)


def _nums_close(a, b, tol=NUM_TOL):
    return len(a) == len(b) and all((x is None and y is None) or close(x, y, tol) for x, y in zip(a, b))


def _match_multiset(A, B, tol=NUM_TOL):
    """A, B: lists of (key, (numbers...)). True if a one-to-one matching with equal keys and close numbers exists
    (greedy on sorted lists is exact here because the numbers of one key differ by far more than the tolerance)."""
    if len(A) != len(B):
        return False
    rest = list(B)
    for k, nums in A:
        for i, (k2, n2) in enumerate(rest):
            if k2 == k and _nums_close(nums, n2, tol):
                del rest[i]
                break
        else:
            return False
    return True


def piece_sig(d):
    return dict(qty=d['qty'], shape=d['shape'].upper(), size=norm_text(d['size']), grade=norm_grade(d['grade']),
                finish=norm_text(d['finish']), name=norm_text(d['name']), length=d['length'],
                holes=_ml(d['holes'], lambda h: (h['kind'].upper(), h['count']), lambda h: (h['dia'],)),
                welds=_ml(d['welds'], lambda w: (w['count'],), lambda w: (w['length'], w['size'])), cuts=d['cuts'],
                prelim=sorted(d['prelim']))


def block_diff(a, b):
    """human readable differences between two versions of one assembly block (numbers compared within NUM_TOL)"""
    out = []
    if a['qty'] != b['qty']:
        out.append(f'quantity {a["qty"]} -> {b["qty"]}')
    pa = {d['piece']: d for d in a['pieces']}
    pb = {d['piece']: d for d in b['pieces']}
    for k in sorted(set(pa) - set(pb)):
        out.append(f'piece {k} removed')
    for k in sorted(set(pb) - set(pa)):
        out.append(f'piece {k} added')
    for k in sorted(set(pa) & set(pb)):
        x, y = piece_sig(pa[k]), piece_sig(pb[k])
        for f in ('qty', 'shape', 'size', 'grade', 'finish', 'name', 'cuts', 'prelim'):
            if x[f] != y[f]:
                out.append(f'{k} {f} {x[f]} -> {y[f]}')
        if not close(x['length'], y['length'], NUM_TOL) and not (x['length'] is None and y['length'] is None):
            out.append(f'{k} length {fmt(x["length"])} -> {fmt(y["length"])}')
        if not _match_multiset(x['holes'], y['holes']):
            out.append(f'{k} holes {sum(h["count"] for h in pa[k]["holes"])} -> {sum(h["count"] for h in pb[k]["holes"])}'
                       + (' (sizes)' if sum(h["count"] for h in pa[k]["holes"]) == sum(h["count"] for h in pb[k]["holes"]) else ''))
        if not _match_multiset(x['welds'], y['welds']):
            out.append(f'{k} welds changed')
    ba = _ml(a['bolts'], lambda d: (d['shape'].upper(), norm_text(d['size']), norm_bolt_grade(d['grade']), d['name'].upper(), d['qty']), lambda d: (d['length'],))
    bb = _ml(b['bolts'], lambda d: (d['shape'].upper(), norm_text(d['size']), norm_bolt_grade(d['grade']), d['name'].upper(), d['qty']), lambda d: (d['length'],))
    if not _match_multiset(ba, bb):
        out.append('bolts changed')
    if sorted(a['seq']) != sorted(b['seq']):
        out.append('sequences changed')
    return out


def rev_text(b):
    return b['rev'] if b['rev'] != '' else '(blank)'


class KissSet:
    """all KISS files of one run, with the per-mark version selection"""

    def __init__(self, paths, asof=None):
        self.files = [read_kiss(p) for p in paths]
        # export time, then file name, then content hash: the order (and so the selection) does not depend on the
        # order or the folders the files are given in
        self.files.sort(key=lambda k: (k['exported'] or datetime.datetime.min, k['file'], k['sha256']))
        self.asof = asof
        self.versions = collections.defaultdict(list)      # (job, mark) -> [(kf, block)] oldest first
        for kf in self.files:
            for b in kf['blocks']:
                self.versions[(kf['job'], b['mark'])].append((kf, b))
        self.selected, self.excluded = {}, {}
        for key, vs in self.versions.items():
            use = [v for v in vs if asof is None or (v[0]['exported'] is not None and v[0]['exported'] <= asof)]
            if use:
                self.selected[key] = use[-1]
            else:
                self.excluded[key] = vs

    def history(self, key):
        """versions of one mark grouped by content: [(content group index, kf, block)] + change log"""
        vs = self.versions[key]
        groups, log = [], []
        for kf, b in vs:
            for gi, (rep_kf, rep_b) in enumerate(groups):
                if not block_diff(rep_b, b):
                    break
            else:
                gi = len(groups)
                groups.append((kf, b))
            log.append((gi, kf, b))
        changes = []
        prev = None
        for gi, kf, b in log:
            if prev is not None and prev[0] != gi:
                changes.append(dict(frm=f'{prev[1]["file"]} ({dts(prev[1]["exported"])}, rev {rev_text(prev[2])})',
                                    to=f'{kf["file"]} ({dts(kf["exported"])}, rev {rev_text(b)})',
                                    what=block_diff(prev[2], b)))
            prev = (gi, kf, b)
        return log, changes


# ====================================================================================== geometry (pure python)


def v_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def v_add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def v_mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def v_dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def v_cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def v_len(a):
    return math.sqrt(v_dot(a, a))


def v_unit(a):
    n = v_len(a)
    return (a[0] / n, a[1] / n, a[2] / n) if n > 0 else a


def arc_points(p0, pm, p1, n=24):
    """points along the three-point arc p0 -> pm -> p1, including the axis extremes inside the sweep"""
    (ax, ay), (bx, by), (cx, cy) = p0, pm, p1
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return [tuple(p0), tuple(pm), tuple(p1)]
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    r = math.hypot(ax - ux, ay - uy)
    a0, am, a1 = (math.atan2(y - uy, x - ux) for x, y in (p0, pm, p1))
    tw = 2 * math.pi
    s1, sm = (a1 - a0) % tw, (am - a0) % tw
    sweep = s1 if sm <= s1 else s1 - tw
    angs = [a0 + sweep * k / n for k in range(n + 1)]
    for q in range(-8, 9):                       # exact bounding box: axis extremes inside the sweep
        a = q * math.pi / 2
        t = (a - a0) / sweep if sweep else -1
        if 0 < t < 1:
            angs.append(a)
    angs.sort(key=lambda a: ((a - a0) / sweep) if sweep else 0)
    return [(ux + r * math.cos(a), uy + r * math.sin(a)) for a in angs]


def arc_radius(p0, pm, p1):
    (ax, ay), (bx, by), (cx, cy) = p0, pm, p1
    a, b, c = math.hypot(bx - cx, by - cy), math.hypot(ax - cx, ay - cy), math.hypot(ax - bx, ay - by)
    area2 = abs((bx - ax) * (cy - ay) - (cx - ax) * (by - ay))
    return a * b * c / (2 * area2) if area2 > 1e-12 else None


def loop_points(segs):
    pts = []
    for s in segs:
        p = [tuple(q) for q in s['p']]
        if s['t'] == 'L':
            pts += p
        else:
            pts += arc_points(p[0], p[1], p[2])
    out = []
    for p in pts:
        if not out or abs(p[0] - out[-1][0]) > 1e-9 or abs(p[1] - out[-1][1]) > 1e-9:
            out.append(p)
    return out


def section_loops(pr, outline):
    """section boundary as closed loops of (x, y) in profile coordinates (pos offset / rotation applied).
    Fillet radii are ignored (they never change an extent along the axis by more than the radius x the cut slope)."""
    k = pr.get('kind', '')
    g = lambda c: fnum(pr.get(c)) or 0.0
    loops = []
    if k == 'I':
        B, Dd, tw, tf = g('b'), g('d'), g('tw'), g('tf')
        x, y, w = B / 2, Dd / 2, tw / 2
        loops = [[(-x, -y), (x, -y), (x, -y + tf), (w, -y + tf), (w, y - tf), (x, y - tf), (x, y), (-x, y), (-x, y - tf),
                  (-w, y - tf), (-w, -y + tf), (-x, -y + tf)]]
    elif k == 'U':
        Dd, B, tw, tf = g('d'), g('b'), g('tw'), g('tf')
        x, y = B / 2, Dd / 2
        loops = [[(-x, -y), (x, -y), (x, -y + tf), (-x + tw, -y + tf), (-x + tw, y - tf), (x, y - tf), (x, y), (-x, y)]]
    elif k == 'L':
        Dd, B, t = g('d'), g('b'), g('t')
        x, y = B / 2, Dd / 2
        loops = [[(-x, -y), (x, -y), (x, -y + t), (-x + t, -y + t), (-x + t, y), (-x, y)]]
    elif k == 'RECT':
        B, Dd = g('b'), g('d')
        loops = [[(-B / 2, -Dd / 2), (B / 2, -Dd / 2), (B / 2, Dd / 2), (-B / 2, Dd / 2)]]
    elif k == 'RHS':
        B, Dd, t = g('b'), g('d'), g('t')
        loops = [[(-B / 2, -Dd / 2), (B / 2, -Dd / 2), (B / 2, Dd / 2), (-B / 2, Dd / 2)],
                 [(-B / 2 + t, -Dd / 2 + t), (B / 2 - t, -Dd / 2 + t), (B / 2 - t, Dd / 2 - t), (-B / 2 + t, Dd / 2 - t)]]
    elif k in ('CIRCLE', 'CHS'):
        R = g('radius')
        loops = [[(R * math.cos(2 * math.pi * i / 96), R * math.sin(2 * math.pi * i / 96)) for i in range(96)]]
    elif k == 'NGON':
        n, R, a0 = int(g('sides') or 0), g('radius'), 0.0
        if n >= 3:
            loops = [[(R * math.cos(a0 + 2 * math.pi * i / n), R * math.sin(a0 + 2 * math.pi * i / n)) for i in range(n)]]
    elif k == 'POLY' and outline:
        loops = [loop_points(outline['outer'])] + [loop_points(s) for s in outline.get('inner', [])]
    ang, px, py = g('pos_angle'), g('pos_x'), g('pos_y')
    if ang or px or py:
        c, s = math.cos(ang), math.sin(ang)
        loops = [[(c * x - s * y + px, s * x + c * y + py) for x, y in lp] for lp in loops]
    return [lp for lp in loops if lp]


def bbox2(loops):
    xs = [p[0] for lp in loops for p in lp]
    ys = [p[1] for lp in loops for p in lp]
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def section_area(pr, outline):
    """area of a profile (mm2, before the solid's scale) with its fillet / corner radii; POLY: polygon area"""
    k = pr.get('kind', '')
    g = lambda c: fnum(pr.get(c)) or 0.0
    q = 1.0 - math.pi / 4.0
    if k == 'I':
        return 2 * g('b') * g('tf') + (g('d') - 2 * g('tf')) * g('tw') + 4 * q * g('r') ** 2
    if k == 'U':
        return 2 * g('b') * g('tf') + (g('d') - 2 * g('tf')) * g('tw') + 2 * q * (g('r') ** 2 - g('r_edge') ** 2)
    if k == 'L':
        return g('t') * (g('d') + g('b') - g('t')) + q * (g('r') ** 2 - 2 * g('r_edge') ** 2)
    if k == 'RECT':
        return g('b') * g('d') - 4 * q * g('r_outer') ** 2
    if k == 'RHS':
        B, D, t = g('b'), g('d'), g('t')
        return B * D - (B - 2 * t) * (D - 2 * t) - 4 * q * (g('r_outer') ** 2 - g('r_inner') ** 2)
    if k == 'CIRCLE':
        return math.pi * g('radius') ** 2
    if k == 'CHS':
        return math.pi * (g('radius') ** 2 - (g('radius') - g('t')) ** 2)
    loops = section_loops(pr, outline)
    if not loops:
        return None
    a = [loop_area_perimeter(lp)[0] for lp in loops]
    return a[0] - sum(a[1:])


def solid_frame(s):
    O = tuple(fnum(s[k]) or 0.0 for k in ('ox', 'oy', 'oz'))
    X = v_unit(tuple(fnum(s[k]) or 0.0 for k in ('xx', 'xy', 'xz')))
    Z = v_unit(tuple(fnum(s[k]) or 0.0 for k in ('zx', 'zy', 'zz')))
    Y = v_cross(Z, X)
    V = tuple(fnum(s[k]) or 0.0 for k in ('vx', 'vy', 'vz'))
    sc = fnum(s.get('scale')) or 1.0
    return O, X, Y, V, sc


def _inv_columns(c0, c1, c2):
    """rows of the inverse of the 3x3 matrix whose columns are c0, c1, c2 (None if singular)"""
    det = v_dot(c0, v_cross(c1, c2))
    if abs(det) < 1e-12:
        return None
    return v_mul(v_cross(c1, c2), 1 / det), v_mul(v_cross(c2, c0), 1 / det), v_mul(v_cross(c0, c1), 1 / det)


def _inside(x, y, loops):
    """even-odd point in polygon (outer loop and hole loops together)"""
    ins = False
    for lp in loops:
        n = len(lp)
        for i in range(n):
            (x0, y0), (x1, y1) = lp[i], lp[(i + 1) % n]
            if (y0 > y) != (y1 > y) and x0 + (y - y0) * (x1 - x0) / (y1 - y0) > x:
                ins = not ins
    return ins


def tool_prism(s, loops):
    """an extruded tool solid as (origin, inverse frame rows, section loops scaled): a point X is inside when
    R (X - O) = (x, y, t) has 0 <= t <= 1 and (x, y) inside the loops"""
    O, X, Y, V, sc = solid_frame(s)
    R = _inv_columns(X, Y, V)
    if R is None:
        return None
    return O, R, [[(x * sc, y * sc) for x, y in lp] for lp in loops]


def _line_in_prism(P0, a, prism):
    """parameter intervals where the line P0 + t a runs inside a tool prism (exact for polygon sections)"""
    O, R, loops = prism
    inf = float('inf')
    c = [v_dot(r, v_sub(P0, O)) for r in R]
    d = [v_dot(r, a) for r in R]
    if abs(d[2]) < 1e-12:
        if not (-1e-9 <= c[2] <= 1 + 1e-9):
            return []
        s_lo, s_hi = -inf, inf
    else:
        t0, t1 = -c[2] / d[2], (1 - c[2]) / d[2]
        s_lo, s_hi = min(t0, t1), max(t0, t1)
    if abs(d[0]) < 1e-12 and abs(d[1]) < 1e-12:
        return [(s_lo, s_hi)] if _inside(c[0], c[1], loops) else []
    ts = []
    for lp in loops:
        for i in range(len(lp)):
            p, q = lp[i], lp[(i + 1) % len(lp)]
            ex, ey = q[0] - p[0], q[1] - p[1]
            den = d[0] * ey - d[1] * ex
            if abs(den) < 1e-15:
                continue
            wx, wy = p[0] - c[0], p[1] - c[1]
            lam = (wx * d[1] - wy * d[0]) / den
            if -1e-9 <= lam <= 1 + 1e-9:
                ts.append((wx * ey - wy * ex) / den)
    ts.sort()
    cuts = [-inf] + ts + [inf]
    out = []
    for lo, hi in zip(cuts, cuts[1:]):
        if hi - lo < 1e-12:
            continue
        mid = (lo + hi) / 2 if lo > -inf and hi < inf else ((hi - 1) if lo == -inf else (lo + 1)) if (lo, hi) != (-inf, inf) else 0.0
        if _inside(c[0] + mid * d[0], c[1] + mid * d[1], loops):
            lo2, hi2 = max(lo, s_lo), min(hi, s_hi)
            if hi2 > lo2:
                out.append((lo2, hi2))
    return out


def axial_extent(s, loops, planes, prisms=()):
    """extent along the extrusion direction of (section prism) clipped by half-spaces [(point, normal keep side)] and
    minus tool prisms (openings that are not holes, e.g. the jaws of a clevis or a notch through a whole end).
    Without tools the extreme of a min / max of affine functions over the section is attained on the section
    boundary: at a vertex or where two bounding planes (or a plane and an end face) cross an edge; both are evaluated.
    With tools the lines through boundary points, through 24 points on every boundary edge and through a 13 x 13 grid
    inside the section are evaluated, each line minus the exact intervals where it runs inside a tool (a sampled
    extreme: it can fall short of the true extreme by the variation of the tool face between two samples)."""
    O, X, Y, V, sc = solid_frame(s)
    L = v_len(V)
    if L <= 0:
        return None
    a = v_mul(V, 1.0 / L)
    W = lambda q: v_add(O, v_add(v_mul(X, q[0] * sc), v_mul(Y, q[1] * sc)))

    def bounds(P0):
        lo, hi = 0.0, L
        for p, n in planes:
            c, k = v_dot(n, v_sub(P0, p)), v_dot(n, a)
            if abs(k) < 1e-12:
                if c < -1e-6:
                    return None
            elif k > 0:
                lo = max(lo, -c / k)
            else:
                hi = min(hi, -c / k)
        return (lo, hi) if hi >= lo - 1e-9 else None

    cand = []
    for lp in loops:
        cand += lp
        if planes:
            for i in range(len(lp)):
                qa, qb = lp[i], lp[(i + 1) % len(lp)]
                Pa, Pb = W(qa), W(qb)
                fs = [(0.0, 0.0)]                                    # bound functions along the edge: t = u + s*w
                for p, n in planes:
                    k = v_dot(n, a)
                    if abs(k) < 1e-12:
                        continue
                    ca, cb = v_dot(n, v_sub(Pa, p)), v_dot(n, v_sub(Pb, p))
                    fs.append((-ca / k, -(cb - ca) / k))
                fs.append((L, 0.0))
                for x in range(len(fs)):
                    for y in range(x + 1, len(fs)):
                        dw = fs[x][1] - fs[y][1]
                        if abs(dw) > 1e-12:
                            t = (fs[y][0] - fs[x][0]) / dw
                            if 0.0 < t < 1.0:
                                cand.append((qa[0] + t * (qb[0] - qa[0]), qa[1] + t * (qb[1] - qa[1])))
    if prisms:
        for lp in loops:
            for i in range(len(lp)):
                qa, qb = lp[i], lp[(i + 1) % len(lp)]
                cand += [(qa[0] + (qb[0] - qa[0]) * k / 25.0, qa[1] + (qb[1] - qa[1]) * k / 25.0) for k in range(1, 25)]
        # lines exactly on the body surface are degenerate against tool faces lying in that surface: every boundary
        # point is moved 0.01 mm inwards (first of 8 directions that lands strictly inside, i.e. its 4 neighbours at
        # 0.004 mm are inside too); material counts only where it is thicker than 0.01 mm along the line
        def strictly_inside(x, y):
            return all(_inside(x + ex, y + ey, loops) for ex, ey in ((0, 0), (0.004, 0), (-0.004, 0), (0, 0.004), (0, -0.004)))
        inner = []
        for q in cand:
            for dx, dy in ((0.7071, 0.7071), (-0.7071, 0.7071), (0.7071, -0.7071), (-0.7071, -0.7071), (1, 0), (-1, 0), (0, 1), (0, -1)):
                if strictly_inside(q[0] + 0.01 * dx, q[1] + 0.01 * dy):
                    inner.append((q[0] + 0.01 * dx, q[1] + 0.01 * dy))
                    break
        cand = inner
        bb = bbox2(loops)
        if bb:
            for i in range(13):
                for j in range(13):
                    q = (bb[0] + (bb[2] - bb[0]) * (i + 0.5) / 13, bb[1] + (bb[3] - bb[1]) * (j + 0.5) / 13)
                    if _inside(q[0], q[1], loops):
                        cand.append(q)
    umin = umax = None
    for q in cand:
        P0 = W(q)
        bd = bounds(P0)
        if bd is None:
            continue
        pieces = [bd]
        for pr in prisms:
            for t0, t1 in _line_in_prism(P0, a, pr):
                nxt = []
                for lo, hi in pieces:
                    if t1 <= lo or t0 >= hi:
                        nxt.append((lo, hi))
                        continue
                    if t0 > lo:
                        nxt.append((lo, t0))
                    if t1 < hi:
                        nxt.append((t1, hi))
                pieces = [x for x in nxt if x[1] - x[0] > 0.01]
            if not pieces:
                break
        if not pieces:
            continue
        u0 = v_dot(v_sub(P0, O), a)
        lo, hi = u0 + min(x[0] for x in pieces), u0 + max(x[1] for x in pieces)
        umin = lo if umin is None else min(umin, lo)
        umax = hi if umax is None else max(umax, hi)
    return None if umin is None else umax - umin


def convex_hull(pts):
    """monotone chain convex hull of 2-D points (counter-clockwise, no repeated points)"""
    P = sorted(set((round(x, 9), round(y, 9)) for x, y in pts))
    if len(P) < 3:
        return P
    cr = lambda o, a, b: (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, up = [], []
    for q in P:
        while len(lo) >= 2 and cr(lo[-2], lo[-1], q) <= 0:
            lo.pop()
        lo.append(q)
    for q in reversed(P):
        while len(up) >= 2 and cr(up[-2], up[-1], q) <= 0:
            up.pop()
        up.append(q)
    return lo[:-1] + up[:-1]


def min_area_rect(pts):
    """minimum-area enclosing rectangle of 2-D points (rotating calipers over the hull edges) -> (short, long)"""
    h = convex_hull(pts)
    if len(h) < 3:
        return None
    best = None
    for i in range(len(h)):
        a, b = h[i], h[(i + 1) % len(h)]
        ang = math.atan2(b[1] - a[1], b[0] - a[0])
        c, s_ = math.cos(ang), math.sin(ang)
        us = [c * x + s_ * y for x, y in h]
        vs = [-s_ * x + c * y for x, y in h]
        w, l = max(us) - min(us), max(vs) - min(vs)
        if best is None or w * l < best[0] - 1e-9:
            best = (w * l, min(w, l), max(w, l))
    return best[1], best[2]


def loop_area_perimeter(lp):
    a = per = 0.0
    for i in range(len(lp)):
        (x0, y0), (x1, y1) = lp[i], lp[(i + 1) % len(lp)]
        a += x0 * y1 - x1 * y0
        per += math.hypot(x1 - x0, y1 - y0)
    return abs(a) / 2.0, per


def strip_dims(loops):
    """read a closed section as a strip of constant thickness (bent or flat plate seen end-on): with area A and
    perimeter P, P = 2 w + 2 t and A = w t (exact for straight legs and for concentric bends) -> (t, w)"""
    if len(loops) != 1:
        return None
    A, P = loop_area_perimeter(loops[0])
    disc = P * P - 16.0 * A
    if A <= 0 or disc < 0:
        return None
    t = (P - math.sqrt(disc)) / 4.0
    return (t, A / t) if t > 0 else None


def newell_normal(lp):
    n = [0.0, 0.0, 0.0]
    m = len(lp)
    for i in range(m):
        a, b = lp[i], lp[(i + 1) % m]
        n[0] += (a[1] - b[1]) * (a[2] + b[2])
        n[1] += (a[2] - b[2]) * (a[0] + b[0])
        n[2] += (a[0] - b[0]) * (a[1] + b[1])
    return tuple(n)


def _exact_faces(rec):
    """[(area, unit normal)] and the vertex set of a part given as exact faces"""
    faces, pts = [], set()
    for so in rec.get('solids', []):
        for fc in so.get('faces', []):
            if not fc or len(fc[0]) < 3:
                continue
            n = newell_normal(fc[0])
            for h in fc[1:]:
                if len(h) >= 3:
                    n = v_add(n, newell_normal(h))      # hole loops run against the outer loop: their area subtracts
            a = v_len(n) / 2.0
            if a > 0:
                faces.append((a, v_mul(n, 1.0 / (2 * a))))
            for lp in fc:
                pts.update(tuple(q) for q in lp)
    faces.sort(key=lambda x: -x[0])
    return faces, sorted(pts)


def exact_axis(faces):
    """extrusion axis of a part given as exact faces: the direction the largest face area is parallel to; candidates are
    the crossings of the 8 largest face normals and the 4 largest normals (the rule tools/recover.py uses for the axis
    of a faceted part); ties: first candidate"""
    top = faces[:8]
    cands = []
    for i in range(len(top)):
        for j in range(i + 1, len(top)):
            c = v_cross(top[i][1], top[j][1])
            if v_len(c) > 0.05:
                cands.append(v_unit(c))
    cands += [f[1] for f in faces[:4]]
    best, bscore = None, None
    for a in cands:
        lat = sum(ar for ar, n in faces if abs(v_dot(n, a)) < 0.02)
        if bscore is None or lat > bscore + 1e-9:
            best, bscore = a, lat
    return best


def exact_axis_extent(rec):
    """length of a part given as exact faces: extent of its vertices along its extrusion axis"""
    faces, pts = _exact_faces(rec)
    if not faces or not pts:
        return None
    a = exact_axis(faces)
    us = [v_dot(p, a) for p in pts]
    return max(us) - min(us)


def exact_shape_facts(rec):
    """facts of a part given as exact faces: length along its extrusion axis, the smallest vertex-ring radius about that
    axis (the shank of a faceted round part: a faceted circle keeps its vertices on the circle), the number of inner face
    loops (a loop inside a face = a hole or a recess) and of voids"""
    faces, pts = _exact_faces(rec)
    inner = sum(max(0, len(fc) - 1) for so in rec.get('solids', []) for fc in so.get('faces', []))
    voids = sum(len(so.get('voids', []) or []) for so in rec.get('solids', []))
    out = dict(length=None, inner_loops=inner, voids=voids, min_radius=None)
    if not faces or not pts:
        return out
    a = exact_axis(faces)
    us = [v_dot(p, a) for p in pts]
    out['length'] = max(us) - min(us)
    c = tuple(sum(p[i] for p in pts) / len(pts) for i in range(3))
    rad = []
    for p in pts:
        d = v_sub(p, c)
        r = v_len(v_sub(d, v_mul(a, v_dot(d, a))))
        if r > 0.5:                                   # vertices on the axis (cap centres) are no ring
            rad.append(r)
    out['min_radius'] = min(rad) if rad else None
    return out


# ====================================================================================== model (schedules)


def read_csv(path):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return []
    with open(path, newline='', encoding='utf-8') as fh:
        return list(csv.DictReader(fh))


def first(d, *keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, ''):
            return v
    return None


P_NAME = ('AISC_EM11_Pset_PieceIdentification.PieceMark', 'Tekla Common.Name')
P_GRADE = ('AISC_EM11_Pset_Material.MaterialGrade', 'Tekla Common.Grade')
P_PRELIM = ('AISC_EM11_Pset_PieceIdentification.PrelimMark', 'Tekla Common.Preliminary mark')
P_PHASE = ('Tekla Common.Phase',)
P_FINISH = ('Tekla Common.Finish',)
P_MAIN = ('AISC_EM11_Pset_PieceIdentification.MainPieceTag',)
B_STD = ('AISC_EM11_Pset_Bolt.BoltStandard', 'Tekla Fastener.Bolt standard', 'Tekla Bolt.Bolt standard',
         'AISC_EM11_Pset_Bolt.BoltGrade')
B_SIZE = ('AISC_EM11_Pset_Bolt.BoltDiameter', 'Tekla Fastener.Bolt size', 'Tekla Bolt.Bolt size')
B_LEN = ('AISC_EM11_Pset_Bolt.BoltLength', 'Tekla Fastener.Bolt length', 'Tekla Bolt.Bolt length')
B_FIELD = ('AISC_EM11_Pset_Bolt.BoltFieldAssembled',)
B_LOC = ('Tekla Fastener.Location', 'Tekla Bolt.Location')
W_LEN = ('AISC_EM11_Pset_Weld.l',)
W_SIZE = ('AISC_EM11_Pset_Weld.d',)


class Model:
    def __init__(self, folder):
        F = lambda n: os.path.join(folder, n)
        self.folder = folder
        self.parts = read_csv(F('parts.csv'))
        if not self.parts:
            raise SystemExit(f'{folder}: parts.csv missing or empty')
        self.byid = {p['part_id']: p for p in self.parts}
        self.profiles = {r['profile_id']: r for r in read_csv(F('profiles.csv'))}
        self.outlines = json.load(open(F('profile_outlines.json'))) if os.path.exists(F('profile_outlines.json')) else {}
        self.solids = {r['solid_id']: r for r in read_csv(F('solids.csv'))}
        # swept solids (paths.json): their length is the length along the path, not the first segment's vector
        self.paths = json.load(open(F('paths.json'))) if os.path.exists(F('paths.json')) else {}
        self.body = collections.defaultdict(list)
        for s in self.solids.values():
            if s['role'] == 'body':
                self.body[s['part_id']].append(s)
        self.cuts = collections.defaultdict(list)
        for c in read_csv(F('cuts.csv')):
            self.cuts[c['solid_id']].append(c)
        self.openings = collections.defaultdict(list)
        for o in read_csv(F('openings.csv')):
            self.openings[o['part_id']].append(o)
        self.volume, self.vstatus = {}, {}
        for r in read_csv(F('verification.csv')):
            v = fnum(r.get('volume'))
            if v is not None:
                self.volume[r['part_id']] = v
            if r.get('status'):
                self.vstatus[r['part_id']] = r['status']
        self.props, self.asm_props = {}, {}
        if os.path.exists(F('part_properties.jsonl')):
            for line in open(F('part_properties.jsonl'), encoding='utf-8'):
                if line.strip():
                    r = json.loads(line)
                    if r.get('ifc_class') == 'IfcElementAssembly':
                        self.asm_props[r['part_id']] = r
                    else:
                        self.props[r['part_id']] = r
        self.exact_path = F('exact_geometry.jsonl')
        self._exact = None
        self.info = json.load(open(F('extract_info.json'))) if os.path.exists(F('extract_info.json')) else {}
        # assemblies of the rebuilt model: assembly_id -> parts (parts.csv only: what is built)
        self.asm = collections.defaultdict(list)
        self.asm_mark = {}
        for p in sorted(self.parts, key=lambda p: p['part_id']):
            if p['assembly_id']:
                self.asm[p['assembly_id']].append(p)
                if p['assembly_mark']:
                    self.asm_mark.setdefault(p['assembly_id'], p['assembly_mark'])
        self.by_mark = collections.defaultdict(list)          # assembly mark -> [assembly_id]
        for aid in sorted(self.asm):
            if self.asm_mark.get(aid):
                self.by_mark[self.asm_mark[aid]].append(aid)
        self.piece_index = collections.defaultdict(set)      # part mark -> assembly marks it occurs in
        for p in self.parts:
            if p['part_mark']:
                self.piece_index[p['part_mark']].add(p['assembly_mark'])
        self.main_of = {aid: self._main(aid) for aid in self.asm}
        self.prelim_groups = collections.defaultdict(list)    # preliminary mark of the main piece -> [assembly_id]
        for aid in sorted(self.asm):
            m = self.main_of[aid]
            pm = self.prop(m, P_PRELIM) if m else None
            if pm:
                self.prelim_groups[str(pm)].append(aid)
        keys = set()
        for r in self.props.values():
            keys.update((r.get('properties') or {}).keys())
        self.has = dict(prelim=bool(keys & set(P_PRELIM)), phase=bool(keys & set(P_PHASE)),
                        finish=bool(keys & set(P_FINISH)), name=bool(keys & set(P_NAME)))
        self._facts = {}

    # ---------------------------------------------------------------- properties
    def prop(self, p, keys):
        r = self.props.get(p['part_id'] if isinstance(p, dict) else p)
        if not r:
            return None
        return first(r.get('properties') or {}, *keys)

    def _main(self, aid):
        ps = [p for p in self.asm[aid] if p['role'] not in ('weld', 'bolt')]
        tagged = [p for p in ps if self.prop(p, P_MAIN) is True]
        if len(tagged) == 1:
            return tagged[0]
        mk = self.asm_mark.get(aid)
        same = [p for p in ps if mk and p['part_mark'] == mk]
        if len(same) == 1:
            return same[0]
        return None

    def exact(self, pid):
        if self._exact is None:
            self._exact = {}
            if os.path.exists(self.exact_path):
                want = {p['part_id'] for p in self.parts if p['geometry'] == 'exact'}
                rx = re.compile(r'"part_id"\s*:\s*"([^"]+)"')
                for line in open(self.exact_path, encoding='utf-8'):
                    m = rx.search(line[:200])
                    if m and m.group(1) in want:
                        self._exact[m.group(1)] = json.loads(line)
        return self._exact.get(pid)

    def solid_len(self, s):
        """length of a solids.csv row: along its path when swept (paths.json), else its extrusion vector"""
        pa = self.paths.get(s['solid_id'])
        if pa:
            pp = pa['points'] + (pa['points'][:1] if pa.get('closed') else [])
            return sum(math.dist(a, b) for a, b in zip(pp, pp[1:]))
        return v_len(tuple(fnum(s[k]) or 0.0 for k in ('vx', 'vy', 'vz')))

    # ---------------------------------------------------------------- per part facts
    def facts(self, p):
        pid = p['part_id']
        if pid in self._facts:
            return self._facts[pid]
        f = dict(part_id=pid, mark=p['part_mark'], role=p['role'], geometry=p['geometry'],
                 name=str(self.prop(p, P_NAME) or ''), grade=norm_grade(self.prop(p, P_GRADE) or p['material']),
                 designation=p['designation'], desig_src='parts.csv designation' if p['designation'] else '',
                 section=None, section_area=None, length=None, length_src='', plate=None, holes=None, holes_src='',
                 volume=self.volume.get(pid))
        b = sorted(self.body.get(pid, []), key=lambda s: int(re.sub(r'\D', '', s['solid_id']) or 0))
        if b:
            s = max(b, key=self.solid_len)
            pr = self.profiles.get(s['profile_id'], {})
            if not f['designation'] and pr.get('designation'):
                f['designation'], f['desig_src'] = pr['designation'], 'profiles.csv designation of the body section'
            loops = section_loops(pr, self.outlines.get(s['profile_id']))
            O, X, Y, V, sc = solid_frame(s)
            L = v_len(V)
            planes = [((fnum(c['px']) or 0.0, fnum(c['py']) or 0.0, fnum(c['pz']) or 0.0),
                       (fnum(c['nx']) or 0.0, fnum(c['ny']) or 0.0, fnum(c['nz']) or 0.0))
                      for c in self.cuts.get(s['solid_id'], []) if c['kind'] == 'plane']
            prisms = []
            for t in self._tools(pid, s):
                tp = self.profiles.get(t['profile_id'], {})
                if self._hole_shape(tp, self.outlines.get(t['profile_id']), fnum(t.get('scale')) or 1.0):
                    continue                                         # a hole never removes a whole end
                tl = section_loops(tp, self.outlines.get(t['profile_id']))
                pz = tool_prism(t, tl) if tl else None
                if pz:
                    prisms.append(pz)
            bounded = sum(1 for c in self.cuts.get(s['solid_id'], []) if c['kind'] == 'bounded_plane')
            ext = axial_extent(s, loops, planes, prisms) if loops else None
            if s['solid_id'] in self.paths:
                L, ext = self.solid_len(s), None          # swept: the developed length along the path
            f['extrusion'] = L
            f['length'] = ext if ext is not None else L
            f['length_src'] = 'swept solid: length along its path (paths.json)' if s['solid_id'] in self.paths else 'rebuilt solid: extent along the extrusion axis' + (
                f' after {len(planes)} plane cut(s)' if planes else '') + (
                f', minus {len(prisms)} opening / cut tool(s)' if prisms else '') + (
                f' ({bounded} bounded-plane cut(s) not applied to the length)' if bounded else '')
            k = pr.get('kind', '')
            g = lambda c: (fnum(pr.get(c)) or 0.0) * sc
            sec = dict(kind=k)
            if k == 'L':
                sec.update(d=g('d'), b=g('b'), t=g('t') * 1.0)
            elif k == 'RECT':
                sec.update(d=g('d'), b=g('b'))
            elif k == 'RHS':
                sec.update(d=g('d'), b=g('b'), t=g('t'))
            elif k in ('CIRCLE', 'CHS'):
                sec.update(dia=2 * g('radius'), t=g('t') if k == 'CHS' else None)
            elif k == 'I':
                sec.update(d=g('d'), b=g('b'), tw=g('tw'), tf=g('tf'))
            elif k == 'NGON':
                sec.update(dia=2 * g('radius'))
            elif k == 'POLY':
                bb = bbox2(loops)
                if bb:
                    sec.update(bx=(bb[2] - bb[0]) * sc, by=(bb[3] - bb[1]) * sc)
            f['section'] = sec
            ar = section_area(pr, self.outlines.get(s['profile_id']))
            f['section_area'] = ar * sc * sc if ar else None
            # plate readings of the rebuilt solid: (thickness, two plan dimensions, how). A KISS PL piece is compared with
            # the reading whose thickness fits (see Checker.plate_fit).
            opts = []
            if k == 'RECT':
                t, w = sorted((sec['d'], sec['b']))
                opts.append((t, w, f['length'], 'RECT section (thickness x width) x extrusion length'))
            elif k == 'POLY' and loops:
                mar = min_area_rect([(x * sc, y * sc) for lp in loops for x, y in lp])
                if mar:
                    opts.append((L, mar[0], mar[1], 'outline = plate plan (minimum-area rectangle), extrusion = thickness'))
                st = strip_dims([[(x * sc, y * sc) for x, y in lp] for lp in loops])
                if st:
                    opts.append((st[0], st[1], f['length'], 'section = plate seen end-on (strip: area / perimeter), extrusion = length'))
            f['plate'] = opts or None
            f['holes'], f['holes_src'] = self._holes(pid, s), 'opening / cut tool solids of the rebuilt part'
        elif p['geometry'] == 'exact':
            rec = self.exact(pid)
            if rec:
                ef = exact_shape_facts(rec)
                if ef['length']:
                    f['length'] = ef['length']
                    f['length_src'] = 'exact faces: extent along the extrusion axis (direction of the largest face area)'
                f['section'] = dict(kind='EXACT', min_dia=2 * ef['min_radius'] if ef['min_radius'] else None)
                if ef['inner_loops'] == 0 and ef['voids'] == 0:
                    f['holes'], f['holes_src'] = [], 'exact faces without any inner loop (no hole possible)'
        self._facts[pid] = f
        return f

    def _tools(self, pid, body_solid):
        """subtractive tool solids of a part: its opening tools and the solid cut tools of its body solid"""
        tools = []
        for o in self.openings.get(pid, []):
            tools += [self.solids[t] for t in (o['tool_solids'] or '').split() if t in self.solids]
        for c in self.cuts.get(body_solid['solid_id'], []):
            if c['kind'] == 'solid' and c['tool_solid_id'] in self.solids:
                tools.append(self.solids[c['tool_solid_id']])
        return tools

    def _holes(self, pid, body_solid):
        """[(kind, diameter mm)] from the part's opening tools and solid cut tools; non-round openings are not holes"""
        out = []
        for t in self._tools(pid, body_solid):
            h = self._hole_shape(self.profiles.get(t['profile_id'], {}), self.outlines.get(t['profile_id']),
                                 fnum(t.get('scale')) or 1.0)
            if h:
                out.append(h)
        ol = self.outlines.get(body_solid['profile_id'])
        pr = self.profiles.get(body_solid['profile_id'], {})
        if pr.get('kind') == 'POLY' and ol:
            for inner in ol.get('inner', []):
                h = self._loop_hole(inner)
                if h:
                    out.append(h)
        return sorted(out)

    def _hole_shape(self, pr, outline, sc):
        k = pr.get('kind')
        if k == 'CIRCLE':
            return ('Round', 2 * (fnum(pr.get('radius')) or 0.0) * sc)
        if k == 'NGON' and not fnum(pr.get('radius_inner')):
            # a regular polygon on a circle of `radius`: a round hole as the faceted source stores it (recovered cut tools)
            return ('Round', 2 * (fnum(pr.get('radius')) or 0.0) * sc)
        if k == 'RECT':
            d, b, ro = fnum(pr.get('d')) or 0.0, fnum(pr.get('b')) or 0.0, fnum(pr.get('r_outer')) or 0.0
            if ro and abs(2 * ro - min(d, b)) < 1e-3:
                return ('Slotted' if abs(d - b) > 1e-3 else 'Round', min(d, b) * sc)
            return None
        if k == 'POLY' and outline:
            h = self._loop_hole(outline['outer'])
            if h:
                return (h[0], h[1] * sc)
        return None

    @staticmethod
    def _loop_hole(segs):
        """a loop made of arcs (circle) or of two half-circle arcs joined by two straight lines (slot)"""
        arcs = [s for s in segs if s['t'] == 'A']
        lines = []
        for s in segs:
            if s['t'] == 'L':
                p = s['p']
                # exporters close slots with 0.001 mm connector segments; those are not edges of the shape
                lines += [(p[i], p[i + 1]) for i in range(len(p) - 1) if math.hypot(p[i + 1][0] - p[i][0], p[i + 1][1] - p[i][1]) > 0.01]
        if not arcs:
            return None
        rs = [arc_radius(*a['p']) for a in arcs]
        if any(r is None for r in rs) or max(rs) - min(rs) > 1e-3:
            return None
        if not lines:
            return ('Round', 2 * rs[0])
        if len(arcs) == 2 and len(lines) == 2:
            # two half circles of one radius joined by two straight edges
            chords = [math.hypot(a['p'][2][0] - a['p'][0][0], a['p'][2][1] - a['p'][0][1]) for a in arcs]
            if all(abs(c - 2 * rs[0]) < 0.01 for c in chords):
                return ('Slotted', 2 * rs[0])
        return None

    # ---------------------------------------------------------------- bolts and welds
    def bolt_groups(self, p):
        """[(diameter, length, grade, field, count, source)] for one bolt part"""
        b = self.body.get(p['part_id'], [])
        circ = []
        for s in b:
            pr = self.profiles.get(s['profile_id'], {})
            if pr.get('kind') == 'CIRCLE':
                L = v_len(tuple(fnum(s[k]) or 0.0 for k in ('vx', 'vy', 'vz')))
                circ.append((2 * (fnum(pr.get('radius')) or 0.0) * (fnum(s.get('scale')) or 1.0), L))
        grade = norm_bolt_grade(str(self.prop(p, B_STD) or ''))
        fld = self.prop(p, B_FIELD)
        if fld is None:
            loc = str(self.prop(p, B_LOC) or '').lower()
            fld = True if loc in ('site', 'field') else False if loc in ('workshop', 'shop') else None
        field = 'Field' if fld is True else 'Shop' if fld is False else ''
        if not circ:
            return [(fnum(self.prop(p, B_SIZE)), fnum(self.prop(p, B_LEN)), grade, field, None,
                     'bolt property set (no shank solids: count unknown)')]
        Lmax = max(L for _, L in circ)
        shanks = [(d, L) for d, L in circ if abs(L - Lmax) < 0.01]
        dia = max(d for d, _ in shanks)
        shanks = [x for x in shanks if abs(x[0] - dia) < 0.01]
        return [(dia, Lmax, grade, field, len(shanks), 'shank solids of the rebuilt bolt group')]

    def weld_items(self, p):
        """[(bead length, attribute length, size, source)] one per weld bead of one weld part. Bead length: extrusion
        length of each bead solid of the rebuilt part (exact welds: extent of each solid along its axis); attribute
        length and size: the weld property set (l, d; rounded to 0.1 mm by the exporter)."""
        size, attr = fnum(self.prop(p, W_SIZE)), fnum(self.prop(p, W_LEN))
        out = []
        for s in sorted(self.body.get(p['part_id'], []), key=lambda s: s['solid_id']):
            out.append((self.solid_len(s), attr, size, 'weld bead solids of the rebuilt part'))
        if not out and p['geometry'] == 'exact':
            rec = self.exact(p['part_id'])
            for so in (rec or {}).get('solids', []):
                L = exact_axis_extent(dict(solids=[so]))
                if L is not None and L > 0.01:        # a solid without extent along its own axis is no bead
                    out.append((L, attr, size, 'solids of the exact weld (extent along its axis)'))
        return out

    def weight(self, aid):
        """rebuilt weight of one assembly (kg): sum of rebuilt part volumes x 7850 kg/m3, bolts and welds excluded"""
        tot, missing = 0.0, 0
        for p in self.asm[aid]:
            if p['role'] in ('bolt', 'weld'):
                continue
            v = self.volume.get(p['part_id'])
            if v is None:
                missing += 1
            else:
                tot += v * STEEL_DENSITY
        return tot, missing


# ====================================================================================== comparison


def plate_fit(f, tk, wk, lk):
    """the reading of a rebuilt part as a plate t x w x l that best fits the KISS plate (tk, wk, lk): every plate
    reading (Model.facts) with both assignments of its plan dimensions to width / length; the largest of the three
    errors, each relative to its tolerance, is minimised -> (t, w, l, how)"""
    best = None
    for t, a, b, how in f['plate'] or []:
        for w, l in ((a, b), (b, a)):
            err = max(abs(t - tk) / DIM_TOL, abs(w - wk) / PLATE_W_TOL,
                      abs(l - lk) / LENGTH_TOL if (l is not None and lk is not None) else 0.0)
            if best is None or err < best[0] - 1e-12:
                best = (err, t, w, l, how)
    return best[1:] if best else (None, None, None, '')


class Checker:
    COLS = ['check', 'assembly_mark', 'item', 'kiss', 'model', 'status', 'reason', 'model_source', 'n_model_parts',
            'model_verification', 'kiss_file', 'kiss_exported', 'kiss_after_model', 'kiss_rev', 'kiss_line',
            'kiss_versions', 'other_versions_agreeing', 'job']

    def __init__(self, model, kset, model_date=None, length_tol=LENGTH_TOL):
        self.M, self.K = model, kset
        self.model_date = model_date
        self.length_tol = length_tol
        self.rows = []
        self._vparts = None          # model parts behind the rows being written (for the verification column)

    def vtext(self):
        """verify.py status of the model parts behind a row (verification.csv), e.g. 'match' or 'MISMATCH 2, match 2'"""
        if not self._vparts:
            return ''
        c = collections.Counter(self.M.vstatus.get(p['part_id'], 'not verified') for p in self._vparts)
        return next(iter(c)) if len(c) == 1 else ', '.join(f'{k} {v}' for k, v in sorted(c.items()))

    def row(self, check, mark, item, kiss, model, status, reason='', src='', n=None, ver=None, others=''):
        kf, b = ver if ver else (None, None)
        self.rows.append(dict(check=check, assembly_mark=mark, item=item, kiss=kiss, model=model, status=status,
                              reason=reason, model_source=src, n_model_parts='' if n is None else n,
                              model_verification=self.vtext(),
                              kiss_file=kf['file'] if kf else '', kiss_exported=dts(kf['exported']) if kf else '',
                              kiss_after_model=('' if not (kf and self.model_date and kf['exported']) else
                                                ('yes' if kf['exported'] > self.model_date else 'no')),
                              kiss_rev=rev_text(b) if b else '', kiss_line=(b['line'] if b else ''),
                              kiss_versions=len(self.K.versions[(kf['job'], b['mark'])]) if kf else '',
                              other_versions_agreeing=others, job=kf['job'] if kf else ''))

    # ---------------------------------------------------------------- helpers
    def others_agreeing(self, key, ver, test):
        """files of the other KISS versions of this mark for which test(block) is True"""
        out = []
        for kf, b in self.K.versions[key]:
            if b is ver[1]:
                continue
            try:
                ok = test(b)
            except Exception:
                ok = False
            if ok:
                out.append(f'{kf["file"]} ({dts(kf["exported"])}, rev {rev_text(b)})')
        return '; '.join(out)

    def piece_parts(self, aids, piece):
        return [p for aid in aids for p in self.M.asm[aid] if p['part_mark'] == piece and p['role'] not in ('bolt', 'weld')]

    # ---------------------------------------------------------------- run
    def run(self):
        M, K = self.M, self.K
        for key in sorted(K.selected, key=lambda k: (k[0], k[1])):
            ver = K.selected[key]
            kf, b = ver
            mark = b['mark']
            aids = M.by_mark.get(mark, [])
            if aids:
                self.row('presence', mark, '', f'qty {b["qty"]}', f'{len(aids)} assemblies', 'agree',
                         src='parts.csv assembly_mark', n=sum(len(M.asm[a]) for a in aids), ver=ver)
                self.assembly(key, ver, aids)
            elif mark in M.prelim_groups:
                self.prelim(key, ver, M.prelim_groups[mark])
            else:
                hint = ''
                if b['main'] and b['main']['piece'] in M.piece_index:
                    hint = '; the main piece mark occurs in model assemblies ' + ', '.join(sorted(M.piece_index[b['main']['piece']]))
                self.row('presence', mark, '', f'qty {b["qty"]}', 'absent', 'DISAGREE',
                         'assembly mark not in the model' + ('' if M.by_mark else ' (the model carries no assembly marks)') + hint,
                         src='parts.csv assembly_mark', n=0, ver=ver)
        kiss_marks = {k[1] for k in K.versions}
        for mark in sorted(M.by_mark):
            if mark not in kiss_marks:
                n = len(M.by_mark[mark])
                self.row('model_coverage', mark, '', '', f'{n} assemblies', 'model_only',
                         'assembly mark of the model in no KISS file', src='parts.csv assembly_mark',
                         n=sum(len(M.asm[a]) for a in M.by_mark[mark]))
        return self.rows

    # ---------------------------------------------------------------- one assembly mark
    def assembly(self, key, ver, aids):
        M = self.M
        kf, b = ver
        mark = b['mark']
        n = len(aids)
        st = 'agree' if b['qty'] == n else 'DISAGREE'
        self.row('assembly_qty', mark, '', b['qty'], n, st, '' if st == 'agree' else 'number of assemblies differs',
                 'parts.csv assembly_id per assembly_mark', ver=ver,
                 others='' if st == 'agree' else self.others_agreeing(key, ver, lambda x: x['qty'] == n))
        if b['seq'] and M.has['phase']:
            mains = [M.main_of[a] for a in aids]
            mp = sorted(str(M.prop(m, P_PHASE) or '') if m else '?' for m in mains)
            ks = sorted(s for s, q in b['seq'] for _ in range(q or 1))
            st = 'agree' if mp == ks else 'DISAGREE'
            self.row('sequence', mark, '', ' '.join(ks), ' '.join(mp), st, '' if st == 'agree' else 'sequences differ',
                     'phase property of the main piece', ver=ver)
        for d in b['pieces']:
            self.piece(key, ver, aids, d)
        self.bolts(key, ver, aids)
        self.welds(key, ver, aids)
        self._vparts = None
        tot, miss = 0.0, 0
        for a in aids:
            w, m_ = M.weight(a)
            tot += w
            miss += m_
        self.row('weight', mark, '', '(KISS lists no weights)', f'{tot:.1f} kg ({tot / LB:.0f} lb) for {n}', 'info',
                 'no weight in KISS' + (f'; {miss} part volume(s) missing' if miss else ''),
                 'verification.csv rebuilt volume x 7850 kg/m3 (bolts, welds excluded)', ver=ver)

    def piece(self, key, ver, aids, d):
        M = self.M
        kf, b = ver
        mark, pm = b['mark'], d['piece']
        parts = self.piece_parts(aids, pm)
        npc = len(parts)
        if not parts:
            elsewhere = sorted(M.piece_index.get(pm, set()) - {mark})
            self.row('piece_presence', mark, pm, f'qty {d["qty"]}', 'absent', 'DISAGREE',
                     'piece mark not in the assemblies of this mark' + (
                         ('; it occurs in ' + ', '.join(elsewhere)) if elsewhere else ''),
                     'parts.csv part_mark', 0, ver=ver,
                     others=self.others_agreeing(key, ver, lambda x: all(y['piece'] != pm for y in x['pieces'])))
            return
        F = [M.facts(p) for p in parts]
        self._vparts = parts
        self.row('piece_presence', mark, pm, f'qty {d["qty"]}', f'{npc} parts', 'agree', '', 'parts.csv part_mark', npc, ver=ver)
        # KISS quantities are totals over the assemblies of the mark; assemblies of one mark are identical, so every
        # assembly must hold total / number of assemblies pieces
        per = [sum(1 for p in M.asm[a] if p['part_mark'] == pm and p['role'] not in ('bolt', 'weld')) for a in aids]
        even = len(set(per)) == 1
        st = 'agree' if d['qty'] == npc and even else 'DISAGREE'
        reason = '' if st == 'agree' else ('quantity differs' if d['qty'] != npc else
                                           'same total, but not the same number in every assembly: ' + ' '.join(map(str, per)))
        self.row('piece_qty', mark, pm, d['qty'], npc if even else f'{npc} ({" ".join(map(str, per))} per assembly)', st, reason,
                 'parts.csv part_mark', npc, ver=ver, others='' if st == 'agree' else self.others_agreeing(
                     key, ver, lambda x: any(y['piece'] == pm and y['qty'] == npc for y in x['pieces'])))

        def vals(fn):
            c = collections.Counter(fn(f) for f in F)
            return c

        # preliminary marks (A records, one per piece) against the PrelimMark property of the model parts
        if d['prelim'] and M.has['prelim']:
            mp = sorted(str(M.prop(p, P_PRELIM) or '') for p in parts)
            kp = sorted(d['prelim'])
            ok = mp == kp
            summ = lambda L: ' '.join(f'{k}' + (f' x{v}' if v > 1 else '') for k, v in sorted(collections.Counter(L).items()))
            self.row('prelim_marks', mark, pm, summ(kp), summ(mp), 'agree' if ok else 'DISAGREE',
                     '' if ok else 'preliminary marks differ', 'part property set PrelimMark', npc, ver=ver,
                     others='' if ok else self.others_agreeing(key, ver, lambda x: any(
                         y['piece'] == pm and sorted(y['prelim']) == mp for y in x['pieces'])))

        def same_piece(x, pred):
            return any(y['piece'] == pm and pred(y) for y in x['pieces'])

        # name
        if d['name'] and M.has['name']:
            c = vals(lambda f: norm_text(f['name']))
            ok = set(c) == {norm_text(d['name'])}
            self.row('name', mark, pm, d['name'], ' | '.join(f'{k} x{v}' if len(c) > 1 else k for k, v in sorted(c.items())),
                     'agree' if ok else 'DISAGREE', '' if ok else 'part name differs', 'property set name', npc, ver=ver,
                     others='' if ok else self.others_agreeing(key, ver, lambda x: same_piece(x, lambda y: set(c) == {norm_text(y['name'])})))
        # profile designation
        kd = kiss_designation(d['shape'], d['size'])
        c = vals(lambda f: f['designation'] or '')
        named = sorted(k for k in c if k)
        unnamed = c.get('', 0)
        if not named:
            self.row('profile', mark, pm, f'{d["shape"]} {d["size"]}', '', 'n/a',
                     'no profile designation in the schedules (' + ', '.join(sorted({f['geometry'] for f in F})) + ' geometry)', '', npc, ver=ver)
        else:
            okc = {k: same_designation(kd, model_designation(k)) for k in named}
            ok = all(okc.values())
            src = sorted({f['desig_src'] for f in F if f['desig_src']})
            note = f'; {unnamed} part(s) without a designation not compared' if unnamed else ''
            # a model profile name that carries no dimensions (user-defined profile, e.g. '#4_CLEVIS') cannot be
            # compared as text with a dimensioned KISS size: not checkable here, the section check measures it
            user = [k for k in named if not okc[k] and kd[1] is not None and (model_designation(k) or (None, None))[1] is None]
            if not ok and len(user) == len(named):
                self.row('profile', mark, pm, f'{d["shape"]} {d["size"]}', ' | '.join(user), 'n/a',
                         'model profile is a user-defined name without dimensions; the section check compares the dimensions' + note,
                         '; '.join(src), npc, ver=ver)
            else:
                self.row('profile', mark, pm, f'{d["shape"]} {d["size"]}', ' | '.join(named),
                         'agree' if ok else 'DISAGREE', ('' if ok else 'designation differs') + note, '; '.join(src), npc, ver=ver,
                         others='' if ok else self.others_agreeing(key, ver, lambda x: same_piece(x, lambda y: all(
                             same_designation(kiss_designation(y['shape'], y['size']), model_designation(k)) for k in named))))
        # section dimensions measured on the rebuilt geometry
        self.section(key, ver, d, kd, F)
        # finish (only when the model carries a finish property)
        if M.has['finish']:
            c = vals(lambda f: re.sub(r'[^A-Z0-9]', '', str(M.prop(f['part_id'], P_FINISH) or '').upper()))
            kfin = re.sub(r'[^A-Z0-9]', '', d['finish'].upper())
            ok = set(c) == {kfin}
            self.row('finish', mark, pm, d['finish'], ' | '.join(sorted(c)), 'agree' if ok else 'DISAGREE',
                     '' if ok else 'finish differs', 'part property set finish', npc, ver=ver)
        # grade
        if d['grade']:
            c = vals(lambda f: f['grade'])
            ok = set(c) == {norm_grade(d['grade'])}
            self.row('grade', mark, pm, d['grade'], ' | '.join(sorted(c)), 'agree' if ok else 'DISAGREE',
                     '' if ok else 'grade differs', 'property set grade / parts.csv material', npc, ver=ver,
                     others='' if ok else self.others_agreeing(key, ver, lambda x: same_piece(x, lambda y: set(c) == {norm_grade(y['grade'])})))
        # length
        self.length(key, ver, d, F)
        # holes
        self.holes(key, ver, d, F)
        self._vparts = None

    def section(self, key, ver, d, kd, F):
        """compare dimensions encoded in the KISS size with the rebuilt section"""
        kf, b = ver
        mark, pm = b['mark'], d['piece']
        fam, dims = kd[0], kd[1]
        if fam not in DIMENSIONED or not dims or fam == 'PD':
            return
        mm = [x * INCH for x in dims]
        res, srcs = [], set()
        for f in F:
            sec, pl = f['section'] or {}, f['plate']
            k = sec.get('kind')
            if k == 'EXACT' and fam in ('RB', 'DBA', 'STUD') and len(mm) == 1 and sec.get('min_dia'):
                ok = close(mm[0], sec['min_dia'], DIM_TOL)
                res.append((ok, f'round {fmt(sec["min_dia"])}'))
                srcs.add('exact faces: smallest vertex ring about the axis')
                continue
            if k is None or k == 'EXACT':
                res.append((None, f'{f["geometry"]} geometry without a parametric section'))
                continue
            if fam == 'L' and len(mm) == 3 and k == 'L':
                ok = all(close(x, y, DIM_TOL) for x, y in zip(sorted(mm[:2]), sorted((sec['d'], sec['b'])))) and \
                    close(mm[2], sec['t'], DIM_TOL)
                res.append((ok, f'L {fmt(sec["d"])} x {fmt(sec["b"])} x {fmt(sec["t"])}'))
            elif fam == 'HSS' and len(mm) == 3 and k == 'RHS':
                ok = all(close(x, y, DIM_TOL) for x, y in zip(sorted(mm[:2]), sorted((sec['d'], sec['b'])))) and close(mm[2], sec['t'], DIM_TOL)
                res.append((ok, f'RHS {fmt(sec["d"])} x {fmt(sec["b"])} x {fmt(sec["t"])}'))
            elif fam == 'HSS' and len(mm) == 2 and k == 'CHS':
                ok = close(mm[0], sec['dia'], DIM_TOL) and close(mm[1], sec['t'], DIM_TOL)
                res.append((ok, f'CHS {fmt(sec["dia"])} x {fmt(sec["t"])}'))
            elif fam in ('RB', 'DBA', 'STUD') and len(mm) == 1 and k in ('CIRCLE', 'NGON'):
                ok = close(mm[0], sec['dia'], DIM_TOL)
                res.append((ok, f'round {fmt(sec["dia"])}'))
            elif fam == '#' and len(mm) == 2 and k == 'RECT':
                ok = all(close(x, y, DIM_TOL) for x, y in zip(sorted(mm), sorted((sec['d'], sec['b']))))
                res.append((ok, f'RECT {fmt(sec["d"])} x {fmt(sec["b"])}'))
            elif fam == 'PL' and len(mm) == 2 and pl:
                t, w, l, how = plate_fit(f, mm[0], mm[1], d['length'])
                ok = close(mm[0], t, DIM_TOL) and close(mm[1], w, PLATE_W_TOL)
                res.append((ok, f'plate {fmt(t)} x {fmt(w)}'))
                srcs.add(how)
                continue
            else:
                res.append((False, f'section kind {k} does not fit {fam}'))
            srcs.add('rebuilt section (solids.csv + profiles.csv)')
        known = [r for r in res if r[0] is not None]
        kiss = f'{d["shape"]} {d["size"]} = ' + ' x '.join(fmt(x) for x in mm) + ' mm'
        c = collections.Counter(r[1] for r in res)
        model = ' | '.join(f'{k} x{v}' if len(c) > 1 else k for k, v in sorted(c.items()))
        if not known:
            self.row('section', mark, pm, kiss, model, 'n/a', res[0][1], '', len(F), ver=ver)
            return
        ok = all(r[0] for r in known)
        part = len(known) < len(res)
        tol = f'{DIM_TOL} mm' + (f', plate width {PLATE_W_TOL:.2f} mm' if fam == 'PL' else '')
        self.row('section', mark, pm, kiss, model, 'agree' if ok else 'DISAGREE',
                 ('' if ok else f'rebuilt section differs (tolerance {tol})') + (
                     f'; {len(res) - len(known)} part(s) without a parametric section' if part else ''),
                 '; '.join(sorted(srcs)), len(F), ver=ver)

    def length(self, key, ver, d, F):
        kf, b = ver
        mark, pm = b['mark'], d['piece']
        if d['length'] is None:
            return
        kd = kiss_designation(d['shape'], d['size'])
        fam = kd[0]
        vals, srcs = [], set()
        for f in F:
            L = f['length']
            src = f['length_src']
            if fam == 'PL' and f['plate'] and kd[1] and len(kd[1]) == 2:
                t, w, L, src = plate_fit(f, kd[1][0] * INCH, kd[1][1] * INCH, d['length'])
            vals.append(L)
            if L is not None:
                srcs.add(src)
        known = [v for v in vals if v is not None]
        c = collections.Counter(fmt(v) if v is not None else 'n/a' for v in vals)
        model = ' | '.join(f'{k} x{v}' if len(c) > 1 else k for k, v in sorted(c.items()))
        srcs = sorted(srcs)
        if not known:
            self.row('length', mark, pm, fmt(d['length']), '', 'n/a',
                     'length not measurable (' + ', '.join(sorted({f['geometry'] for f in F})) + ' geometry)', '', len(F), ver=ver)
            return
        ok = all(close(v, d['length'], self.length_tol) for v in known)
        reason = '' if ok else f'length differs by {fmt(max(abs(v - d["length"]) for v in known))} mm (tolerance {self.length_tol})'
        if len(known) < len(vals):
            reason += ('; ' if reason else '') + f'{len(vals) - len(known)} part(s) not measurable'
        self.row('length', mark, pm, fmt(d['length']), model, 'agree' if ok else 'DISAGREE', reason, '; '.join(srcs), len(F),
                 ver=ver, others='' if ok else self.others_agreeing(key, ver, lambda x: any(
                     y['piece'] == pm and y['length'] is not None and all(close(v, y['length'], self.length_tol) for v in known) for y in x['pieces'])))

    def holes(self, key, ver, d, F):
        kf, b = ver
        mark, pm = b['mark'], d['piece']
        kn = sum(h['count'] for h in d['holes'])
        if any(f['holes'] is None for f in F):
            geo = sorted({f['geometry'] for f in F if f['holes'] is None})
            self.row('holes', mark, pm, kn, '', 'n/a', 'holes not countable on ' + ', '.join(geo) + ' geometry', '', len(F), ver=ver)
            return
        mh = [h for f in F for h in f['holes']]
        hsrc = '; '.join(sorted({f['holes_src'] for f in F}))
        st = 'agree' if kn == len(mh) else 'DISAGREE'
        self.row('holes', mark, pm, kn, len(mh), st, '' if st == 'agree' else 'hole count differs',
                 hsrc, len(F), ver=ver, others='' if st == 'agree' else self.others_agreeing(
                     key, ver, lambda x: any(y['piece'] == pm and sum(h['count'] for h in y['holes']) == len(mh) for y in x['pieces'])))
        if kn and kn == len(mh):
            ks = sorted((h['kind'].upper(), h['dia']) for h in d['holes'] for _ in range(h['count']))
            ms = sorted((k.upper(), dia) for k, dia in mh)
            rest = list(ms)
            ok = True
            for kk, dia in ks:
                for i, (mk_, mdia) in enumerate(rest):
                    if mk_ == kk and close(mdia, dia, HOLE_TOL):
                        del rest[i]
                        break
                else:
                    ok = False
                    break
            summ = lambda L: ', '.join(f'{v} {k[0].lower()} {fmt(k[1])}' for k, v in sorted(collections.Counter((k, round(x, 2)) for k, x in L).items()))
            self.row('hole_sizes', mark, pm, summ(ks), summ(ms), 'agree' if ok else 'DISAGREE',
                     '' if ok else f'hole kinds / diameters differ (tolerance {HOLE_TOL} mm)', hsrc, len(F), ver=ver)

    def bolts(self, key, ver, aids):
        """bolts per assembly mark: KISS bolt lines summed per (diameter, length, grade, field/shop) against the shank
        solids of the rebuilt bolt groups of all assemblies of the mark"""
        M = self.M
        kf, b = ver
        mark = b['mark']
        model, bparts = [], []
        for ai, a in enumerate(aids):
            for p in M.asm[a]:
                if p['role'] == 'bolt':
                    bparts.append(p)
                    model += [g + (ai,) for g in M.bolt_groups(p)]
        self._vparts = bparts
        kk = collections.OrderedDict()        # KISS key -> [qty, display, sizes]
        for x in sorted(b['bolts'], key=lambda x: x['line']):
            toks = split_size(x['size'])
            dia = parse_inch(toks[0]) * INCH if toks and parse_inch(toks[0]) else None
            key_ = (round(dia, 2) if dia else None, round(x['length'], 2) if x['length'] is not None else None,
                    norm_bolt_grade(x['grade']), x['name'].capitalize())
            e = kk.setdefault(key_, [0, f'{x["shape"]} {x["size"]} ({fmt(x["length"])} mm) {x["grade"]} {x["name"]}', 0])
            e[0] += x['qty'] or 0
            e[2] += 1
        if not kk and not model:
            return
        if any(m[4] is None for m in model):
            self.row('bolts', mark, '', sum(e[0] for e in kk.values()), '', 'n/a',
                     'bolt groups without shank solids (count unknown)', model[0][5], len(model), ver=ver)
            return
        src = model[0][5] if model else 'no bolt group in the model'
        matched = set()
        for (dia, L, g, fld), (q, disp, nlines) in kk.items():
            cand = [(i, m) for i, m in enumerate(model) if close(m[0], dia, BOLT_TOL) and close(m[1], L, BOLT_TOL)]
            same = sum(m[4] for i, m in cand if m[2] == g and m[3] == fld)
            matched.update(i for i, m in cand if m[2] == g and m[3] == fld)
            item = f'{disp.split(" (")[0].split(" ", 1)[1]} {fld}'
            kiss = f'{q} x {disp}' + (f' ({nlines} lines)' if nlines > 1 else '')
            # KISS bolt quantities are totals over the assemblies of the mark; field bolts are not part of an assembly's
            # identity, so only the total is compared (an uneven split over the assemblies is shown, not judged)
            per = [sum(m[4] for i, m in cand if m[2] == g and m[3] == fld and m[6] == ai) for ai in range(len(aids))]
            if same == q:
                self.row('bolts', mark, item, kiss, str(same) + ('' if len(set(per)) == 1 else f' ({" ".join(map(str, per))} per assembly)'),
                         'agree', '', src, len(cand), ver=ver)
                continue
            split = collections.Counter()
            for i, m in cand:
                split[f'{m[2] or "?"} {m[3] or "?"}'] += m[4]
            anyg = sum(split.values())
            reason = 'bolt count differs' if anyg != q else 'same count of this size, other grade or field/shop'

            def agrees(bb, dia=dia, L=L, g=g, fld=fld, same=same):
                tot = 0
                for y in bb['bolts']:
                    t_ = split_size(y['size'])
                    yd = parse_inch(t_[0]) * INCH if t_ and parse_inch(t_[0]) else None
                    if close(yd, dia, BOLT_TOL) and close(y['length'], L, BOLT_TOL) and norm_bolt_grade(y['grade']) == g \
                            and y['name'].capitalize() == fld:
                        tot += y['qty'] or 0
                return tot == same
            self.row('bolts', mark, item, kiss,
                     f'{same} ({", ".join(f"{v} {k}" for k, v in sorted(split.items())) or "none"} of {fmt(dia)} x {fmt(L)} mm)',
                     'DISAGREE', reason, src, len(cand), ver=ver, others=self.others_agreeing(key, ver, agrees))
        extra = collections.Counter()
        for i, m in enumerate(model):
            if i not in matched:
                extra[(round(m[0], 2), round(m[1], 2), m[2], m[3])] += m[4]
        for (dia, L, g, fld), cnt in sorted(extra.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2], kv[0][3])):
            self.row('bolts', mark, f'{fmt(dia)} x {fmt(L)} {fld}', 'none', f'{cnt} x {fmt(dia)} x {fmt(L)} mm {g} {fld}',
                     'DISAGREE', 'model bolts not in the KISS list', src, None, ver=ver)
        self._vparts = None

    def welds(self, key, ver, aids):
        """welds per assembly mark: number of weld beads, and their lengths / sizes. A KISS weld length is matched by
        the bead solid's length or by the weld's length attribute (KISS reports the attribute; the exported bead solid
        is sometimes trimmed, by 1/8 to 1/2 in, where it meets a corner)"""
        M = self.M
        kf, b = ver
        mark = b['mark']
        kw = [(w['length'], w['size'], w['count']) for d in b['pieces'] + b['bolts'] for w in d['welds']]
        mw, wparts = [], []
        for a in aids:
            for p in M.asm[a]:
                if p['role'] == 'weld':
                    wparts.append(p)
                    mw += M.weld_items(p)
        nparts = len(wparts)
        self._vparts = wparts
        if not kw and not mw:
            return
        kn, mn = sum(x[2] for x in kw), len(mw)
        kl = sum((x[0] or 0) * x[2] for x in kw)
        ml = sum(x[0] or 0 for x in mw)
        st = 'agree' if kn == mn else 'DISAGREE'
        src = '; '.join(sorted({x[3] for x in mw})) or 'no weld in the model'
        self.row('weld_count', mark, '', kn, mn, st, '' if st == 'agree' else 'number of weld beads differs', src, nparts,
                 ver=ver, others='' if st == 'agree' else self.others_agreeing(key, ver, lambda bb: sum(
                     w['count'] for d in bb['pieces'] + bb['bolts'] for w in d['welds']) == mn))
        if kn == mn and kn:
            ks = sorted(((x[0], x[1]) for x in kw for _ in range(x[2])), key=lambda t: (t[1] or 0, t[0] or 0))
            rest = sorted(mw, key=lambda t: (t[2] or 0, t[0] or 0))
            bad, by_attr = [], 0
            for L, sz in ks:
                hit = None
                for i, (Lb, La, s2, _) in enumerate(rest):          # first choice: the bead solid
                    if close(sz, s2, WELD_TOL) and close(L, Lb, WELD_TOL):
                        hit = i
                        break
                if hit is None:
                    for i, (Lb, La, s2, _) in enumerate(rest):      # else: the weld length attribute
                        if close(sz, s2, WELD_TOL) and close(L, La, WELD_TOL):
                            hit = i
                            by_attr += 1
                            break
                if hit is None:
                    bad.append((L, sz))
                else:
                    del rest[hit]
            ok = not bad
            self.row('weld_sizes', mark, '', f'{len(ks)} beads, total {fmt(kl, 1)} mm', f'{mn} beads, total {fmt(ml, 1)} mm'
                     + (f' ({by_attr} matched by the weld length attribute)' if by_attr else ''),
                     'agree' if ok else 'DISAGREE', '' if ok else (
                         f'{len(bad)} bead(s) without a model weld of the same length / size (tolerance {WELD_TOL} mm): '
                         + ', '.join(f'{fmt(L)} x {fmt(sz)}' for L, sz in bad) + '; model left: '
                         + ', '.join(f'{fmt(Lb)} ({fmt(La)}) x {fmt(s2)}' for Lb, La, s2, _ in rest)),
                     'bead solid length or weld length attribute; weld property set size', nparts, ver=ver)

    # ---------------------------------------------------------------- preliminary marks (advance bills)
    def prelim(self, key, ver, aids):
        M = self.M
        kf, b = ver
        mark = b['mark']
        self.row('presence', mark, '(preliminary mark)', f'qty {b["qty"]}', f'{len(aids)} assemblies whose main piece has this preliminary mark',
                 'agree', 'mark is a preliminary mark of the model, not an assembly mark (advance bill)', 'property set PrelimMark', ver=ver)
        n = len(aids)
        st = 'agree' if b['qty'] == n else 'DISAGREE'
        self.row('prelim_qty', mark, '', b['qty'], n, st, '' if st == 'agree' else 'number of assemblies with this preliminary mark differs',
                 'main pieces with this preliminary mark', ver=ver)
        d = b['main']
        if not d:
            return
        mains = [M.main_of[a] for a in aids]
        F = [M.facts(m) for m in mains if m]
        kd = kiss_designation(d['shape'], d['size'])
        c = collections.Counter(f['designation'] for f in F)
        ok = all(same_designation(kd, model_designation(k)) for k in c)
        self.row('prelim_profile', mark, d['piece'], f'{d["shape"]} {d["size"]}', ' | '.join(sorted(c)), 'agree' if ok else 'DISAGREE',
                 '' if ok else 'designation differs', 'main piece designation', len(F), ver=ver)
        c = collections.Counter(f['grade'] for f in F)
        ok = set(c) == {norm_grade(d['grade'])}
        self.row('prelim_grade', mark, d['piece'], d['grade'], ' | '.join(sorted(c)), 'agree' if ok else 'DISAGREE',
                 '' if ok else 'grade differs', 'main piece grade', len(F), ver=ver)
        Ls = [f['length'] for f in F if f['length'] is not None]
        if d['length'] is not None and Ls:
            ok = all(L <= d['length'] + self.length_tol for L in Ls)
            self.row('prelim_order_length', mark, d['piece'], fmt(d['length']), f'max {fmt(max(Ls))}', 'agree' if ok else 'DISAGREE',
                     'advance bill lengths are order lengths: every main piece must fit' + ('' if ok else ' - a main piece is longer'),
                     'rebuilt main pieces', len(Ls), ver=ver)


def weights_check(model, rows_out, weight_rows, wsum):
    """advance bill of materials (per preliminary mark, with weights; CSV from abm2csv.py) against the rebuilt main
    pieces. Several bills may list a mark (re-issues, a copy split by sequence): per mark the bill with the latest
    date is used (ties: file name); same-date bills whose totals differ are reported as conflicts."""
    per = collections.defaultdict(lambda: collections.defaultdict(list))      # mark -> source -> rows
    for r in weight_rows:
        per[r['mark']][r['source']].append(r)
    conflicts = []
    for mark in sorted(per):
        srcs = per[mark]
        tot = {}
        for src, rs in srcs.items():
            tot[src] = (rs[0].get('date', ''), sum(int(float(r['qty'])) for r in rs), round(sum(float(r['weight_lbs'] or 0) for r in rs), 1))
        order = sorted(srcs, key=lambda x: (tot[x][0], x))
        src = order[-1]
        same_date = [x for x in order if tot[x][0] == tot[src][0]]
        if len({tot[x][1] for x in same_date}) > 1 or max(tot[x][2] for x in same_date) - min(tot[x][2] for x in same_date) > 1.0:
            conflicts.append(dict(mark=mark, bills={x: dict(date=tot[x][0], qty=tot[x][1], lbs=tot[x][2]) for x in same_date}))
        rs = srcs[src]
        aids = model.prelim_groups.get(mark, [])
        qty = sum(int(float(r['qty'])) for r in rs)
        wl = sum(float(r['weight_lbs'] or 0) for r in rs)
        lenmm = sum(int(float(r['qty'])) * float(r['length_mm']) for r in rs if r.get('length_mm'))
        base = dict(assembly_mark=mark, kiss_file=src, kiss_exported=rs[0].get('date', ''), kiss_rev=rs[0].get('rev', ''),
                    kiss_line=','.join(str(r.get('row', '')) for r in rs), kiss_versions=len(srcs),
                    other_versions_agreeing='', job=rs[0].get('job', ''), kiss_after_model='')
        if not aids:
            rows_out.append(dict(base, check='abm_presence', item='', kiss=f'qty {qty}', model='absent', status='DISAGREE',
                                 reason='preliminary mark on no main piece of the model', model_source='property set PrelimMark',
                                 n_model_parts=0))
            continue
        mains = [model.main_of[a] for a in aids if model.main_of[a]]
        vc = collections.Counter(model.vstatus.get(m['part_id'], 'not verified') for m in mains)
        base['model_verification'] = next(iter(vc)) if len(vc) == 1 else ', '.join(f'{k} {v}' for k, v in sorted(vc.items()))
        rows_out.append(dict(base, check='abm_presence', item='', kiss=f'qty {qty}', model=f'{len(aids)} assemblies',
                             status='agree', reason='', model_source='property set PrelimMark of the main pieces', n_model_parts=len(aids)))
        F = [model.facts(m) for m in mains]
        st = 'agree' if qty == len(aids) else 'DISAGREE'
        rows_out.append(dict(base, check='abm_qty', item='', kiss=qty, model=len(aids), status=st,
                             reason='' if st == 'agree' else 'number of main pieces with this preliminary mark differs',
                             model_source='main pieces with this preliminary mark', n_model_parts=len(F)))
        sizes = sorted({r['size'] for r in rs})
        c = collections.Counter(f['designation'] for f in F)
        ok = all(any(same_designation(model_designation(z), model_designation(k)) for z in sizes) for k in c)
        rows_out.append(dict(base, check='abm_profile', item='', kiss=' | '.join(sizes), model=' | '.join(sorted(c)),
                             status='agree' if ok else 'DISAGREE', reason='' if ok else 'designation differs',
                             model_source='main piece designation', n_model_parts=len(F)))
        grades = sorted({norm_grade(r['grade']) for r in rs})
        cg = collections.Counter(f['grade'] for f in F)
        ok = set(cg) <= set(grades)
        rows_out.append(dict(base, check='abm_grade', item='', kiss=' | '.join(grades), model=' | '.join(sorted(cg)),
                             status='agree' if ok else 'DISAGREE', reason='' if ok else 'grade differs',
                             model_source='main piece grade', n_model_parts=len(F)))
        mw = [f['volume'] * STEEL_DENSITY for f in F if f['volume'] is not None]
        ml = [f['length'] for f in F if f['length'] is not None]
        if len(mw) == len(F) and len(ml) == len(F) and lenmm > 0 and sum(ml) > 0 and wl > 0:
            k_lin = wl * LB / (lenmm / 1000.0)          # kg/m from the bill
            m_lin = sum(mw) / (sum(ml) / 1000.0)
            rel = m_lin / k_lin - 1.0
            ok = abs(rel) <= WEIGHT_TOL
            wsum.append(dict(mark=mark, designation=' | '.join(sorted(c)), bill=src, bill_kg_per_m=round(k_lin, 3),
                             model_kg_per_m=round(m_lin, 3), rel=round(rel, 4)))
            sa = [f['section_area'] for f in F if f.get('section_area')]
            s_lin = (sum(sa) / len(sa)) * STEEL_DENSITY * 1000.0 if len(sa) == len(F) else None     # kg/m of the section
            wsum[-1].update(section_kg_per_m=round(s_lin, 3) if s_lin else None,
                            section_rel=round(s_lin / k_lin - 1.0, 4) if s_lin else None)
            diag = (f'; the rebuilt section alone weighs {s_lin:.2f} kg/m ({(s_lin / k_lin - 1) * 100:+.1f} % against the bill), '
                    f'holes / copes / fittings {(m_lin / s_lin - 1) * 100:+.1f} %') if s_lin else ''
            rows_out.append(dict(base, check='abm_weight', item='',
                                 kiss=f'{wl:.0f} lb for {qty} x {fmt(lenmm / qty)} mm = {k_lin:.2f} kg/m',
                                 model=f'{sum(mw) / LB:.0f} lb for {len(F)} pieces, {sum(ml):.0f} mm = {m_lin:.2f} kg/m ({rel * 100:+.1f} %)',
                                 status='agree' if ok else 'DISAGREE',
                                 reason=('weight per metre compared (the bill weighs order lengths)' +
                                         ('' if ok else f'; differs by more than {WEIGHT_TOL * 100:.0f} %') + diag),
                                 model_source='rebuilt volume x 7850 kg/m3 / rebuilt length of the main pieces', n_model_parts=len(F)))
        else:
            rows_out.append(dict(base, check='abm_weight', item='', kiss=f'{wl:.0f} lb', model='', status='n/a',
                                 reason='rebuilt volume or length missing for a main piece', model_source='', n_model_parts=len(F)))
    return conflicts


# ====================================================================================== summary


def model_date_from_ifc(path):
    """FILE_NAME time stamp of an IFC header (plain text read; .ifczip supported)"""
    if path.lower().endswith('.ifczip'):
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.lower().endswith('.ifc'))
            head = z.open(name).read(20000).decode('latin-1')
    else:
        head = open(path, 'rb').read(20000).decode('latin-1')
    m = re.search(r"FILE_NAME\s*\(\s*'(?:[^']|'')*'\s*,\s*'([^']+)'", head)
    if not m:
        raise SystemExit('no FILE_NAME time stamp in ' + path)
    return parse_dt(m.group(1).replace('T', ' ')[:19])


def summarize(model, kset, rows, args, model_date):
    checks = collections.OrderedDict()
    for r in rows:
        c = checks.setdefault(r['check'], collections.Counter())
        c[r['status']] += 1
    rates = {}
    for k, c in checks.items():
        a, d = c.get('agree', 0), c.get('DISAGREE', 0)
        rates[k] = dict(agree=a, disagree=d, not_checkable=c.get('n/a', 0), model_only=c.get('model_only', 0),
                        info=c.get('info', 0), agreement=round(a / (a + d), 4) if a + d else None)
    rclass = lambda t: re.sub(r'\d+(?:\.\d+)?', '#', t.split('; the rebuilt section')[0])
    dis = collections.Counter((r['check'], rclass(r['reason'])) for r in rows if r['status'] == 'DISAGREE')
    na = collections.Counter((r['check'], rclass(r['reason'])) for r in rows if r['status'] == 'n/a')
    every = [{k: r.get(k, '') for k in ('check', 'assembly_mark', 'item', 'kiss', 'model', 'reason', 'model_verification',
                                         'kiss_file', 'kiss_exported', 'kiss_after_model', 'other_versions_agreeing')}
             for r in rows if r['status'] == 'DISAGREE']
    expl = collections.Counter(r['check'] for r in rows if r['status'] == 'DISAGREE' and r['other_versions_agreeing'])
    files = []
    for kf in kset.files:
        files.append(dict(file=kf['file'], sha256=kf['sha256'], job=kf['job'], job_name=kf['job_name'], exported=dts(kf['exported']),
                          after_model=(bool(model_date and kf['exported'] and kf['exported'] > model_date) if model_date else None),
                          used=(kset.asof is None or (kf['exported'] is not None and kf['exported'] <= kset.asof)),
                          blocks=len(kf['blocks']), problems=kf['problems'], n_problems=len(kf['problems'])))
    multi, revised, same_ts_conflicts, changes = 0, 0, [], []
    after_model = []
    for key in sorted(kset.versions):
        vs = kset.versions[key]
        if len(vs) > 1:
            multi += 1
            log, ch = kset.history(key)
            if ch:
                revised += 1
                changes.append(dict(job=key[0], mark=key[1], versions=[f'{kf["file"]} ({dts(kf["exported"])}, rev {rev_text(b)}, group {g})'
                                                                        for g, kf, b in log], changes=ch))
            sel = kset.selected.get(key)
            if sel:
                ts = sel[0]['exported']
                peers = [v for v in vs if v[0]['exported'] == ts and v is not sel]
                for kf, b in peers:
                    if block_diff(b, sel[1]):
                        same_ts_conflicts.append(dict(job=key[0], mark=key[1], selected=sel[0]['file'], other=kf['file'],
                                                      what=block_diff(b, sel[1])))
        sel = kset.selected.get(key)
        if model_date and sel and sel[0]['exported'] and sel[0]['exported'] > model_date:
            after_model.append(f'{key[1]} ({sel[0]["file"]}, {dts(sel[0]["exported"])})')
    pres = [r for r in rows if r['check'] == 'presence']
    late = collections.Counter(r['check'] for r in rows if r['status'] == 'DISAGREE' and r.get('kiss_after_model') == 'yes')
    vfail = collections.Counter(r['check'] for r in rows if r['status'] == 'DISAGREE' and 'MISMATCH' in (r.get('model_verification') or ''))
    vfail_agree = collections.Counter(r['check'] for r in rows if r['status'] == 'agree' and 'MISMATCH' in (r.get('model_verification') or ''))
    jobs = collections.OrderedDict()
    for key in sorted(kset.selected):
        j = jobs.setdefault(key[0], dict(job_name='', marks=0, present=0, present_as_prelim=0))
        j['marks'] += 1
    for kf in kset.files:
        if kf['job'] in jobs:
            jobs[kf['job']]['job_name'] = kf['job_name']
    for r in pres:
        j = jobs.get(r['job'])
        if j and r['status'] == 'agree':
            if r['item']:
                j['present_as_prelim'] += 1
            else:
                j['present'] += 1
    nm = sum(1 for p in model.parts if p['part_mark'])
    na_ = sum(1 for p in model.parts if p['assembly_mark'])
    census = profile_census(model, kset)
    return dict(
        tool=VERSION, schedule_dir=os.path.basename(os.path.normpath(args.schedule_dir)),
        model=dict(source=model.info.get('source', ''), originating_system=model.info.get('originating_system', ''),
                   parts=len(model.parts), parts_with_part_mark=nm, parts_with_assembly_mark=na_,
                   assemblies=len(model.asm), assembly_marks=len(model.by_mark),
                   geometry=dict(collections.Counter(p['geometry'] for p in model.parts)),
                   model_date=dts(model_date) if model_date else None,
                   properties_available={k: v for k, v in model.has.items()}),
        options=dict(asof=dts(kset.asof) if kset.asof else None, length_tol_mm=args.length_tol, dim_tol_mm=DIM_TOL,
                     hole_tol_mm=HOLE_TOL, bolt_tol_mm=BOLT_TOL, weld_tol_mm=WELD_TOL, kiss_number_tol_mm=NUM_TOL,
                     plate_width_tol_mm=PLATE_W_TOL, steel_density_kg_m3=round(STEEL_DENSITY * 1e9, 3),
                     abm_linear_weight_tol=WEIGHT_TOL),
        dedup_rule=('per (job number, assembly mark) the block from the KISS file with the latest H-record export date+time is '
                    'used (ties: file name, then file content hash); with --asof only files exported at or before that time '
                    'are used'),
        kiss_files=files,
        versions=dict(marks=len(kset.versions), selected=len(kset.selected), excluded_by_asof=len(kset.excluded),
                      marks_in_several_files=multi, marks_with_changed_content=revised,
                      same_timestamp_conflicts=same_ts_conflicts, selected_version_newer_than_model=after_model,
                      changes=changes),
        jobs=jobs,
        model_marks_not_in_kiss=sorted(m for m in model.by_mark if m not in {k[1] for k in kset.versions}),
        checks=rates,
        disagreements_by_reason=[dict(check=k[0], reason=k[1], rows=v) for k, v in sorted(dis.items(), key=lambda x: (-x[1], x[0]))],
        disagreements=every,
        disagreements_with_another_kiss_version_agreeing=dict(expl),
        disagreements_on_kiss_versions_newer_than_model=dict(late),
        disagreements_on_parts_that_fail_verify=dict(vfail),
        agreements_on_parts_that_fail_verify=dict(vfail_agree),
        not_checkable_by_reason=[dict(check=k[0], reason=k[1], rows=v) for k, v in sorted(na.items(), key=lambda x: (-x[1], x[0]))],
        checks_not_available=[x for x, ok in (('prelim_marks', model.has['prelim']), ('sequence', model.has['phase']),
                                             ('finish', model.has['finish']), ('name', model.has['name'])) if not ok],
        profile_census=census,
    )


def profile_census(model, kset):
    """per KISS job and profile designation (members only): KISS pieces of the selected versions against the model's
    members. Informative only (no status): a design model without marks can still be compared profile by profile."""
    FAMS = ('W', 'HSS', 'L', 'C', 'MC', 'WT', 'PIPE', 'S', 'HP')
    m = collections.defaultdict(lambda: [0, 0.0])
    for p in model.parts:
        if p['role'] != 'member':
            continue
        md = model_designation(p['designation'])
        if md and md[0] in FAMS:
            f = model.facts(p)
            m[md[2]][0] += 1
            m[md[2]][1] += f['length'] or 0.0
    out = collections.OrderedDict()
    for job in sorted({k[0] for k in kset.selected}):
        k = collections.defaultdict(lambda: [0, 0.0])
        for key, (kf, b) in kset.selected.items():
            if key[0] != job:
                continue
            for d in b['pieces']:
                fam, dims, text = kiss_designation(d['shape'], d['size'])
                if fam in FAMS:
                    k[text][0] += d['qty'] or 0
                    k[text][1] += (d['qty'] or 0) * (d['length'] or 0.0)
        rows = []
        for t in sorted(set(k) | set(m)):
            rows.append(dict(designation=t, kiss_pieces=k[t][0] if t in k else 0, kiss_length_m=round(k[t][1] / 1000, 1) if t in k else 0,
                             model_members=m[t][0] if t in m else 0, model_length_m=round(m[t][1] / 1000, 1) if t in m else 0))
        both = [r for r in rows if r['kiss_pieces'] and r['model_members']]
        out[job] = dict(designations_kiss=sum(1 for r in rows if r['kiss_pieces']),
                        designations_model=sum(1 for r in rows if r['model_members']), designations_both=len(both),
                        same_count=sum(1 for r in both if r['kiss_pieces'] == r['model_members']), rows=rows)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('schedule_dir')
    ap.add_argument('kss', nargs='+')
    ap.add_argument('--asof', help='use only KISS files exported at or before this time (YYYY-MM-DD[THH:MM])')
    ap.add_argument('--model-date', help='export time of the model (annotates KISS versions newer than the model)')
    ap.add_argument('--ifc', help='read --model-date from the FILE_NAME header of this IFC / IFCZIP (text only)')
    ap.add_argument('--weights', action='append', default=[], help='advance bill CSV (abm2csv.py) to check per preliminary mark')
    ap.add_argument('--out', default='kiss', help='output name prefix (default kiss -> kiss_check.csv, kiss_summary.json)')
    ap.add_argument('--length-tol', type=float, default=LENGTH_TOL)
    args = ap.parse_args(argv)
    model_date = parse_dt(args.model_date) if args.model_date else (model_date_from_ifc(args.ifc) if args.ifc else None)
    asof = parse_dt(args.asof) if args.asof else None
    paths = []
    for p in args.kss:
        if os.path.isdir(p):
            paths += sorted(os.path.join(p, x) for x in os.listdir(p) if x.lower().endswith('.kss'))
        else:
            paths.append(p)
    model = Model(args.schedule_dir)
    kset = KissSet(sorted(set(paths)), asof=asof)
    ch = Checker(model, kset, model_date=model_date, length_tol=args.length_tol)
    rows = ch.run()
    wrows = []
    for w in args.weights:
        wrows += read_csv(w)
    wsum, wconf = [], []
    if wrows:
        wconf = weights_check(model, rows, wrows, wsum)
    out_csv = os.path.join(args.schedule_dir, f'{args.out}_check.csv')
    with open(out_csv, 'w', newline='', encoding='utf-8') as fh:
        wr = csv.DictWriter(fh, fieldnames=Checker.COLS)
        wr.writeheader()
        for r in rows:
            wr.writerow({k: r.get(k, '') for k in Checker.COLS})
    summ = summarize(model, kset, rows, args, model_date)
    if wrows:
        summ['advance_bills'] = dict(files=[dict(file=os.path.basename(w), sha256=hashlib.sha256(open(w, 'rb').read()).hexdigest())
                                            for w in args.weights], rows=len(wrows), marks=len({r['mark'] for r in wrows}),
                                     same_date_conflicts=wconf, linear_weight=wsum)
    with open(os.path.join(args.schedule_dir, f'{args.out}_summary.json'), 'w', encoding='utf-8') as fh:
        json.dump(summ, fh, indent=1, default=str)
    print(json.dumps(dict(rows=len(rows), checks=summ['checks']), indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
