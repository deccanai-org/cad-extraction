"""pmp completion: merge the track patches (complete/<track>/out/<tag>/patch.json, see ../INTERFACES.md) into a model's
baseline schedules -> COMPLETED schedules + schedules/completion.json. Pure python (csv / json), no CAD: the build,
the colouring and the checks run on Modal (app_v2 stage `complete`, build_completed_coloured.py, verify_completed.py).
"""
import collections
import copy
import csv
import hashlib
import json
import math
import os
import re
import shutil

VERSION = 'pmp-completion 1.0'
PATCH_SCHEMA = 'pmp-completion-patch/1'
OUT_SCHEMA = 'pmp-completion/1'
TRACK_ORDER = ['db1', 'sds2_ifc', 'standards', 'estimate']

# colour -> (rgb, STEP name prefix, folder title, meaning)
PALETTE = collections.OrderedDict([
    ('GREY', ((0.78, 0.78, 0.78), '', 'GREY - original geometry, verified, unchanged',
              'original geometry, verified correct against the source (unchanged)')),
    ('GREEN', ((0.10, 0.70, 0.20), 'GREEN-RESTORED', 'GREEN - restored exactly from the source file',
               'restored EXACTLY from data in the source file (DB1 / SDS/2 / IFC) that the conversion ignored or broke')),
    ('BLUE', ((0.10, 0.35, 0.95), 'BLUE-STANDARD', 'BLUE - built from cited industry standard tables',
              'built from a cited industry standard table (bolts / nuts / washers, studs, rebar, HSS radii, joists, '
              'grating, anchor rods)')),
    ('AMBER', ((1.00, 0.65, 0.00), 'AMBER-ESTIMATED', 'AMBER - ESTIMATED (best inference, basis in the name)',
               'ESTIMATED: no exact data and no standard - best inference from neighbouring parts, repeated marks, '
               'symmetry, the package drawings / NC1 / KISS (basis stated per part)')),
    ('MAGENTA', ((0.90, 0.00, 0.75), 'MAGENTA-NOT-EXACT', 'MAGENTA - our rebuild still differs from the target',
                 'our script\'s rebuild still differs from the target geometry (not fixed, or the build / check failed)')),
    ('RED', ((0.90, 0.05, 0.05), 'RED-POSITION-ONLY', 'RED - position only (marker)',
             'nothing known beyond a position: a marker only')),
])
COLOURS = list(PALETTE)
WEAKEST_FIRST = ['RED', 'MAGENTA', 'AMBER', 'BLUE', 'GREEN', 'GREY']
OPS = {'add_part', 'replace_part', 'add_cuts', 'replace_cuts', 'set_fields', 'marker', 'accept', 'remove_part'}
GEOM_KINDS = {'profile_extrusion', 'cylinder', 'hex_prism', 'ring', 'prism', 'sweep', 'faceted', 'box', 'compound',
              'schedule_part'}
PART_FIELDS = ['part_id', 'ifc_class', 'role', 'name', 'designation', 'material', 'part_mark', 'assembly_mark',
               'drawing_ref', 'assembly_id', 'geometry', 'note']
PROFILE_FIELDS = ['profile_id', 'kind', 'designation', 'd', 'b', 'tw', 'tf', 't', 'r', 'r_edge', 'r_inner', 'r_outer',
                  'slope', 'radius', 'pos_x', 'pos_y', 'pos_angle', 'sides', 'radius_inner', 'angle_inner']
SOLID_FIELDS = ['solid_id', 'part_id', 'role', 'opening_id', 'profile_id', 'ox', 'oy', 'oz', 'xx', 'xy', 'xz', 'zx', 'zy',
                'zz', 'vx', 'vy', 'vz', 'scale', 'fxx', 'fxy', 'fxz', 'fzx', 'fzy', 'fzz']
CUT_FIELDS = ['cut_id', 'solid_id', 'kind', 'px', 'py', 'pz', 'nx', 'ny', 'nz', 'tool_solid_id']
ROLES = {'member', 'plate', 'bolt', 'weld', 'accessory', 'concrete', 'other'}
FLAG_FIX_COLOURS = {'ORANGE', 'RED', 'PURPLE'}       # baseline flags that must be resolved for a part to stay GREY


# ======================================================================================== small helpers
def sha1(s):
    return hashlib.sha1(s.encode('utf-8')).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 22), b''):
            h.update(b)
    return h.hexdigest()


def fmt(v):
    """deterministic CSV number"""
    if isinstance(v, str):
        return v
    if v is None:
        return ''
    if isinstance(v, bool):
        return '1' if v else '0'
    if isinstance(v, int):
        return str(v)
    if abs(v) < 5e-12:
        return '0.0'
    return repr(round(float(v), 9))


def vec(a):
    if not isinstance(a, (list, tuple)) or len(a) != 3:
        raise ValueError(f'expected [x, y, z], got {a!r}')
    return [float(x) for x in a]


def sub(a, b):
    return [a[i] - b[i] for i in range(3)]


def add(a, b):
    return [a[i] + b[i] for i in range(3)]


def mul(a, k):
    return [x * k for x in a]


def dot(a, b):
    return sum(a[i] * b[i] for i in range(3))


def cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def norm(a):
    return math.sqrt(dot(a, a))


def unit(a):
    n = norm(a)
    if n < 1e-12:
        raise ValueError('zero-length direction')
    return [x / n for x in a]


def perp(z):
    a = [1.0, 0.0, 0.0] if abs(z[0]) < 0.9 else [0.0, 1.0, 0.0]
    return unit(cross(z, a))


def square_to(x, z):
    """x projected square to z (unit); a perpendicular when x is missing or parallel"""
    if x is None:
        return perp(z)
    x = vec(x)
    x = sub(x, mul(z, dot(x, z)))
    return unit(x) if norm(x) > 1e-9 else perp(z)


def read_csv(path):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return [], []
    with open(path, newline='', encoding='utf-8') as fh:
        rd = csv.DictReader(fh)
        rows = list(rd)
        return list(rd.fieldnames or []), rows


def write_csv(path, fields, rows):
    with open(path, 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction='ignore', lineterminator='\r\n')
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, '') if r.get(k) is not None else '' for k in fields})


def ascii_text(s, limit=None):
    s = ''.join(ch if 32 <= ord(ch) < 127 else ('?' if ord(ch) >= 127 else ' ') for ch in str(s or ''))
    s = ' '.join(s.replace('\\', '/').split())
    if limit and len(s) > limit:
        s = s[:limit - 3].rstrip() + '...'
    return s


def weakest(colours):
    for c in WEAKEST_FIRST:
        if c in colours:
            return c
    return 'GREY'


# ======================================================================================== validation
def validate_patch(p, tag=None, baseline_ids=None):
    """-> list of error strings (empty = valid)"""
    err = []
    if p.get('schema') != PATCH_SCHEMA:
        err.append(f"schema must be {PATCH_SCHEMA!r}")
    if p.get('track') not in TRACK_ORDER:
        err.append(f"track must be one of {TRACK_ORDER}")
    if tag and p.get('tag') != tag:
        err.append(f"tag {p.get('tag')!r} != {tag!r}")
    ids = set()
    for k, op in enumerate(p.get('ops') or []):
        where = f"ops[{k}] ({op.get('id')})"
        o = op.get('op')
        if o not in OPS:
            err.append(f'{where}: unknown op {o!r}')
            continue
        if not op.get('id'):
            err.append(f'{where}: id missing')
        elif op['id'] in ids:
            err.append(f'{where}: duplicate id')
        ids.add(op.get('id'))
        col = op.get('colour')
        if o not in ('accept', 'remove_part', 'set_fields') or col:
            if col not in ('GREEN', 'BLUE', 'AMBER', 'RED'):
                err.append(f'{where}: colour must be GREEN, BLUE, AMBER or RED (GREY / MAGENTA are the integration\'s)')
        if o == 'marker' and col != 'RED':
            err.append(f'{where}: a marker is RED')
        pv = op.get('provenance') or {}
        if not pv.get('what'):
            err.append(f'{where}: provenance.what missing')
        if col == 'GREEN' and not pv.get('source'):
            err.append(f'{where}: GREEN needs provenance.source (file + record + field)')
        if col == 'BLUE' and not pv.get('standard'):
            err.append(f'{where}: BLUE needs provenance.standard (standard + table + values)')
        if col == 'AMBER' and not pv.get('basis'):
            err.append(f'{where}: AMBER needs provenance.basis (why this estimate)')
        if col == 'RED' and not (pv.get('source') or pv.get('basis')):
            err.append(f'{where}: RED needs provenance.source or basis (where the position comes from)')
        if o in ('replace_part', 'add_cuts', 'replace_cuts', 'set_fields', 'accept', 'remove_part'):
            if not op.get('part_id'):
                err.append(f'{where}: part_id missing')
            elif baseline_ids is not None and op['part_id'] not in baseline_ids:
                err.append(f"{where}: part_id {op['part_id']} not in the baseline parts.csv (nor added earlier)")
        if o in ('add_part', 'replace_part'):
            try:
                check_geom(op.get('geometry'))
            except ValueError as e:
                err.append(f'{where}: geometry: {e}')
        if o in ('add_part', 'marker'):
            part = op.get('part') or {}
            if part.get('role') not in ROLES:
                err.append(f"{where}: part.role must be one of {sorted(ROLES)}")
            if not part.get('name'):
                err.append(f'{where}: part.name missing')
            if baseline_ids is not None and part.get('part_id') and part['part_id'] in baseline_ids:
                err.append(f"{where}: part.part_id {part['part_id']} already exists (use replace_part)")
        if o == 'marker':
            try:
                vec(op.get('point'))
            except ValueError as e:
                err.append(f'{where}: point: {e}')
        if o in ('add_cuts', 'replace_cuts'):
            for j, c in enumerate(op.get('cuts') or []):
                try:
                    check_cut(c)
                except ValueError as e:
                    err.append(f'{where}: cuts[{j}]: {e}')
            if o == 'add_cuts' and not op.get('cuts'):
                err.append(f'{where}: no cuts')
        if baseline_ids is not None and o in ('add_part', 'marker'):
            pid = (op.get('part') or {}).get('part_id') or new_part_id(p.get('track'), op.get('id'))
            baseline_ids.add(pid)
    return err


def check_geom(g, inner=False):
    if not isinstance(g, dict):
        raise ValueError('GEOM must be an object')
    k = g.get('kind')
    if k not in GEOM_KINDS:
        raise ValueError(f'unknown kind {k!r}')
    if k == 'compound':
        if inner:
            raise ValueError('nested compound')
        if not g.get('items'):
            raise ValueError('compound without items')
        for it in g['items']:
            if it.get('kind') == 'faceted':
                raise ValueError('faceted inside a compound (give the whole part as one faceted GEOM)')
            check_geom(it, True)
        return
    if k == 'faceted':
        if not g.get('solids'):
            raise ValueError('faceted without solids')
        return
    if k == 'schedule_part':
        if inner:
            raise ValueError('schedule_part is a whole part (not inside a compound / a cut tool)')
        if not g.get('schedules') or not g.get('part_id'):
            raise ValueError('schedule_part needs schedules and part_id')
        if not os.path.exists(os.path.join(g['schedules'], 'parts.csv')):
            raise ValueError(f"schedule_part: no parts.csv in {g['schedules']}")
        return
    need = {'profile_extrusion': ['profile', 'start', 'end'], 'cylinder': ['start', 'end', 'radius'],
            'hex_prism': ['base_center', 'axis', 'height', 'across_flats'],
            'ring': ['base_center', 'axis', 'height', 'outer_diameter', 'inner_diameter'],
            'prism': ['outline_world', 'normal', 'thickness'], 'sweep': ['profile', 'points'],
            'box': ['origin', 'x_dir', 'y_dir', 'size']}[k]
    for f in need:
        if g.get(f) in (None, '', []):
            raise ValueError(f'{k}: {f} missing')
    if k in ('profile_extrusion', 'sweep'):
        pr = g['profile']
        if pr.get('kind') == 'POLY' and not g.get('outline'):
            raise ValueError('POLY profile needs outline')
    for c in g.get('cuts') or []:
        check_cut(c)


def check_cut(c):
    k = c.get('kind')
    if k == 'plane':
        vec(c.get('point'))
        unit(vec(c.get('normal')))
    elif k == 'solid':
        t = c.get('tool')
        check_geom(t, True)
        if t.get('kind') in ('compound', 'faceted'):
            raise ValueError('a cut tool is one solid (not compound / faceted)')
    else:
        raise ValueError(f'cut kind {k!r} (plane | solid)')


def new_part_id(track, op_id):
    return 'C' + sha1(f'{track}:{op_id}')[:21]


# ======================================================================================== GEOM -> schedule rows
class Rows:
    """schedule rows being added: profiles (deduplicated by content), outlines, solids, cuts, paths, exact"""

    def __init__(self, existing_profiles):
        self.profiles = {}            # new profile rows
        self.outlines = {}
        self.solids = []
        self.cuts = []
        self.paths = {}
        self.exact = {}
        self.boundaries = {}
        self.openings = []
        self.existing_profiles = existing_profiles

    def profile(self, row, outline=None):
        r = {k: fmt(row.get(k)) if row.get(k) not in (None, '') else '' for k in PROFILE_FIELDS if k != 'profile_id'}
        if not r.get('kind'):
            raise ValueError('profile kind missing')
        key = json.dumps([r, outline], sort_keys=True)
        pid = 'P_' + sha1(key)[:12]
        if pid not in self.profiles and pid not in self.existing_profiles:
            self.profiles[pid] = dict(r, profile_id=pid)
            if outline is not None:
                self.outlines[pid] = outline
        return pid

    def profile_row(self, row, outline=None):
        """an existing profiles.csv row (other schedules) -> its id here (deduplicated by content)"""
        return self.profile({k: row.get(k, '') for k in PROFILE_FIELDS if k != 'profile_id'}, outline)

    def solid(self, sid, part_id, role, pid, o, x, z, v):
        f = lambda a: [fmt(t) for t in a]
        r = dict(solid_id=sid, part_id=part_id, role=role, opening_id='', profile_id=pid, scale='1.0')
        r.update(zip(['ox', 'oy', 'oz'], f(o)))
        r.update(zip(['xx', 'xy', 'xz'], f(x)))
        r.update(zip(['zx', 'zy', 'zz'], f(z)))
        r.update(zip(['vx', 'vy', 'vz'], f(v)))
        r.update(zip(['fxx', 'fxy', 'fxz'], f(x)))
        r.update(zip(['fzx', 'fzy', 'fzz'], f(z)))
        self.solids.append(r)
        return sid


def plane_outline(points, normal):
    """planar polygon (world points) -> (origin, x axis, z axis, 2D outline segments) in its own frame"""
    pts = []
    for q in points:
        q = vec(q)
        if not pts or norm(sub(q, pts[-1])) > 1e-6:
            pts.append(q)
    if len(pts) > 2 and norm(sub(pts[0], pts[-1])) <= 1e-6:
        pts.pop()
    if len(pts) < 3:
        raise ValueError('outline with fewer than 3 distinct points')
    z = unit(vec(normal))
    o = pts[0]
    x = None
    for q in pts[1:]:
        d = sub(q, o)
        d = sub(d, mul(z, dot(d, z)))
        if norm(d) > 1e-6:
            x = unit(d)
            break
    if x is None:
        raise ValueError('degenerate outline')
    y = cross(z, x)
    loc = [[round(dot(sub(q, o), x), 9), round(dot(sub(q, o), y), 9)] for q in pts]
    off_plane = max(abs(dot(sub(q, o), z)) for q in pts)
    if off_plane > 0.5:
        raise ValueError(f'outline not planar ({off_plane:.2f} mm off the plane square to the normal)')
    return o, x, z, {'outer': [{'t': 'L', 'p': loc + [loc[0]]}], 'inner': []}


def geom_rows(g, rows, part_id, base, role='body'):
    """one GEOM -> solid rows (+ their cut rows). `base` = deterministic id stem. Returns the body solid ids."""
    k = g['kind']
    if k == 'compound':
        out = []
        for j, it in enumerate(g['items']):
            out += geom_rows(it, rows, part_id, f'{base}.{j}', role)
        return out
    sid = 'S_' + sha1(base)[:14]
    if k in ('profile_extrusion', 'cylinder'):
        s, e = vec(g['start']), vec(g['end'])
        z = unit(sub(e, s))
        x = square_to(g.get('x_dir'), z)
        if k == 'cylinder':
            pid = rows.profile({'kind': 'CIRCLE', 'radius': float(g['radius'])})
        else:
            pid = rows.profile(g['profile'], g.get('outline'))
        rows.solid(sid, part_id, role, pid, s, x, z, sub(e, s))
    elif k == 'hex_prism':
        z = unit(vec(g['axis']))
        x = square_to(g.get('x_dir'), z)
        R = float(g['across_flats']) / math.sqrt(3.0)
        pid = rows.profile({'kind': 'NGON', 'sides': 6, 'radius': R, 'pos_angle': math.pi / 6})
        rows.solid(sid, part_id, role, pid, vec(g['base_center']), x, z, mul(z, float(g['height'])))
        if g.get('hole_diameter'):
            tool = {'kind': 'cylinder', 'start': add(vec(g['base_center']), mul(z, -1.0)),
                    'end': add(vec(g['base_center']), mul(z, float(g['height']) + 1.0)),
                    'radius': float(g['hole_diameter']) / 2.0}
            g = dict(g, cuts=[{'kind': 'solid', 'tool': tool}] + list(g.get('cuts') or []))
    elif k == 'ring':
        z = unit(vec(g['axis']))
        x = square_to(g.get('x_dir'), z)
        R, ri = float(g['outer_diameter']) / 2.0, float(g['inner_diameter']) / 2.0
        if not 0 < ri < R:
            raise ValueError('ring: need 0 < inner < outer diameter')
        pid = rows.profile({'kind': 'CHS', 'radius': R, 't': R - ri})
        rows.solid(sid, part_id, role, pid, vec(g['base_center']), x, z, mul(z, float(g['height'])))
    elif k == 'prism':
        o, x, z, outline = plane_outline(g['outline_world'], g['normal'])
        o = add(o, mul(z, float(g.get('offset') or 0.0)))
        pid = rows.profile({'kind': 'POLY'}, outline)
        rows.solid(sid, part_id, role, pid, o, x, z, mul(z, float(g['thickness'])))
    elif k == 'box':
        x = unit(vec(g['x_dir']))
        y = vec(g['y_dir'])
        y = unit(sub(y, mul(x, dot(x, y))))
        z = cross(x, y)
        dx, dy, dz = [float(v) for v in g['size']]
        o = add(vec(g['origin']), add(mul(x, dx / 2), mul(y, dy / 2)))
        pid = rows.profile({'kind': 'RECT', 'b': dx, 'd': dy})
        rows.solid(sid, part_id, role, pid, o, x, z, mul(z, dz))
    elif k == 'sweep':
        pts = [vec(p) for p in g['points']]
        if len(pts) < 2:
            raise ValueError('sweep needs two points')
        z = unit(sub(pts[1], pts[0]))
        x = square_to(g.get('x_dir'), z)
        pid = rows.profile(g['profile'], g.get('outline'))
        rows.solid(sid, part_id, role, pid, pts[0], x, z, sub(pts[1], pts[0]))
        pth = {'points': [[round(c, 9) for c in p] for p in pts], 'closed': bool(g.get('closed')),
               'section': g.get('section', 'perpendicular')}
        rows.paths[sid] = pth
    elif k == 'faceted':
        raise ValueError('faceted geometry is a whole part (not a solid row)')
    for j, c in enumerate(g.get('cuts') or []):
        cut_rows(c, rows, part_id, sid, f'{base}.cut{j}')
    return [sid]


def cut_rows(c, rows, part_id, solid_id, base):
    cid = 'C_' + sha1(base)[:14]
    if c['kind'] == 'plane':
        p, n = vec(c['point']), unit(vec(c['normal']))
        rows.cuts.append(dict(cut_id=cid, solid_id=solid_id, kind='plane', px=fmt(p[0]), py=fmt(p[1]), pz=fmt(p[2]),
                              nx=fmt(n[0]), ny=fmt(n[1]), nz=fmt(n[2]), tool_solid_id=''))
    else:
        tids = geom_rows(c['tool'], rows, part_id, base + '.tool', role='cut_tool')
        rows.cuts.append(dict(cut_id=cid, solid_id=solid_id, kind='solid', px='', py='', pz='', nx='', ny='', nz='',
                              tool_solid_id=tids[0]))
    return cid


_SRC_CACHE = {}


def src_schedules(folder):
    folder = os.path.abspath(folder)
    if folder not in _SRC_CACHE:
        s = lambda n: os.path.join(folder, n)
        d = {}
        _, d['parts'] = read_csv(s('parts.csv'))
        _, prof = read_csv(s('profiles.csv'))
        d['profiles'] = {r['profile_id']: r for r in prof}
        _, sol = read_csv(s('solids.csv'))
        d['solids'] = sol
        _, d['cuts'] = read_csv(s('cuts.csv'))
        _, d['openings'] = read_csv(s('openings.csv'))
        d['outlines'] = json.load(open(s('profile_outlines.json'))) if os.path.exists(s('profile_outlines.json')) else {}
        d['boundaries'] = json.load(open(s('cut_boundaries.json'))) if os.path.exists(s('cut_boundaries.json')) else {}
        d['paths'] = json.load(open(s('paths.json'))) if os.path.exists(s('paths.json')) else {}
        d['exact'] = {}
        if os.path.exists(s('exact_geometry.jsonl')):
            for ln in open(s('exact_geometry.jsonl'), encoding='utf-8'):
                if ln.strip():
                    r = json.loads(ln)
                    d['exact'][r['part_id']] = r
        d['by_part'] = collections.defaultdict(list)
        for r in sol:
            d['by_part'][r['part_id']].append(r)
        d['part'] = {p['part_id']: p for p in d['parts']}
        _SRC_CACHE[folder] = d
    return _SRC_CACHE[folder]


def copy_schedule_part(g, rows, dst_pid, base):
    """GEOM schedule_part -> rows here (ids namespaced). Returns (source part row, exact record or None)"""
    d = src_schedules(g['schedules'])
    spid = g['part_id']
    prow = d['part'].get(spid)
    if prow is None:
        raise ValueError(f"schedule_part: part {spid} not in {g['schedules']}/parts.csv")
    if prow.get('geometry') == 'exact':
        rec = dict(d['exact'][spid], part_id=dst_pid)
        return prow, rec
    smap = {r['solid_id']: 'S_' + sha1(f"{base}:{r['solid_id']}")[:14] for r in d['by_part'].get(spid, [])}
    for r in d['by_part'].get(spid, []):
        pid = rows.profile_row(d['profiles'][r['profile_id']], d['outlines'].get(r['profile_id']))
        nr = dict(r, solid_id=smap[r['solid_id']], part_id=dst_pid, profile_id=pid)
        rows.solids.append(nr)
        if r['solid_id'] in d['paths']:
            rows.paths[nr['solid_id']] = d['paths'][r['solid_id']]
    for c in d['cuts']:
        if c['solid_id'] in smap:
            cid = 'C_' + sha1(f"{base}:{c['cut_id']}")[:14]
            nc = dict(c, cut_id=cid, solid_id=smap[c['solid_id']])
            if c.get('tool_solid_id'):
                if c['tool_solid_id'] not in smap:
                    raise ValueError(f"schedule_part {spid}: cut tool {c['tool_solid_id']} belongs to another part")
                nc['tool_solid_id'] = smap[c['tool_solid_id']]
            if c['cut_id'] in d['boundaries']:
                rows.boundaries[cid] = d['boundaries'][c['cut_id']]
            rows.cuts.append(nc)
    for o in d['openings']:
        if o['part_id'] == spid:
            oid = 'O_' + sha1(f"{base}:{o['opening_id']}")[:14]
            rows.openings.append(dict(o, opening_id=oid, part_id=dst_pid,
                                      tool_solids=' '.join(smap[t] for t in o['tool_solids'].split())))
            for r in rows.solids:
                if r.get('opening_id') == o['opening_id'] and r['part_id'] == dst_pid:
                    r['opening_id'] = oid
    return prow, None


def canonical_part(d, spid):
    """content fingerprint of one part's geometry rows in a schedules folder (ids replaced by content): equal
    fingerprints = the same construction"""
    p = d['part'][spid]
    if p.get('geometry') == 'exact':
        return sha1(json.dumps(['exact', d['exact'].get(spid, {}).get('solids')], sort_keys=True))
    sol = {r['solid_id']: r for r in d['by_part'].get(spid, [])}

    def solid_key(sid, depth=0):
        r = sol[sid]
        prof = d['profiles'][r['profile_id']]
        pk = [prof.get(k, '') for k in PROFILE_FIELDS if k != 'profile_id'] + [d['outlines'].get(r['profile_id'])]
        cuts = []
        for c in d['cuts']:
            if c['solid_id'] == sid:
                ck = [c['kind'], c['px'], c['py'], c['pz'], c['nx'], c['ny'], c['nz'],
                      solid_key(c['tool_solid_id'], depth + 1) if c.get('tool_solid_id') and depth < 6 else '',
                      d['boundaries'].get(c['cut_id'])]
                cuts.append(ck)
        return [r['role'], pk] + [r.get(k, '') for k in SOLID_FIELDS[5:]] + [d['paths'].get(sid), cuts]
    bodies = sorted(json.dumps(solid_key(s), sort_keys=True) for s, r in sol.items() if r['role'] == 'body')
    ops = []
    for o in d['openings']:
        if o['part_id'] == spid:
            ops.append(sorted(json.dumps(solid_key(t), sort_keys=True) for t in o['tool_solids'].split()))
    return sha1(json.dumps([p.get('geometry'), bodies, sorted(map(json.dumps, ops))], sort_keys=True))


def faceted_record(g, part_id):
    sols = []
    for s in g['solids']:
        faces = [[[[round(float(c), 9) for c in pt] for pt in loop] for loop in face] for face in s['faces']]
        voids = s.get('voids') or []
        sols.append({'faces': faces, 'voids': voids})
    return {'part_id': part_id, 'source': 'completion (pmp-completion)', 'solids': sols}


def geom_points(g):
    """every point a GEOM names (for a rough box / 'where' before the build)"""
    k = g.get('kind')
    pts = []
    if k == 'compound':
        for it in g['items']:
            pts += geom_points(it)
    elif k in ('profile_extrusion', 'cylinder'):
        pts += [vec(g['start']), vec(g['end'])]
    elif k in ('hex_prism', 'ring'):
        b = vec(g['base_center'])
        pts += [b, add(b, mul(unit(vec(g['axis'])), float(g['height'])))]
    elif k == 'prism':
        pts += [vec(p) for p in g['outline_world']]
    elif k == 'box':
        pts += [vec(g['origin'])]
    elif k == 'sweep':
        pts += [vec(p) for p in g['points']]
    elif k == 'schedule_part':
        d = src_schedules(g['schedules'])
        for r in d['by_part'].get(g['part_id'], []):
            o = [float(r['ox'] or 0), float(r['oy'] or 0), float(r['oz'] or 0)]
            pts += [o, add(o, [float(r['vx'] or 0), float(r['vy'] or 0), float(r['vz'] or 0)])]
        ex = d['exact'].get(g['part_id'])
        if ex:
            for so in ex['solids']:
                for f in so['faces']:
                    for loop in f:
                        pts += [vec(p) for p in loop]
    elif k == 'faceted':
        for s in g['solids']:
            for f in s['faces']:
                for loop in f:
                    pts += [vec(p) for p in loop]
    return pts


def bbox_of(pts):
    if not pts:
        return None
    return [round(min(p[i] for p in pts), 1) for i in range(3)] + [round(max(p[i] for p in pts), 1) for i in range(3)]


# ======================================================================================== baseline
class Baseline:
    def __init__(self, tree):
        """tree = scripts/<model_folder>/ of the baseline run"""
        self.tree = tree
        self.sched = os.path.join(tree, 'schedules')
        s = lambda n: os.path.join(self.sched, n)
        self.part_fields, self.parts = read_csv(s('parts.csv'))
        self.prof_fields, self.profiles = read_csv(s('profiles.csv'))
        self.solid_fields, self.solids = read_csv(s('solids.csv'))
        self.cut_fields, self.cuts = read_csv(s('cuts.csv'))
        self.open_fields, self.openings = read_csv(s('openings.csv'))
        self.outlines = json.load(open(s('profile_outlines.json'))) if os.path.exists(s('profile_outlines.json')) else {}
        self.paths = json.load(open(s('paths.json'))) if os.path.exists(s('paths.json')) else {}
        self.boundaries = json.load(open(s('cut_boundaries.json'))) if os.path.exists(s('cut_boundaries.json')) else {}
        self.exact_lines = []
        if os.path.exists(s('exact_geometry.jsonl')):
            self.exact_lines = [ln for ln in open(s('exact_geometry.jsonl'), encoding='utf-8') if ln.strip()]
        self.issues = json.load(open(s('issues.json'))) if os.path.exists(s('issues.json')) else {}
        self.missing = json.load(open(s('missing_parts.json'))) if os.path.exists(s('missing_parts.json')) else {}
        vf = os.path.join(tree, 'verification', 'verification.csv')
        _, vrows = read_csv(vf)
        self.verification = {r['part_id']: r for r in vrows}
        mi = os.path.join(tree, 'model_info.json')
        self.model_info = json.load(open(mi)) if os.path.exists(mi) else {}
        self.model_name = self.issues.get('model_name') or self.model_info.get('model') or os.path.basename(tree.rstrip('/'))


# ======================================================================================== merge
def load_patches(complete_root, tag):
    """[(path, patch)] in TRACK_ORDER for one sample"""
    out = []
    for tr in TRACK_ORDER:
        f = os.path.join(complete_root, tr, 'out', tag, 'patch.json')
        if os.path.exists(f):
            out.append((f, json.load(open(f, encoding='utf-8'))))
    return out


def label_for(colour, info, base):
    """STEP product name: '<PREFIX> <what> [<basis>] | <part id> <name>'"""
    if colour == 'GREY':
        return ascii_text(base, 300)
    tail = ascii_text(base, 110)
    head = ascii_text(f"{PALETTE[colour][1]} {info}".strip(), 300 - len(tail) - 3)
    return f'{head} | {tail}'


def short_basis(pv, colour):
    if colour == 'GREEN':
        return 'source: ' + str(pv.get('source', ''))
    if colour == 'BLUE':
        return 'standard: ' + str(pv.get('standard', ''))
    if colour == 'AMBER':
        return 'estimated, basis: ' + str(pv.get('basis', ''))
    if colour == 'RED':
        return 'position from: ' + str(pv.get('source') or pv.get('basis') or '')
    return ''


def merge(baseline_tree, patches, out_tree, tag, model_id=None, log=print):
    """baseline scripts tree + patches -> out_tree/schedules (COMPLETED) + schedules_original + completion.json.
    Returns the completion dict (before the build; verify_completed adds the build results / MAGENTA)."""
    B = Baseline(baseline_tree)
    os.makedirs(out_tree, exist_ok=True)
    so = os.path.join(out_tree, 'schedules_original')
    if os.path.abspath(so) != os.path.abspath(B.sched):
        if os.path.exists(so):
            shutil.rmtree(so)
        shutil.copytree(B.sched, so)
    sched_out = os.path.join(out_tree, 'schedules')
    if os.path.abspath(sched_out) != os.path.abspath(B.sched):
        if os.path.exists(sched_out):
            shutil.rmtree(sched_out)
        shutil.copytree(B.sched, sched_out)

    parts = [dict(p) for p in B.parts]
    by_id = {p['part_id']: p for p in parts}
    base_ids = set(by_id)
    solids = [dict(s) for s in B.solids]
    cuts = [dict(c) for c in B.cuts]
    openings = [dict(o) for o in B.openings]
    paths = copy.deepcopy(B.paths)
    exact = collections.OrderedDict()
    for ln in B.exact_lines:
        r = json.loads(ln)
        exact[r['part_id']] = ln if ln.endswith('\n') else ln + '\n'
    rows = Rows({r['profile_id'] for r in B.profiles})
    info = collections.OrderedDict()           # part_id -> completion entry
    removed, warnings, inputs = [], [], {}
    resolved = set()                           # (part_id, category)
    resolved_all = set()                       # part ids whose every flag is resolved
    superseded = set()
    flags = {pid: e for pid, e in (B.issues.get('parts') or {}).items()}

    def entry(pid, status):
        e = info.get(pid)
        if e is None:
            p = by_id.get(pid, {})
            e = info[pid] = collections.OrderedDict(colour='GREY', status=status, name=p.get('name', ''), ops=[],
                                                    tracks=[], colours=[], provenance=[], resolves=[], where='',
                                                    bbox=None, target=None, kind=[])
        elif e['status'] in ('unchanged', 'accepted') and status not in ('unchanged', 'accepted'):
            e['status'] = status
        return e

    def body_ids(pid):
        return [s['solid_id'] for s in solids if s['part_id'] == pid and s['role'] == 'body']

    def drop_geometry(pid):
        """the part's solids (and the tools only they use), cuts, openings, exact record"""
        nonlocal solids, cuts, openings
        mine = {s['solid_id'] for s in solids if s['part_id'] == pid}
        cuts = [c for c in cuts if c['solid_id'] not in mine]
        openings = [o for o in openings if o['part_id'] != pid]
        solids = [s for s in solids if s['part_id'] != pid]
        for sid in mine:
            paths.pop(sid, None)
        exact.pop(pid, None)

    def place(g, row, pid, oid, take_fields):
        """GEOM -> rows of part `pid` (row = its parts.csv row, geometry column set here)"""
        if g['kind'] == 'faceted':
            row['geometry'] = 'exact'
            exact[pid] = json.dumps(faceted_record(g, pid), separators=(',', ':')) + '\n'
        elif g['kind'] == 'schedule_part':
            prow, rec = copy_schedule_part(g, rows, pid, f'{oid}:geom')
            row['geometry'] = prow.get('geometry') or 'parametric'      # built as the pipeline verified it
            if take_fields:
                for k2 in PART_FIELDS:
                    if k2 not in ('part_id', 'geometry', 'note') and prow.get(k2):
                        row[k2] = prow[k2]
            if rec is not None:
                exact[pid] = json.dumps(rec, separators=(',', ':')) + '\n'
        else:
            row['geometry'] = 'completion'
            geom_rows(g, rows, pid, f'{oid}:geom')

    for path, P in patches:
        inputs[f"{P.get('track')}/{os.path.basename(path)}"] = (sha256_file(path) if os.path.exists(path) else
                                                                 hashlib.sha256(json.dumps(P, sort_keys=True).encode()).hexdigest())
        errs = validate_patch(P, tag, set(by_id))
        if errs:
            raise ValueError(f'{path}: invalid patch:\n  ' + '\n  '.join(errs[:30]))
        tr = P['track']
        for op in P['ops']:
            o, oid, col = op['op'], f"{tr}:{op['id']}", op.get('colour')
            pv = dict(op.get('provenance') or {}, track=tr, op=oid, colour=col)
            for s in op.get('supersedes') or []:
                superseded.add(s)
            res = list(op.get('resolves') or [])
            if o in ('replace_part', 'add_cuts', 'replace_cuts', 'accept') and not op.get('resolves'):
                resolved_all.add(op['part_id'])
            for r in res:
                resolved.add((r.get('part_id'), r.get('category')))
            if o in ('add_part', 'marker'):
                pid = (op.get('part') or {}).get('part_id') or new_part_id(tr, op['id'])
                row = {k: '' for k in PART_FIELDS}
                row.update({k: str(v) for k, v in (op.get('part') or {}).items() if k in PART_FIELDS})
                row['part_id'] = pid
                if o == 'marker':
                    g = {'kind': 'box', 'origin': sub(vec(op['point']), [float(op.get('size', 100)) / 2] * 3),
                         'x_dir': [1, 0, 0], 'y_dir': [0, 1, 0], 'size': [float(op.get('size', 100))] * 3}
                else:
                    g = op['geometry']
                row['note'] = ascii_text(f"completion {tr}:{op['id']}", 200)
                parts.append(row)
                by_id[pid] = row
                place(g, row, pid, oid, take_fields=not op.get('part'))
                e = entry(pid, 'marker' if o == 'marker' else 'added')
                e['bbox'] = bbox_of(geom_points(g))
            elif o == 'replace_part':
                pid = op['part_id']
                drop_geometry(pid)
                gone = {s['solid_id'] for s in rows.solids if s['part_id'] == pid}
                rows.solids = [s for s in rows.solids if s['part_id'] != pid]
                rows.cuts = [c for c in rows.cuts if c['solid_id'] not in gone]
                rows.openings = [x for x in rows.openings if x['part_id'] != pid]
                for sid in gone:
                    rows.paths.pop(sid, None)
                g = op['geometry']
                row = by_id[pid]
                for k2, v in (op.get('part') or {}).items():
                    if k2 in PART_FIELDS and k2 != 'part_id':
                        row[k2] = str(v)
                place(g, row, pid, oid, take_fields=False)
                e = entry(pid, 'replaced')
                e['bbox'] = bbox_of(geom_points(g))
            elif o in ('add_cuts', 'replace_cuts'):
                pid = op['part_id']
                if o == 'replace_cuts':
                    rc = set(op.get('remove_cut_ids') or [])
                    ro = set(op.get('remove_opening_ids') or [])
                    have_c = {c['cut_id'] for c in cuts if c['solid_id'] in {s['solid_id'] for s in solids if s['part_id'] == pid}}
                    have_o = {x['opening_id'] for x in openings if x['part_id'] == pid}
                    if rc - have_c or ro - have_o:
                        raise ValueError(f'{path} {oid}: cut / opening ids not on part {pid}: '
                                         f'{sorted(rc - have_c) + sorted(ro - have_o)}')
                    cuts = [c for c in cuts if c['cut_id'] not in rc]
                    openings = [x for x in openings if x['opening_id'] not in ro]
                if by_id[pid].get('geometry') == 'exact':
                    raise ValueError(f'{path} {oid}: part {pid} is faceted (exact): give replace_part with its geometry')
                targets = op.get('solid_ids') or body_ids(pid) + [s['solid_id'] for s in rows.solids
                                                                  if s['part_id'] == pid and s['role'] == 'body']
                if not targets:
                    raise ValueError(f'{path} {oid}: part {pid} has no body solid to cut')
                for sid in targets:
                    for j, c in enumerate(op.get('cuts') or []):
                        cut_rows(c, rows, pid, sid, f'{oid}:{sid}:cut{j}')
                entry(pid, 'modified')
            elif o == 'set_fields':
                pid = op['part_id']
                for k2, v in (op.get('fields') or {}).items():
                    if k2 in PART_FIELDS and k2 not in ('part_id', 'geometry'):
                        by_id[pid][k2] = str(v)
                e = entry(pid, 'metadata')
                e.setdefault('metadata', []).append({k2: str(v) for k2, v in (op.get('fields') or {}).items()})
            elif o == 'accept':
                entry(op['part_id'], 'accepted')
            elif o == 'remove_part':
                pid = op['part_id']
                drop_geometry(pid)
                parts = [p for p in parts if p['part_id'] != pid]
                removed.append({'part_id': pid, 'name': by_id[pid].get('name', ''), 'op': oid, 'provenance': pv})
                by_id.pop(pid)
                info.pop(pid, None)
                continue
            pid = op.get('part_id') or (op.get('part') or {}).get('part_id') or new_part_id(tr, op['id'])
            e = info[pid]
            e['ops'].append(oid)
            if tr not in e['tracks']:
                e['tracks'].append(tr)
            if col:
                e['colours'].append(col)
            e['provenance'].append(pv)
            e['resolves'] += res
            e['kind'].append(o)
            if op.get('where'):
                e['where'] = op['where']
            if op.get('target'):
                e['target'] = op['target']

    # ---- baseline RED entries not superseded (missing_parts.json): schedule parts are in the schedules already
    for m in (B.missing.get('parts') or []):
        mid = f"missing:{m.get('id')}"
        g = m.get('geometry') or {}
        if mid in superseded or (g.get('kind') == 'schedule_part' and f"missing:{g.get('part_id')}" in superseded):
            continue
        if g.get('kind') == 'schedule_part':
            pid = g['part_id']
            if pid in by_id:
                e = entry(pid, 'restored')
                e['colours'].append('GREEN')
                e['provenance'].append({'what': 'part present in the source, missing from the delivered STEP: built from '
                                                'its source record', 'source': m.get('source_ref') or 'source IFC',
                                        'track': 'integrate', 'op': mid, 'colour': 'GREEN'})
            continue
        # recorded geometry (an envelope / prism / bar) or a marker: drawn, but not claimed exact
        kind = g.get('kind')
        conv = None
        if kind == 'prism_world':
            conv = {'kind': 'prism', 'outline_world': g['outline_world'], 'normal': g['normal'],
                    'thickness': g['thickness'], 'offset': g.get('offset', -float(g['thickness']) / 2.0)}
        elif kind == 'cylinder':
            conv = {'kind': 'cylinder', 'start': g['start'], 'end': g['end'], 'radius': g['radius']}
        elif kind == 'profile':
            conv = {'kind': 'profile_extrusion', 'profile': g['profile'], 'start': g['start'], 'end': g['end'],
                    'x_dir': g.get('x_dir')}
        elif kind == 'cylinders':
            conv = {'kind': 'compound', 'items': [{'kind': 'cylinder', 'start': c['start'], 'end': c['end'],
                                                   'radius': c['radius']} for c in g['items']]}
        pid = new_part_id('integrate', mid)
        ev = m.get('evidence') or {}
        row = {k: '' for k in PART_FIELDS}
        row.update(part_id=pid, ifc_class='IfcBuildingElementProxy', role='other',
                   name=ascii_text(ev.get('name') or m.get('source_ref') or mid, 120),
                   geometry='completion', note=ascii_text(f'completion integrate:{mid}', 200))
        if conv is not None:
            try:
                check_geom(conv)
                geom_rows(conv, rows, pid, f'integrate:{mid}:geom')
                colour, status = 'MAGENTA', 'not_fixed'
                what = (f"{m.get('reason') or 'missing from the delivered STEP'}: drawn from the geometry the source "
                        f"records ({kind}); not proven to be the exact part - no track completed it")
            except ValueError as ex:
                conv = None
                warnings.append(f'{mid}: recorded geometry unusable ({ex}); marker instead')
        if conv is None:
            pts = []
            for key in ('at', 'start', 'end', 'lo', 'hi', 'origin'):
                if isinstance(g.get(key), list) and len(g[key]) == 3 and not isinstance(g[key][0], list):
                    pts.append(vec(g[key]))
            if not pts:
                warnings.append(f'{mid}: no position recorded; not drawn')
                continue
            c = [sum(p[i] for p in pts) / len(pts) for i in range(3)]
            geom_rows({'kind': 'box', 'origin': sub(c, [50, 50, 50]), 'x_dir': [1, 0, 0], 'y_dir': [0, 1, 0],
                       'size': [100, 100, 100]}, rows, pid, f'integrate:{mid}:marker')
            colour, status = 'RED', 'marker'
            what = f"{m.get('reason') or 'missing'}: only its position is known (marker)"
        parts.append(row)
        by_id[pid] = row
        e = entry(pid, status)
        e['colours'].append(colour)
        e['provenance'].append({'what': what, 'source': m.get('source_ref') or '', 'track': 'integrate', 'op': mid,
                                'colour': colour, 'evidence': {'category': m.get('category')}})
        e['bbox'] = bbox_of(geom_points(conv)) if conv else None

    # ---- unresolved baseline flags -> MAGENTA (honest: not fixed)
    unresolved = []
    for pid, fe in flags.items():
        if pid not in by_id:
            continue
        for fl in fe.get('flags') or []:
            if fl.get('colour') not in FLAG_FIX_COLOURS:
                continue
            if pid in resolved_all or (pid, fl.get('category')) in resolved:
                continue
            unresolved.append({'part_id': pid, 'category': fl.get('category'), 'colour_was': fl.get('colour'),
                               'reason': fl.get('reason')})
    # baseline parts our script did not rebuild to 'match' and nobody replaced
    for pid, v in B.verification.items():
        if pid in by_id and v.get('status') != 'match' and pid not in resolved_all and \
                not any(u['part_id'] == pid for u in unresolved) and 'replaced' != (info.get(pid) or {}).get('status'):
            unresolved.append({'part_id': pid, 'category': 'our_script_' + v.get('status', '?').lower(),
                               'colour_was': 'PURPLE', 'reason': f"our rebuild: {v.get('status')}"})
    for u in unresolved:
        e = entry(u['part_id'], 'not_fixed')
        e['colours'].append('MAGENTA')
        e['provenance'].append({'what': f"NOT FIXED: {u['reason']}", 'track': 'integrate', 'op': 'unresolved:' +
                                str(u['category']), 'colour': 'MAGENTA', 'evidence': {'baseline_flag': u['category']}})

    # ---- conflicts: one part, ops of different tracks in different colours (the record shows both; the weakest wins)
    conflicts = []
    for pid, e in info.items():
        byt = collections.defaultdict(set)
        for x in e['provenance']:
            if x.get('track') not in (None, 'integrate') and x.get('colour'):
                byt[x['track']].add(x['colour'])
        if len(byt) > 1 and len(set().union(*byt.values())) > 1:
            conflicts.append({'part_id': pid, 'tracks': {k: sorted(v) for k, v in byt.items()},
                              'what': [str(x.get('what'))[:160] for x in e['provenance'] if x.get('track') in byt]})
    # ---- colour + label per part
    for pid, e in info.items():
        cols = set(e['colours'])
        if e['status'] == 'accepted' and not cols:
            e['colour'] = 'GREY'
        else:
            e['colour'] = weakest(cols) if cols else 'GREY'
        fe = flags.get(pid) or {}
        if not e['where'] and fe.get('where'):
            e['where'] = fe['where']
        if not e['bbox'] and fe.get('bbox'):
            e['bbox'] = fe['bbox']
        pv = [x for x in e['provenance'] if x.get('colour') == e['colour']] or e['provenance']
        what = '; '.join(dict.fromkeys(str(x.get('what', '')) for x in pv))
        basis = '; '.join(dict.fromkeys(short_basis(x, e['colour']) for x in pv if short_basis(x, e['colour'])))
        e['summary'] = ascii_text(f'{what} [{basis}]' if basis else what, 600)
        p = by_id.get(pid, {})
        if e['colour'] in ('GREEN', 'BLUE', 'AMBER') and '[approx:' in (p.get('name') or ''):
            e['name_was'] = p['name']                   # the converter's approx tag no longer applies: every flag resolved
            p['name'] = re.sub(r'\s*\[approx:[^\]]*\]', '', p['name']).strip() or p['name']
        e['name'] = p.get('name', e['name'])
        e['label'] = label_for(e['colour'], e['summary'], f"{pid} {e['name']}".strip())

    # ---- write the completed schedules (a file nothing changed keeps its baseline bytes)
    def put_csv(name, fields, new_rows, old_rows):
        if new_rows != old_rows:
            write_csv(os.path.join(sched_out, name), fields, new_rows)
    put_csv('parts.csv', B.part_fields or PART_FIELDS, parts, B.parts)
    put_csv('profiles.csv', B.prof_fields or PROFILE_FIELDS, B.profiles + [rows.profiles[k] for k in sorted(rows.profiles)],
            B.profiles)
    put_csv('solids.csv', B.solid_fields or SOLID_FIELDS, solids + rows.solids, B.solids)
    put_csv('cuts.csv', B.cut_fields or CUT_FIELDS, cuts + rows.cuts, B.cuts)
    put_csv('openings.csv', B.open_fields or ['opening_id', 'part_id', 'opening_guid', 'tool_solids'],
            openings + rows.openings, B.openings)
    if rows.outlines:
        outl = dict(B.outlines)
        outl.update(rows.outlines)
        json.dump(outl, open(os.path.join(sched_out, 'profile_outlines.json'), 'w'))
    if rows.boundaries:
        bnd = dict(B.boundaries)
        bnd.update(rows.boundaries)
        json.dump(bnd, open(os.path.join(sched_out, 'cut_boundaries.json'), 'w'))
    allp = dict(paths)
    allp.update(rows.paths)
    pj = os.path.join(sched_out, 'paths.json')
    if allp != B.paths:
        if allp:
            json.dump(allp, open(pj, 'w'))
        elif os.path.exists(pj):
            os.remove(pj)
    new_exact = [ln for pid, ln in exact.items() if pid in by_id]
    old_exact = [ln if ln.endswith('\n') else ln + '\n' for ln in B.exact_lines]
    if new_exact != old_exact:
        with open(os.path.join(sched_out, 'exact_geometry.jsonl'), 'w', encoding='utf-8') as fh:
            fh.writelines(new_exact)

    # untouched-row fingerprint: per baseline part its rows (to prove untouched parts are byte-identical)
    def fp(pid, sol, cu, op_, ex):
        mine = sorted(s['solid_id'] for s in sol if s['part_id'] == pid)
        h = hashlib.sha256()
        h.update(json.dumps([by_id.get(pid) if pid in by_id else None], sort_keys=True).encode())
        for s in sorted((x for x in sol if x['part_id'] == pid), key=lambda x: x['solid_id']):
            h.update(json.dumps(s, sort_keys=True).encode())
        for c in sorted((x for x in cu if x['solid_id'] in mine), key=lambda x: x['cut_id']):
            h.update(json.dumps(c, sort_keys=True).encode())
        for x in sorted((x for x in op_ if x['part_id'] == pid), key=lambda x: x['opening_id']):
            h.update(json.dumps(x, sort_keys=True).encode())
        h.update((ex.get(pid) or '').encode())
        return h.hexdigest()

    counts = collections.Counter()
    for p in parts:
        counts[(info.get(p['part_id']) or {}).get('colour', 'GREY')] += 1
    comp = collections.OrderedDict(
        schema=OUT_SCHEMA, version=VERSION, tag=tag, model_id=model_id or B.issues.get('model_id'),
        model_name=B.model_name, step_source=B.issues.get('step_source'),
        delivered=B.issues.get('delivered'),
        colours={c: list(PALETTE[c][0]) for c in COLOURS},
        prefix={c: PALETTE[c][1] for c in COLOURS},
        meaning={c: PALETTE[c][3] for c in COLOURS},
        precedence=WEAKEST_FIRST,
        counts={c: counts.get(c, 0) for c in COLOURS},
        totals=dict(parts=len(parts), baseline_parts=len(B.parts),
                    by_status=dict(collections.Counter(e['status'] for pid, e in info.items() if pid in by_id)),
                    removed=len(removed)),
        parts=collections.OrderedDict((pid, e) for pid, e in info.items() if pid in by_id and
                                      (e['colour'] != 'GREY' or e['ops'] or e['status'] != 'unchanged')),
        removed=removed, unresolved=unresolved, conflicts=conflicts, warnings=warnings, inputs=inputs,
        baseline=dict(tree=os.path.basename(baseline_tree.rstrip('/')),
                      issues_counts=(B.issues.get('counts') or {}).get('rebuild'),
                      parts=len(B.parts)),
        untouched=None, build=None)
    # untouched parts: rows identical to the baseline (checked here as text; the build check is in verify_completed)
    touched = set(info) | {r['part_id'] for r in removed}
    untouched_ids = [p['part_id'] for p in B.parts if p['part_id'] not in touched]
    bsol, bcut, bop = B.solids, B.cuts, B.openings
    bex = {json.loads(ln)['part_id']: (ln if ln.endswith('\n') else ln + '\n') for ln in B.exact_lines}
    bad = []
    by_base = {p['part_id']: p for p in B.parts}
    for pid in untouched_ids:
        a = fp(pid, solids + rows.solids, cuts + rows.cuts, openings + rows.openings, exact)
        saved = by_id.get(pid)
        by_id[pid] = by_base[pid]
        b = fp(pid, bsol, bcut, bop, bex)
        by_id[pid] = saved
        if a != b:
            bad.append(pid)
    comp['untouched'] = dict(n=len(untouched_ids), rows_identical=len(untouched_ids) - len(bad), rows_differ=bad[:50])
    json.dump(comp, open(os.path.join(sched_out, 'completion.json'), 'w', encoding='utf-8'), indent=1)
    log(f"[{tag}] merged {len(patches)} patch(es): parts {len(B.parts)} -> {len(parts)}; "
        + ', '.join(f'{c} {comp["counts"][c]}' for c in COLOURS)
        + f"; unresolved flags {len(unresolved)}; untouched rows identical {comp['untouched']['rows_identical']}"
          f"/{len(untouched_ids)}")
    return comp
