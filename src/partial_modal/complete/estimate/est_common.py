"""shared helpers for the estimate track (AMBER): baseline tree reading, vector maths, patch / log writers.
Pure python (csv / json / math); geometry is checked on Modal (modal_estimate.py)."""
import csv
import datetime
import hashlib
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
COMPLETE = os.path.dirname(HERE)
ROOT = os.path.dirname(COMPLETE)
sys.path.insert(0, os.path.join(COMPLETE, 'integrate'))
from samples import baseline_tree, jobs  # noqa: E402

INPUTS = os.path.join(HERE, 'inputs')
OUT = os.path.join(HERE, 'out')
SHORT = {'n1_db1_small': 'n1', 'n2_db1_addon': 'n2', 'n3_ifc_approx': 'n3', 'n4_ifc_c2s': 'n4', 'n5_sds2': 'n5'}
IN = 25.4
STEEL_LB_PER_IN3 = 0.2836


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def read_csv(p):
    if not os.path.exists(p):
        return []
    with open(p, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


class Tree:
    """the baseline scripts tree of one sample (read only)"""

    def __init__(self, tag):
        self.tag = tag
        self.job = jobs()[tag]
        self.tree = baseline_tree(tag)
        s = lambda n: os.path.join(self.tree, 'schedules', n)
        self.sched_dir = os.path.join(self.tree, 'schedules')
        self.parts = {r['part_id']: r for r in read_csv(s('parts.csv'))}
        self.profiles = {r['profile_id']: r for r in read_csv(s('profiles.csv'))}
        self.solids = {r['solid_id']: r for r in read_csv(s('solids.csv'))}
        self.cuts = read_csv(s('cuts.csv'))
        self.issues = json.load(open(s('issues.json')))
        self.missing = json.load(open(s('missing_parts.json'))) if os.path.exists(s('missing_parts.json')) else {}
        self.by_part = {}
        for r in self.solids.values():
            self.by_part.setdefault(r['part_id'], []).append(r)
        self.cuts_by_tool = {c['tool_solid_id']: c for c in self.cuts if c.get('tool_solid_id')}
        self.inputs = {}
        for n in ('parts.csv', 'profiles.csv', 'solids.csv', 'cuts.csv', 'issues.json', 'missing_parts.json'):
            if os.path.exists(s(n)):
                self.inputs[os.path.relpath(s(n), ROOT)] = sha256_file(s(n))
        self._exact = None

    def exact(self, pid):
        if self._exact is None:
            self._exact = {}
            p = os.path.join(self.sched_dir, 'exact_geometry.jsonl')
            if os.path.exists(p):
                for ln in open(p, encoding='utf-8'):
                    if ln.strip():
                        d = json.loads(ln)
                        self._exact[d['part_id']] = d
        return self._exact.get(pid)

    def flagged(self, category):
        return [(gid, p) for gid, p in self.issues['parts'].items() if any(f['category'] == category for f in p['flags'])]

    def add_input(self, path):
        self.inputs[os.path.relpath(path, ROOT)] = sha256_file(path)


# ------------------------------------------------------------------ vectors
def V(a):
    return [float(x) for x in a]


def sub(a, b):
    return [a[i] - b[i] for i in range(3)]


def add(a, b):
    return [a[i] + b[i] for i in range(3)]


def mul(a, k):
    return [a[i] * k for i in range(3)]


def dot(a, b):
    return sum(a[i] * b[i] for i in range(3))


def cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def norm(a):
    return math.sqrt(dot(a, a))


def unit(a):
    n = norm(a)
    return [x / n for x in a]


def r6(a):
    return [round(float(x), 6) for x in a]


def solid_frame(r):
    """solids.csv row -> (origin, x axis, z axis, extrusion vector)"""
    g = lambda k: float(r[k] or 0.0)
    return ([g('ox'), g('oy'), g('oz')], [g('xx'), g('xy'), g('xz')], [g('zx'), g('zy'), g('zz')],
            [g('vx'), g('vy'), g('vz')])


# ------------------------------------------------------------------ section outlines (2D, profile_outlines.json style)
def rrect_segments(A, B, r):
    """rounded rectangle centred at 0: half sizes A (x) and B (y), corner radius r (<= min(A, B)); slot = r == min(A,B).
    -> outline {'outer': [SEG...], 'inner': []} with 'L' runs and three-point 'A' arcs, counter-clockwise"""
    c = math.cos(math.pi / 4)
    a, b = A - r, B - r
    segs = []

    def L(p, q):
        if math.dist(p, q) > 1e-9:
            segs.append({'t': 'L', 'p': [[round(p[0], 6), round(p[1], 6)], [round(q[0], 6), round(q[1], 6)]]})

    def Arc(cx, cy, a0):
        p0 = (cx + r * math.cos(a0), cy + r * math.sin(a0))
        pm = (cx + r * math.cos(a0 + math.pi / 4), cy + r * math.sin(a0 + math.pi / 4))
        p1 = (cx + r * math.cos(a0 + math.pi / 2), cy + r * math.sin(a0 + math.pi / 2))
        segs.append({'t': 'A', 'p': [[round(v, 6) for v in p0], [round(v, 6) for v in pm], [round(v, 6) for v in p1]]})

    L((A, -b), (A, b))
    Arc(a, b, 0.0)
    L((a, B), (-a, B))
    Arc(-a, b, math.pi / 2)
    L((-A, b), (-A, -b))
    Arc(-a, -b, math.pi)
    L((-a, -B), (a, -B))
    Arc(a, -b, 3 * math.pi / 2)
    _ = c
    return {'outer': segs, 'inner': []}


def slot_tool(origin, vec, x_dir, dh, sx, sy):
    """a slotted hole tool (Tekla slot: hole dh elongated by sx along the group x and sy along the group y), as a
    profile_extrusion with a POLY rounded-rectangle outline (arcs, never a RECT with r = b/2)"""
    A, B, r = (dh + sx) / 2.0, (dh + sy) / 2.0, dh / 2.0
    return {'kind': 'profile_extrusion', 'profile': {'kind': 'POLY', 'designation': f'BOLT_SLOT_D{dh:g}_X{sx:g}_Y{sy:g}'},
            'outline': rrect_segments(A, B, r), 'start': r6(origin), 'end': r6(add(origin, vec)), 'x_dir': r6(x_dir)}


def L_section_world(heel, u, w, a_leg, b_leg, t):
    """L angle section polygon in world coordinates: heel corner, leg a along u, leg b along w, thickness t"""
    p = lambda s, q: add(heel, add(mul(u, s), mul(w, q)))
    return [p(0, 0), p(a_leg, 0), p(a_leg, t), p(t, t), p(t, b_leg), p(0, b_leg)]


def write_out(tag, patch, log):
    d = os.path.join(OUT, tag)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, 'patch.json'), 'w', encoding='utf-8') as f:
        json.dump(patch, f, indent=1, sort_keys=False)
        f.write('\n')
    with open(os.path.join(d, 'estimate_log.json'), 'w', encoding='utf-8') as f:
        json.dump(log, f, indent=1, sort_keys=False)
        f.write('\n')
    return d


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def new_patch(tree, notes=None):
    return {'schema': 'pmp-completion-patch/1', 'track': 'estimate', 'tag': tree.tag, 'model_id': tree.job['model_id'],
            'generated_by': 'complete/estimate/make_estimates.py', 'generated_at': now(), 'inputs': tree.inputs,
            'ops': [], 'notes': notes or []}


def new_log(tree):
    return {'schema': 'pmp-estimate-log/1', 'tag': tree.tag, 'model_id': tree.job['model_id'],
            'model_folder': tree.job['model_folder'], 'step_source': tree.job['step_source'],
            'generated_by': 'complete/estimate/make_estimates.py', 'generated_at': now(),
            'colour': 'AMBER', 'meaning': 'ESTIMATED: no exact data and no standard - best inference; basis and confidence per entry',
            'confidence_scale': '0..1 = our probability that the estimate matches the real fabricated part within the stated feature '
                                '(rule accuracies are measured where we cite a measurement; otherwise judged, and said so)',
            'estimates': [], 'not_estimated': [], 'summary': {}}
