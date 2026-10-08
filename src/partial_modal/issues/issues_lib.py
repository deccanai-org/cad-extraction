"""issues_lib - colour-coded issue models of a converted steel model (shared by every model's build_issues_model.py).

Two ways to show where a delivered STEP is not perfect, both driven by the model's schedules/issues.json and
schedules/missing_parts.json (written by the pipeline's issue maker):

  rebuild mode (default)   every part rebuilt from the schedules with steelbuild (exactly as build_model.py builds it),
                           each part coloured, the parts the conversion dropped added in RED, one STEP folder per colour
  delivered mode           the delivered STEP itself, edited as TEXT: only PRODUCT / occurrence names change and colour
                           styling is appended; every geometry entity stays byte-identical (the file stays small), and the
                           RED parts are appended as new products (from the MISSING_parts_only STEP)

Colours (COLOUR_RGB values written to the STEP, as every viewer shows them):
  GREY    fine
  RED     MISSING: dropped by the conversion; drawn ONLY from geometry the SOURCE records (an IFC product, a DB1 record's
          outline + thickness, a rod's axis + diameter, a section named in the source along its recorded axis);
          a labelled marker where the source records a position but no size
  ORANGE  APPROX: approximated by the converter (a stand-in, a nominal size, a cut or fitting not applied, ...)
  YELLOW  CHECK: suspicious (split into pieces, duplicated, open surfaces, ...)
  PURPLE  OUR-SCRIPT-NOT-PERFECT: our build123d script does not rebuild this part to 'match' yet
One colour per part, by precedence RED > YELLOW > ORANGE > PURPLE > GREY (as the hand-made sample overlays: a problem
of the delivered STEP shows before a shortfall of our own script); the part's label lists every reason, so a part our
script also fails on says so in its name.

Deterministic: the same inputs give byte-identical files (rebuild mode: the STEP header time stamp is fixed to the
delivered STEP's own time stamp; delivered mode keeps the delivered header time). Headless; needs build123d only.
"""
from __future__ import annotations

import collections
import gzip
import hashlib
import json
import math
import os
import re
import sys

VERSION = 'pmp-issues 1.1'
COLOURS = collections.OrderedDict([
    ('GREY', (0.78, 0.78, 0.78)),
    ('RED', (0.9, 0.05, 0.05)),
    ('ORANGE', (1.0, 0.55, 0.0)),
    ('YELLOW', (1.0, 0.9, 0.0)),
    ('PURPLE', (0.6, 0.15, 0.85)),
])
PRECEDENCE = ['RED', 'YELLOW', 'ORANGE', 'PURPLE', 'GREY']
PREFIX = {'RED': 'MISSING', 'PURPLE': 'OUR-SCRIPT-NOT-PERFECT', 'YELLOW': 'CHECK', 'ORANGE': 'APPROX', 'GREY': ''}
FOLDER = {'GREY': 'GREY - fine', 'RED': 'RED - MISSING from the delivered STEP (drawn from the source records)',
          'ORANGE': 'ORANGE - APPROX: approximated by the converter', 'YELLOW': 'YELLOW - CHECK: suspicious',
          'PURPLE': 'PURPLE - our build123d script does not rebuild these perfectly yet'}
LABEL_MAX = 300
FIXED_TIME = '2000-01-01T00:00:00'


# ======================================================================================== small helpers
def ascii_text(s, limit=None):
    """printable ASCII only (non-ASCII -> '?'), no backslash (STEP escape char), whitespace collapsed"""
    s = ''.join(ch if 32 <= ord(ch) < 127 else ('?' if ord(ch) >= 127 else ' ') for ch in str(s or ''))
    s = ' '.join(s.replace('\\', '/').split())
    if limit and len(s) > limit:
        s = s[:limit - 3].rstrip() + '...'
    return s


def step_str(s, limit=LABEL_MAX):
    """a STEP string literal"""
    return "'" + ascii_text(s, limit).replace("'", "''") + "'"


def fnum(v):
    """deterministic STEP REAL"""
    if abs(v) < 5e-10:
        return '0.'
    s = ('%.6f' % v).rstrip('0')
    return s if not s.endswith('.') else s


def resolve_colour(colours):
    """one colour from a set of flag colours, by precedence"""
    for c in PRECEDENCE:
        if c in colours:
            return c
    return 'GREY'


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 22), b''):
            h.update(b)
    return h.hexdigest()


def load_json(path, default=None):
    if not path or not os.path.exists(path):
        return default
    op = gzip.open if path.endswith('.gz') else open
    with op(path, 'rt', encoding='utf-8') as f:
        return json.load(f)


def label_for(entry, base_name, part_id=None, with_id=False):
    """the product name shown for a flagged part: '<PREFIX> <reasons> | <name> [<id>]'"""
    if not entry or entry.get('colour', 'GREY') == 'GREY':
        return base_name
    reasons = '; '.join(entry.get('reasons') or [])
    tail = ascii_text(base_name, 120)
    if with_id and part_id and part_id not in tail:
        tail += f' [{part_id}]'
    head = ascii_text(f"{PREFIX[entry['colour']]} {reasons}".strip(), LABEL_MAX - len(tail) - 3)
    return f'{head} | {tail}'


# ======================================================================================== sds2 instance ids
_B64 = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$'


def ifc_guid(hex32):
    bs = [int(hex32[i:i + 2], 16) for i in range(0, 32, 2)]

    def b64(v, n):
        return ''.join(_B64[(v >> (6 * i)) & 63] for i in reversed(range(n)))
    return b64(bs[0], 2) + ''.join(b64((bs[i] << 16) + (bs[i + 1] << 8) + bs[i + 2], 4) for i in range(1, 16, 3))


def sds2_guid(salt, label, k):
    """the GlobalId the SDS/2 IFC emitter and the pipeline's delivered reader give an instance (sds2label.guid/key)"""
    key = label.strip() if not k else '%s\x00%d' % (label.strip(), k)
    return ifc_guid(hashlib.sha256((salt + '|' + key).encode('utf-8')).hexdigest()[:32])


# ======================================================================================== STEP text (ISO 10303-21)
_START = re.compile(rb'(?:^|;)[ \t\r\n]*(#(\d+)[ \t\r\n]*=[ \t\r\n]*)', re.M)
_TYPE = re.compile(rb'\(?[ \t\r\n]*([A-Z][A-Z0-9_]*)')
_STR = re.compile(r"'(?:[^']|'')*'")
_REF = re.compile(r'#(\d+)')
STYLABLE = {'FACETED_BREP', 'MANIFOLD_SOLID_BREP', 'BREP_WITH_VOIDS', 'SHELL_BASED_SURFACE_MODEL', 'MAPPED_ITEM',
            'FACE_BASED_SURFACE_MODEL', 'GEOMETRIC_CURVE_SET', 'TESSELLATED_SHELL', 'TESSELLATED_SOLID',
            'TRIANGULATED_FACE_SET', 'COMPLEX_TRIANGULATED_FACE_SET', 'GEOMETRIC_SET'}
REP_TYPES = {'SHAPE_REPRESENTATION', 'ADVANCED_BREP_SHAPE_REPRESENTATION', 'FACETED_BREP_SHAPE_REPRESENTATION',
             'MANIFOLD_SURFACE_SHAPE_REPRESENTATION', 'GEOMETRICALLY_BOUNDED_SURFACE_SHAPE_REPRESENTATION',
             'GEOMETRICALLY_BOUNDED_WIREFRAME_SHAPE_REPRESENTATION', 'EDGE_BASED_WIREFRAME_SHAPE_REPRESENTATION',
             'TESSELLATED_SHAPE_REPRESENTATION', 'SHAPE_REPRESENTATION_WITH_PARAMETERS'}


def strings_of(body):
    return [s[1:-1].replace("''", "'").replace('\r', '').replace('\n', '') for s in _STR.findall(body)]


def refs_of(body):
    return [int(x) for x in _REF.findall(_STR.sub("''", body))]


def replace_refs(body, mapping):
    """replace #refs outside quoted strings: mapping is a dict old -> new or a function"""
    f = mapping if callable(mapping) else (lambda i: mapping.get(i, i))
    out, last = [], 0
    for m in _STR.finditer(body):
        out.append(_REF.sub(lambda r: '#%d' % f(int(r.group(1))), body[last:m.start()]))
        out.append(m.group(0))
        last = m.end()
    out.append(_REF.sub(lambda r: '#%d' % f(int(r.group(1))), body[last:]))
    return ''.join(out)


def replace_string_arg(body, k, new_literal):
    """body with its k-th quoted string (0-based) replaced by new_literal (a quoted STEP string)"""
    ms = list(_STR.finditer(body))
    m = ms[k]
    return body[:m.start()] + new_literal + body[m.end():]


class StepFile:
    """an ISO 10303-21 file read as bytes: statement index, types, bodies, product structure. Nothing is re-encoded."""

    def __init__(self, path):
        self.path = path
        with open(path, 'rb') as f:
            raw = f.read()
        if raw[:2] == b'\x1f\x8b':
            raw = gzip.decompress(raw)
        self.raw = raw
        m = re.search(rb'(^|[\r\n;])[ \t]*DATA[ \t\r\n]*;', raw, re.M)
        if not m:
            raise ValueError(f'{path}: no DATA section')
        self.data0 = m.end()
        e = None
        for e in re.finditer(rb'(^|[\r\n;])[ \t]*ENDSEC[ \t\r\n]*;', raw[self.data0:], re.M):
            pass                                           # the LAST ENDSEC closes DATA
        if e is None:
            raise ValueError(f'{path}: no ENDSEC after DATA')
        self.data1 = self.data0 + e.start() + len(e.group(1))
        self.header = raw[:self.data0]
        self.sha256 = hashlib.sha256(raw).hexdigest()
        self._scan()
        self.S = None

    def _scan(self):
        raw, d0, d1 = self.raw, self.data0, self.data1
        starts, bodies, ids = [], [], []
        for m in _START.finditer(raw, d0, d1):
            starts.append(m.start(1))
            bodies.append(m.end(1))
            ids.append(int(m.group(2)))
        keep = []
        n, i = len(starts), 0
        while i < n:
            j = i
            end = starts[j + 1] if j + 1 < n else d1
            while raw.count(b"'", starts[i], end) % 2 == 1 and j + 1 < n:    # a '#n=' inside a string: merge
                j += 1
                end = starts[j + 1] if j + 1 < n else d1
            keep.append((ids[i], starts[i], bodies[i], end))
            i = j + 1
        self.ids = [k[0] for k in keep]
        self.start = [k[1] for k in keep]
        self.bstart = [k[2] for k in keep]
        self.end = [k[3] for k in keep]
        self.pos = {}
        self.tname = []
        self.by_type = collections.defaultdict(list)
        for k, (eid, s0, b0, e0) in enumerate(keep):
            if eid in self.pos:
                raise ValueError('duplicate entity id #%d' % eid)
            self.pos[eid] = k
            mt = _TYPE.match(raw, b0)
            t = mt.group(1).decode() if mt else ''
            self.tname.append(t)
            self.by_type[t].append(eid)
        self.max_id = max(self.ids) if self.ids else 0

    def type(self, eid):
        return self.tname[self.pos[eid]]

    def body(self, eid):
        k = self.pos[eid]
        b = self.raw[self.bstart[k]:self.end[k]].decode('latin-1').rstrip()
        return b[:-1] if b.endswith(';') else b

    def refs(self, eid):
        return refs_of(self.body(eid))

    def strings(self, eid):
        return strings_of(self.body(eid))

    def complex_types(self, eid):
        b = self.body(eid)
        return re.findall(r'([A-Z][A-Z0-9_]*)\s*\(', _STR.sub("''", b)) if b.lstrip().startswith('(') else [self.type(eid)]

    # ------------------------------------------------------------------ product structure
    def structure(self):
        if self.S is not None:
            return self.S
        prod = {}
        for i in self.by_type['PRODUCT']:
            st = self.strings(i)
            prod[i] = dict(id=i, gid=st[0] if st else '', name=st[1] if len(st) > 1 else '', descr=st[2] if len(st) > 2 else '')
        pdf_prod = {}
        for t in ('PRODUCT_DEFINITION_FORMATION', 'PRODUCT_DEFINITION_FORMATION_WITH_SPECIFIED_SOURCE'):
            for i in self.by_type[t]:
                r = self.refs(i)
                if r:
                    pdf_prod[i] = r[-1]
        pd_prod = {}
        for t in ('PRODUCT_DEFINITION', 'PRODUCT_DEFINITION_WITH_ASSOCIATED_DOCUMENTS'):
            for i in self.by_type[t]:
                r = self.refs(i)
                if r:
                    pd_prod[i] = pdf_prod.get(r[0])
        pds_of = {}
        for i in self.by_type['PRODUCT_DEFINITION_SHAPE']:
            r = self.refs(i)
            if r:
                pds_of.setdefault(r[0], i)
        sdr = collections.defaultdict(list)
        for i in self.by_type['SHAPE_DEFINITION_REPRESENTATION']:
            r = self.refs(i)
            if len(r) >= 2:
                sdr[r[0]].append(r[1])
        nauo = {}
        for i in self.by_type['NEXT_ASSEMBLY_USAGE_OCCURRENCE']:
            st, r = self.strings(i), self.refs(i)
            nauo[i] = dict(id=i, oid=st[0] if st else '', name=st[1] if len(st) > 1 else '',
                           descr=st[2] if len(st) > 2 else '', relating=r[0], related=r[1])
        srr = collections.defaultdict(list)          # plain SRR (no transformation): rep <-> rep of the same product
        for t in ('SHAPE_REPRESENTATION_RELATIONSHIP', 'REPRESENTATION_RELATIONSHIP'):
            for i in self.by_type[t]:
                b = self.body(i)
                if 'TRANSFORMATION' in b:
                    continue
                r = self.refs(i)
                if len(r) >= 2:
                    srr[r[0]].append(r[1])
                    srr[r[1]].append(r[0])
        cdsr_of_nauo = {}                            # NAUO -> (CDSR id, RR id)
        for i in self.by_type['CONTEXT_DEPENDENT_SHAPE_REPRESENTATION']:
            r = self.refs(i)
            if len(r) >= 2:
                pds = r[1]
                if pds in self.pos:
                    pr = self.refs(pds)
                    if pr:
                        cdsr_of_nauo[pr[0]] = (i, r[0])
        styled = collections.defaultdict(list)      # item -> existing styled items
        for t in ('STYLED_ITEM', 'OVER_RIDING_STYLED_ITEM'):
            for i in self.by_type[t]:
                r = self.refs(i)
                if r:
                    styled[r[-1]].append(i)
        self.S = dict(prod=prod, pd_prod=pd_prod, prod_pd={v: k for k, v in pd_prod.items() if v is not None},
                      pds_of=pds_of, sdr=sdr, nauo=nauo, srr=srr, cdsr_of_nauo=cdsr_of_nauo, styled=styled)
        return self.S

    def rep_items(self, rep):
        r = self.refs(rep)
        return r[:-1], r[-1]

    def shape_reps(self, pd):
        S = self.structure()
        out, todo, seen = [], list(S['sdr'].get(S['pds_of'].get(pd), [])), set()
        while todo:
            rp = todo.pop(0)
            if rp in seen or rp not in self.pos:
                continue
            seen.add(rp)
            out.append(rp)
            for other in S['srr'].get(rp, []):
                if other not in seen and self.type(other) in REP_TYPES:
                    todo.append(other)
        return out

    def geometry_items(self, pd):
        items = []
        for rp in self.shape_reps(pd):
            its, _ = self.rep_items(rp)
            for it in its:
                if it in self.pos and self.type(it) in STYLABLE:
                    items.append((rp, it))
        return items

    def parts(self):
        """the leaf parts a viewer lists, document order: free products with geometry ('p<PRODUCT id>') and assembly
        occurrences of products with geometry ('o<NAUO id>')"""
        S = self.structure()
        relating = {n['relating'] for n in S['nauo'].values()}
        related = {n['related'] for n in S['nauo'].values()}
        out = []
        for pid in sorted(S['prod'], key=lambda i: self.pos[i]):
            pd = S['prod_pd'].get(pid)
            if pd is None or pd in related:
                continue
            items = self.geometry_items(pd)
            if not items:
                continue
            p = S['prod'][pid]
            out.append(dict(key='p%d' % pid, product=pid, pd=pd, name=p['name'], label=p['name'] or p['gid'], gid=p['gid'],
                            nauo=None, items=items))
        for nid in sorted(S['nauo'], key=lambda i: self.pos[i]):
            n = S['nauo'][nid]
            pd = n['related']
            pid = S['pd_prod'].get(pd)
            if pid is None:
                continue
            items = self.geometry_items(pd)
            if not items:
                continue                    # a sub-assembly occurrence: its leaves are listed by their own NAUOs
            if pd in relating:
                pass                        # a product with geometry AND components: listed as a part too
            p = S['prod'][pid]
            # the name an OpenCASCADE reader (XCAF) gives a component: the occurrence's description, else its name, else
            # its id; with none of them, the product's name
            occ = n['descr'].strip() or n['name'].strip() or n['oid'].strip()
            out.append(dict(key='o%d' % nid, product=pid, pd=pd, name=p['name'], label=occ or p['name'] or p['gid'],
                            gid=p['gid'], nauo=nid, items=items))
        return out

    def part_ids(self, scheme):
        """[(part dict, part id)] for the leaf parts, ids as the pipeline names them:
           product_id  the PRODUCT id field (IFC GlobalId for STEPs written from an IFC by the z3 converters)
           sds2label   sds2label.guid(sha256 of the file, label + repeat index) of each top-level instance"""
        parts = self.parts()
        if scheme == 'product_id':
            return [(p, p['gid']) for p in parts]
        if scheme == 'sds2label':
            seen = collections.Counter()
            out = []
            for p in parts:
                lab = p['label'].strip()
                k = seen[lab]
                seen[lab] += 1
                out.append((p, sds2_guid(self.sha256, lab, k)))
            return out
        raise ValueError('unknown id scheme ' + scheme)

    def length_unit_mm(self):
        """mm per length unit of the file; None when absent or mixed"""
        found = set()
        for eid in self.by_type.get('LENGTH_UNIT', []) + self.by_type.get('NAMED_UNIT', []) + self.by_type.get('SI_UNIT', []):
            b = re.sub(r'\s', '', self.body(eid))
            if 'LENGTH_UNIT' not in b:
                continue
            if 'SI_UNIT(.MILLI.,.METRE.)' in b:
                found.add(1.0)
            elif 'SI_UNIT($,.METRE.)' in b:
                found.add(1000.0)
            elif 'SI_UNIT(.CENTI.,.METRE.)' in b:
                found.add(10.0)
            elif "'INCH'" in b.upper():
                found.add(25.4)
            elif "'FOOT'" in b.upper():
                found.add(304.8)
            else:
                found.add(None)
        return found.pop() if len(found) == 1 else None


def flatten(body):
    """one-line statement text: line breaks outside strings become blanks, inside strings they are dropped (Part 21)"""
    out, inq = [], False
    for ch in body:
        if ch == "'":
            inq = not inq
            out.append(ch)
        elif ch in '\r\n':
            if not inq:
                out.append(' ')
        else:
            out.append(ch)
    return ''.join(out)


def data_statements(path):
    """the DATA statements of a (small) STEP file as text, each '#id=...' without the trailing ';' (quotes respected)"""
    sf = StepFile(path)
    return sf, [(eid, sf.body(eid)) for eid in sf.ids]


# ======================================================================================== delivered mode
def colour_of_label(label):
    """our colour of a part from the start of its name (the labels this library writes)"""
    for c in PRECEDENCE:
        if PREFIX[c] and label.startswith(PREFIX[c]):
            return c
    return 'GREY'


def colour_by_label(src, out_path, desc):
    """a STEP written by export_step WITHOUT colours, coloured as text by each leaf part's name prefix: deterministic
    styling (OpenCASCADE's own colour writer orders its styled items by memory addresses)"""
    sf = StepFile(src)
    plan = [(p, None, colour_of_label(p['label']), None) for p in sf.parts()]
    return colour_delivered(src, {}, out_path, plan_override=plan, desc=desc)


def colour_delivered(delivered, issues, out_path, missing_step=None, scheme='product_id', title='', plan_override=None,
                     desc=None):
    """the delivered STEP coloured per issues.json (text edit; geometry byte-identical) + the red parts of missing_step
    appended. Returns dict(counts, renamed, cloned, styled, appended_entities, parts)."""
    sf = StepFile(delivered)
    S = sf.structure()
    entries = issues.get('parts') or {}
    # colour + label per leaf part
    plan = []
    if plan_override is not None:
        plan = plan_override
    else:
        for p, pid in sf.part_ids(scheme):
            e = entries.get(pid)
            if e is not None and not e.get('in_delivered', True):
                e = None
            col = e['colour'] if e else 'GREY'
            plan.append((p, pid, col, e))
    new, repl = [], {}
    nid = [sf.max_id + 1]

    def add(body):
        i = nid[0]
        nid[0] += 1
        new.append('#%d=%s;' % (i, body))
        return i

    # presentation styles, one per colour
    psa = {}
    for cname, (r, g, b) in COLOURS.items():
        c = add(f"COLOUR_RGB('{cname.lower()}',{fnum(r)},{fnum(g)},{fnum(b)})")
        fasc = add(f"FILL_AREA_STYLE_COLOUR('',#{c})")
        fas = add(f"FILL_AREA_STYLE('',(#{fasc}))")
        ssfa = add(f"SURFACE_STYLE_FILL_AREA(#{fas})")
        sss = add(f"SURFACE_SIDE_STYLE('',(#{ssfa}))")
        ssu = add(f"SURFACE_STYLE_USAGE(.BOTH.,#{sss})")
        psa[cname] = add(f"PRESENTATION_STYLE_ASSIGNMENT((#{ssu}))")
    # colour per product definition: the colour most of its occurrences have; the others get their own product copy
    by_pd = collections.defaultdict(list)
    for p, pid, col, e in plan:
        by_pd[p['pd']].append((p, col))
    base_col = {}
    for pd, lst in by_pd.items():
        cnt = collections.Counter(c for _, c in lst)
        best = max(cnt.values())
        base_col[pd] = [c for c in PRECEDENCE if cnt.get(c) == best][0]
    styled, cloned, renamed = [], 0, 0
    item_colour = {}
    for pd, col in sorted(base_col.items(), key=lambda kv: sf.pos[kv[0]]):
        for rp, it in sf.geometry_items(pd):
            item_colour[it] = col
    counts = collections.Counter()
    for p, pid, col, e in plan:
        counts[col] += 1
        if p['nauo'] is not None and col != base_col[p['pd']]:
            items = _clone_occurrence(sf, S, p, add, repl)
            cloned += 1
            for it in items:
                item_colour[it] = col
        if e is not None and col != 'GREY':
            lab = label_for(e, p['label'], pid, with_id=True)
            if p['nauo'] is None:
                b = repl.get(p['product']) or sf.body(p['product'])
                repl[p['product']] = replace_string_arg(b, 1, step_str(lab))
                for rp in sf.shape_reps(p['pd']):     # the representation name too, where it repeats the product name
                    st = sf.strings(rp)
                    if st and st[0] and st[0] == p['name']:
                        repl[rp] = replace_string_arg(repl.get(rp) or sf.body(rp), 0, step_str(lab))
            else:
                # the occurrence's name (and its description where it has one: a reader shows that first)
                b = repl.get(p['nauo']) or sf.body(p['nauo'])
                b = replace_string_arg(b, 1, step_str(lab))
                if S['nauo'][p['nauo']]['descr'].strip():
                    b = replace_string_arg(b, 2, step_str(lab))
                repl[p['nauo']] = b
            renamed += 1
    # styled items: re-point existing ones, add the rest
    for it in sorted(item_colour, key=lambda i: sf.pos.get(i, 10 ** 12 + i)):
        col = item_colour[it]
        old = S['styled'].get(it) if it in sf.pos else None
        if old:
            for si in old:
                b = sf.body(si)
                t = sf.type(si)
                repl[si] = f"{t}('{col.lower()}',(#{psa[col]}),#{it})" if t == 'STYLED_ITEM' else b
            continue
        styled.append(add(f"STYLED_ITEM('{col.lower()}',(#{psa[col]}),#{it})"))
    ctxs = collections.Counter()
    for p, pid, col, e in plan:
        for rp, it in p['items'][:1]:
            ctxs[sf.rep_items(rp)[1]] += 1
    ctx = sorted(ctxs.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] if ctxs else None
    if styled:
        add("MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION('',(" + ','.join(f'#{s}' for s in styled) +
            f"),#{ctx})")
    # red parts: the MISSING_parts_only STEP's statements, renumbered after ours
    appended = 0
    n_red = 0
    if missing_step and os.path.exists(missing_step):
        msf = StepFile(missing_step)
        off = nid[0] + 1000 - min(msf.ids)
        for eid in msf.ids:
            new.append('#%d=%s;' % (eid + off, replace_refs(flatten(msf.body(eid)), lambda i: i + off)))
            appended += 1
        n_red = len(msf.parts())
        counts['RED'] += n_red
    # write
    hdr = sf.header.decode('latin-1')
    desc = desc or (f'{title}: delivered STEP coloured by issue (grey ok, red missing, orange approximated, yellow '
                    f'check, purple our script not perfect); geometry unchanged ({VERSION})')
    hdr = re.sub(r"FILE_DESCRIPTION\s*\(\s*\((?:\s*'(?:[^']|'')*'\s*,?)*\s*\)",
                 lambda m: 'FILE_DESCRIPTION((' + step_str(desc, 1000) + ')', hdr, count=1)
    hdr = re.sub(r"(FILE_NAME\s*\(\s*)'(?:[^']|'')*'", lambda m: m.group(1) + step_str(os.path.basename(out_path)), hdr,
                 count=1)
    tmp = out_path + '.tmp'
    raw = sf.raw
    with open(tmp, 'wb') as f:
        f.write(hdr.encode('latin-1'))
        last = sf.data0
        for eid in sorted(repl, key=lambda e: sf.pos[e]):
            k = sf.pos[eid]
            f.write(raw[last:sf.start[k]])
            f.write(('#%d=%s;' % (eid, repl[eid])).encode('latin-1'))
            last = sf.end[k]
        f.write(raw[last:sf.data1])
        if not raw[last:sf.data1].rstrip(b' \t').endswith(b'\n'):
            f.write(b'\n')
        for s in new:
            f.write(s.encode('latin-1') + b'\n')
        f.write(raw[sf.data1:])
    os.replace(tmp, out_path)
    return dict(counts={c: counts.get(c, 0) for c in COLOURS}, renamed=renamed, cloned=cloned, styled=len(styled),
                appended_entities=appended, red_appended=n_red, parts=len(plan), delivered_sha256=sf.sha256)


def _clone_occurrence(sf, S, p, add, repl):
    """give one assembly occurrence its own product (so it can carry its own colour): new PRODUCT .. SHAPE_DEFINITION_
    REPRESENTATION chain whose representation repeats the original's items, each top-level body re-instanced on the SAME
    shells (no geometry duplicated); the occurrence (NAUO) and its placement relationship are re-pointed to the copy.
    Returns the new stylable items."""
    pd = p['pd']
    pid = S['pd_prod'][pd]
    pb = sf.body(pid)
    new_prod = add(pb)
    pdf_old = sf.refs(pd)[0]
    new_pdf = add(replace_refs(sf.body(pdf_old), {pid: new_prod}))
    new_pd = add(replace_refs(sf.body(pd), {pdf_old: new_pdf}))
    pds_old = S['pds_of'][pd]
    new_pds = add(replace_refs(sf.body(pds_old), {pd: new_pd}))
    rep_map, items = {}, []
    for rp in sf.shape_reps(pd):
        its, ctx = sf.rep_items(rp)
        imap = {}
        for it in its:
            if it in sf.pos and sf.type(it) in STYLABLE:
                ni = add(sf.body(it))                  # same body: references the same shells / mapped source
                imap[it] = ni
                items.append(ni)
        rep_map[rp] = add(replace_refs(sf.body(rp), imap))
    for rp_old in S['sdr'].get(pds_old, []):
        if rp_old in rep_map:
            add(f'SHAPE_DEFINITION_REPRESENTATION(#{new_pds},#{rep_map[rp_old]})')
    seen = set()
    for rp in rep_map:                                 # plain SRRs between the product's own representations
        for other in S['srr'].get(rp, []):
            if other in rep_map and (other, rp) not in seen:
                seen.add((rp, other))
                for t in ('SHAPE_REPRESENTATION_RELATIONSHIP', 'REPRESENTATION_RELATIONSHIP'):
                    for i in sf.by_type[t]:
                        b = sf.body(i)
                        r = sf.refs(i)
                        if 'TRANSFORMATION' not in b and len(r) >= 2 and r[0] == rp and r[1] == other:
                            add(replace_refs(b, rep_map))
    nauo = p['nauo']
    repl[nauo] = replace_refs(repl.get(nauo) or sf.body(nauo), {pd: new_pd})
    if nauo in S['cdsr_of_nauo']:
        _, rr = S['cdsr_of_nauo'][nauo]
        repl[rr] = replace_refs(repl.get(rr) or sf.body(rr), rep_map)
    return items


# entity types the delivered mode may rewrite (names / colour styling / re-pointing an occurrence at its own product
# copy); every other original statement must come out byte for byte (after line-break normalisation)
EDITABLE = {'PRODUCT', 'NEXT_ASSEMBLY_USAGE_OCCURRENCE', 'STYLED_ITEM', 'REPRESENTATION_RELATIONSHIP',
            'SHAPE_REPRESENTATION_RELATIONSHIP'} | REP_TYPES


def _styled_rgb(sf, si, depth=0, seen=None):
    """the COLOUR_RGB a STYLED_ITEM's presentation styles lead to, as (r, g, b), or None"""
    seen = seen if seen is not None else set()
    if si in seen or depth > 12 or si not in sf.pos:
        return None
    seen.add(si)
    t = sf.type(si)
    if t == 'COLOUR_RGB':
        nums = re.findall(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?', _STR.sub("''", sf.body(si)))
        return tuple(float(x) for x in nums[-3:]) if len(nums) >= 3 else None
    refs = sf.refs(si)
    if t in ('STYLED_ITEM', 'OVER_RIDING_STYLED_ITEM'):
        refs = refs[:-1]                                  # the last ref is the styled item itself
    for r in refs:
        c = _styled_rgb(sf, r, depth + 1, seen)
        if c is not None:
            return c
    return None


def check_delivered(delivered, coloured, plan_counts):
    """the delivered-mode output checked as text: every original statement present and unchanged except names /
    styling / occurrence re-pointing (EDITABLE), no geometry statement edited, and the colour of every leaf part (from
    its items' styling) one of ours, single, and counted per colour. Returns a dict; 'ok' False on any violation."""
    a, b = StepFile(delivered), StepFile(coloured)
    norm = lambda s: ' '.join(flatten(s).split())
    missing_ids = [i for i in a.ids if i not in b.pos]
    edited = collections.Counter()
    bad_edits = []
    for i in a.ids:
        if i not in b.pos:
            continue
        ba, bb = a.body(i), b.body(i)
        if ba == bb or norm(ba) == norm(bb):
            continue
        t = a.type(i)
        edited[t] += 1
        if t not in EDITABLE or b.type(i) != t:
            bad_edits.append((i, t))
    new_ids = [i for i in b.ids if i not in a.pos]
    S = b.structure()
    item_rgb = {}
    for t in ('STYLED_ITEM', 'OVER_RIDING_STYLED_ITEM'):
        for si in b.by_type.get(t, []):
            r = b.refs(si)
            if r:
                item_rgb.setdefault(r[-1], set()).add(_styled_rgb(b, si))
    counts, mixed, uncoloured = collections.Counter(), [], []
    for p in b.parts():
        cols = set()
        for rp, it in p['items']:
            for rgb in item_rgb.get(it, {None}):
                cols.add(classify_rgb(rgb) if rgb is not None else 'NONE')
        if len(cols) == 1:
            c = cols.pop()
            counts[c] += 1
            if c in ('NONE', 'OTHER'):
                uncoloured.append(p['label'][:80])
        else:
            mixed.append((p['label'][:80], sorted(cols)))
            counts['MIXED'] += 1
    want = {c: plan_counts.get(c, 0) for c in COLOURS}
    got = {c: counts.get(c, 0) for c in COLOURS}
    ok = not missing_ids and not bad_edits and not mixed and not uncoloured and got == want
    return dict(ok=ok, original_statements=len(a.ids), missing=len(missing_ids), edited=dict(sorted(edited.items())),
                bad_edits=bad_edits[:10], n_bad_edits=len(bad_edits), appended=len(new_ids), counts=got, expected=want,
                mixed=mixed[:10], n_mixed=len(mixed), uncoloured=uncoloured[:10], n_uncoloured=len(uncoloured),
                geometry_statements_unchanged=not bad_edits and not missing_ids)


# ======================================================================================== geometry (build123d / OCP)
def _occ():
    from OCP.gp import gp_Pnt, gp_Dir, gp_Vec, gp_Ax2
    return gp_Pnt, gp_Dir, gp_Vec, gp_Ax2


def _v(a):
    return [float(x) for x in a]


def _sub(a, b):
    return [a[i] - b[i] for i in range(3)]


def _add(a, b):
    return [a[i] + b[i] for i in range(3)]


def _mul(a, k):
    return [x * k for x in a]


def _dot(a, b):
    return sum(a[i] * b[i] for i in range(3))


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _norm(a):
    return math.sqrt(_dot(a, a))


def _unit(a):
    n = _norm(a)
    if n < 1e-12:
        raise ValueError('zero-length direction')
    return [x / n for x in a]


def _perp(u):
    a = [1.0, 0.0, 0.0] if abs(u[0]) < 0.9 else [0.0, 1.0, 0.0]
    return _unit(_cross(u, a))


def solid_prism(points, normal, thickness):
    """planar polygon (3D points) extruded by `thickness` along `normal`"""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from build123d import Solid
    gp_Pnt, gp_Dir, gp_Vec, gp_Ax2 = _occ()
    pts = []
    for q in points:
        if not pts or _norm(_sub(q, pts[-1])) > 1e-6:
            pts.append(q)
    if len(pts) > 2 and _norm(_sub(pts[0], pts[-1])) <= 1e-6:
        pts.pop()
    if len(pts) < 3:
        raise ValueError('outline with fewer than 3 distinct points')
    mp = BRepBuilderAPI_MakePolygon()
    for q in pts:
        mp.Add(gp_Pnt(*q))
    mp.Close()
    mf = BRepBuilderAPI_MakeFace(mp.Wire(), True)
    if not mf.IsDone():
        raise ValueError('outline is not a planar face')
    n = _unit(normal)
    sh = BRepPrimAPI_MakePrism(mf.Face(), gp_Vec(*_mul(n, thickness))).Shape()
    return Solid(sh)


def solid_cylinder(start, end, radius):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from build123d import Solid
    gp_Pnt, gp_Dir, gp_Vec, gp_Ax2 = _occ()
    d = _sub(end, start)
    L = _norm(d)
    if L < 1e-6 or radius <= 0:
        raise ValueError('cylinder without length or radius')
    return Solid(BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*start), gp_Dir(*_unit(d))), radius, L).Solid())


def solid_box_centered(centre, size):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from build123d import Solid
    gp_Pnt, gp_Dir, gp_Vec, gp_Ax2 = _occ()
    c = _v(centre)
    h = size / 2.0
    return Solid(BRepPrimAPI_MakeBox(gp_Pnt(c[0] - h, c[1] - h, c[2] - h), size, size, size).Solid())


def solid_bbox_frame(lo, hi, bar=None):
    """a bounding box drawn as its 12 edges (square bars): a MARKER, clearly not a part shape"""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound
    from build123d import Compound, Solid
    gp_Pnt, gp_Dir, gp_Vec, gp_Ax2 = _occ()
    lo, hi = _v(lo), _v(hi)
    ext = [hi[i] - lo[i] for i in range(3)]
    if bar is None:
        bar = max(2.0, min(25.0, max(ext) / 60.0))
    if min(ext) <= 3 * bar:
        sz = [max(e, bar) for e in ext]
        return Solid(BRepPrimAPI_MakeBox(gp_Pnt(*lo), *sz).Solid())
    bld, comp = BRep_Builder(), TopoDS_Compound()
    bld.MakeCompound(comp)
    for ax in range(3):
        o1, o2 = [a for a in range(3) if a != ax]
        for s1 in (lo[o1], hi[o1] - bar):
            for s2 in (lo[o2], hi[o2] - bar):
                p = [0.0, 0.0, 0.0]
                p[ax], p[o1], p[o2] = lo[ax], s1, s2
                sz = [0.0, 0.0, 0.0]
                sz[ax], sz[o1], sz[o2] = ext[ax], bar, bar
                bld.Add(comp, BRepPrimAPI_MakeBox(gp_Pnt(*p), *sz).Solid())
    return Compound(comp)


def solid_obox_frame(origin, x_dir, y_dir, lo, hi, bar=None):
    """a box in its own frame (origin + x / y axes, local lo..hi mm) drawn as its 12 edges: a MARKER for the extent of
    something the source records (e.g. the vertices of a piece the converter rejected), clearly not a part shape"""
    from build123d import Location, Plane, Vector
    x = _unit(_v(x_dir))
    y = _v(y_dir)
    y = _unit(_sub(y, _mul(x, _dot(x, y))))
    z = _cross(x, y)
    frame = solid_bbox_frame(_v(lo), _v(hi), bar)
    return frame.moved(Location(Plane(origin=Vector(*_v(origin)), x_dir=Vector(*x), z_dir=Vector(*z))))


def solid_profile(start, end, x_dir, row, steelbuild_mod=None):
    """a section (a profiles.csv-style row, steelbuild.profile_face) extruded from start to end; the section's x axis
    along x_dir (projected square to the axis)"""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from build123d import Plane, Vector, Location, Solid
    gp_Pnt, gp_Dir, gp_Vec, gp_Ax2 = _occ()
    sb = steelbuild_mod or _steelbuild()
    d = _sub(end, start)
    L = _norm(d)
    z = _unit(d)
    x = _v(x_dir) if x_dir else _perp(z)
    x = _sub(x, _mul(z, _dot(x, z)))
    x = _unit(x) if _norm(x) > 1e-9 else _perp(z)
    face = sb.profile_face(row)
    pl = Plane(origin=Vector(*start), x_dir=Vector(*x), z_dir=Vector(*z))
    placed = face.moved(Location(pl))
    return Solid(BRepPrimAPI_MakePrism(placed.wrapped, gp_Vec(*_mul(z, L))).Shape())


def _steelbuild():
    import steelbuild
    return steelbuild


def build_missing(entry, sched=None, steelbuild_mod=None):
    """one entry of missing_parts.json -> build123d shape (Solid or Compound). Raises on bad geometry."""
    g = entry['geometry']
    k = g['kind']
    if k == 'schedule_part':
        sb = steelbuild_mod or _steelbuild()
        row = next((p for p in sched.parts if p['part_id'] == g['part_id']), None) if sched is not None else None
        if row is None:
            raise ValueError(f"schedule part {g['part_id']} not in schedules/parts.csv")
        solids = sb.build_part(row, sched)
        if not solids:
            raise ValueError(f"schedule part {g['part_id']} built no solid")
        return _one(solids)
    if k == 'prism':
        O, x, y = _v(g['origin']), _unit(_v(g['x'])), _v(g['y'])
        y = _unit(_sub(y, _mul(x, _dot(x, y))))
        n = _unit(_cross(x, y))
        t = float(g['thickness'])
        off = float(g.get('offset', -t / 2.0))
        o = _add(O, _mul(n, off))
        pts = [_add(o, _add(_mul(x, float(q[0])), _mul(y, float(q[1])))) for q in g['outline']]
        return solid_prism(pts, n, t)
    if k == 'prism_world':
        n = _unit(_v(g['normal']))
        t = float(g['thickness'])
        off = float(g.get('offset', -t / 2.0))
        pts = [_add(_v(q), _mul(n, off)) for q in g['outline_world']]
        return solid_prism(pts, n, t)
    if k == 'cylinder':
        return solid_cylinder(_v(g['start']), _v(g['end']), float(g['radius']))
    if k == 'profile':
        return solid_profile(_v(g['start']), _v(g['end']), g.get('x_dir'), g['profile'], steelbuild_mod)
    if k == 'marker':
        return solid_box_centered(_v(g['at']), float(g.get('size', 100.0)))
    if k == 'line_marker':
        return solid_cylinder(_v(g['start']), _v(g['end']), float(g.get('radius', 25.0)))
    if k == 'bbox_frame':
        return solid_bbox_frame(_v(g['lo']), _v(g['hi']))
    if k == 'obox_frame':
        return solid_obox_frame(g['origin'], g['x'], g['y'], g['lo'], g['hi'])
    if k == 'cylinders':
        return _one([solid_cylinder(_v(c['start']), _v(c['end']), float(c['radius'])) for c in g['items']])
    if k == 'markers':
        return _one([solid_box_centered(_v(p), float(g.get('size', 30.0))) for p in g['at']])
    raise ValueError('unknown missing-part geometry kind ' + k)


def part_shape(solids, steelbuild_mod):
    """the shape of one part exactly as steelbuild.write_step writes it into rebuilt_model.step: every solid an own copy
    (steelbuild._own: vertices snapped for the STEP reader), several solids as one compound"""
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound
    from build123d import Compound
    own = [steelbuild_mod._own(s) for s in solids]
    if len(own) == 1:
        return own[0]
    bld, comp = BRep_Builder(), TopoDS_Compound()
    bld.MakeCompound(comp)
    for s in own:
        bld.Add(comp, s.wrapped)
    return Compound(comp)


def _one(solids):
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound
    from build123d import Compound
    if len(solids) == 1:
        return solids[0]
    bld, comp = BRep_Builder(), TopoDS_Compound()
    bld.MakeCompound(comp)
    for s in solids:
        bld.Add(comp, s.wrapped)
    return Compound(comp)


def own_copy(shape, steelbuild_mod=None):
    """an independent copy for the STEP writer (steelbuild._own for solids: vertices snapped for the STEP reader)"""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
    from OCP.TopAbs import TopAbs_SOLID
    from build123d import Solid, Compound
    sb = steelbuild_mod
    w = shape.wrapped
    if w.ShapeType() == TopAbs_SOLID:
        if sb is not None and hasattr(sb, '_own'):
            return sb._own(shape)
        return Solid(BRepBuilderAPI_Copy(w, True, False).Shape())
    return Compound(BRepBuilderAPI_Copy(w, True, False).Shape())


def rgb_color(name):
    from build123d import Color
    r, g, b = COLOURS[name]
    return Color(r, g, b)


def export_coloured(folders, path, title, timestamp=FIXED_TIME):
    """folders: [(colour, [shape with .label])] -> one STEP: a root assembly with one sub-assembly per colour (named
    '<colour folder> (n)'), every leaf in its colour. The header time stamp is fixed (byte-identical re-runs)."""
    from build123d import Compound, export_step
    kids = []
    for col, leaves in folders:
        if not leaves:
            continue
        kids.append(Compound(children=leaves, label=f'{FOLDER[col]} ({len(leaves)})'))
    root = Compound(children=kids, label=ascii_text(title, 200))
    export_uncoloured_then_colour(root, path, title, timestamp)
    return sum(len(v) for _, v in folders)


def export_uncoloured_then_colour(root, path, title, timestamp=FIXED_TIME):
    """export_step without colours (deterministic), header normalised, then every leaf coloured as text by its name"""
    from build123d import export_step
    tmp, tmp2 = path + '.tmp.step', path + '.tmp2.step'
    export_step(root, tmp)
    normalise_header(tmp, tmp2, os.path.basename(path), timestamp)
    colour_by_label(tmp2, path, f'{ascii_text(title, 200)} ({VERSION})')
    os.remove(tmp2)


def normalise_header(src, dst, name, timestamp=FIXED_TIME):
    """FILE_NAME name and time stamp set to fixed values (the only non-deterministic bytes OpenCASCADE writes)"""
    raw = open(src, 'rb').read()
    i = raw.find(b'DATA;')
    hdr = raw[:i].decode('latin-1')
    m = re.search(r"FILE_NAME\s*\(\s*'(?:[^']|'')*'\s*,\s*'[^']*'", hdr)
    if not m:
        raise ValueError('no FILE_NAME in ' + src)
    hdr = hdr[:m.start()] + f"FILE_NAME({step_str(name)},'{timestamp}'" + hdr[m.end():]
    with open(dst + '.part', 'wb') as f:
        f.write(hdr.encode('latin-1'))
        f.write(raw[i:])
    os.replace(dst + '.part', dst)
    if os.path.abspath(src) != os.path.abspath(dst):
        os.remove(src)


# ======================================================================================== read-back (as a viewer reads it)
def readback(path):
    """read a STEP the way OpenCASCADE-based viewers (CAD Assistant) do (XCAF, colours + names) -> list of leaf parts
    [(name, colour name or raw rgb or None)] in tree order"""
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TDocStd import TDocStd_Document
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool, XCAFDoc_ColorTool
    from OCP.TDF import TDF_Label
    from OCP.TDataStd import TDataStd_Name
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.Quantity import Quantity_Color
    try:
        from OCP.TDF import TDF_LabelSequence
    except ImportError:
        from OCP.collections import Sequence_TDF_Label as TDF_LabelSequence
    try:
        from OCP.XCAFDoc import XCAFDoc_ColorType
        CT = (XCAFDoc_ColorType.XCAFDoc_ColorSurf, XCAFDoc_ColorType.XCAFDoc_ColorGen)
    except ImportError:
        from OCP.XCAFDoc import XCAFDoc_ColorSurf, XCAFDoc_ColorGen
        CT = (XCAFDoc_ColorSurf, XCAFDoc_ColorGen)
    doc = TDocStd_Document(TCollection_ExtendedString('XmlOcaf'))
    rd = STEPCAFControl_Reader()
    rd.SetColorMode(True)
    rd.SetNameMode(True)
    if rd.ReadFile(path) != IFSelect_RetDone:
        raise ValueError('cannot read ' + path)
    rd.Transfer(doc)
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())

    def col(lab):
        q = Quantity_Color()
        for t in CT:
            if XCAFDoc_ColorTool.GetColor_s(lab, t, q):
                return (q.Red(), q.Green(), q.Blue())
        return None

    def nm(lab):
        a = TDataStd_Name()
        return a.Get().ToExtString() if lab.FindAttribute(TDataStd_Name.GetID_s(), a) else ''

    def sub_colours(lab):
        subs = TDF_LabelSequence()
        XCAFDoc_ShapeTool.GetSubShapes_s(lab, subs)
        cs = {col(subs.Value(j)) for j in range(1, subs.Length() + 1)}
        return cs

    out = []

    def leaf(lab_inst, lab_ref):
        c = col(lab_inst) or col(lab_ref)
        if c is None:
            cs = sub_colours(lab_ref)
            if len(cs) == 1 and None not in cs:
                c = cs.pop()
            elif cs:
                c = ('mixed', tuple(sorted(str(x) for x in cs)))
        out.append((nm(lab_inst) or nm(lab_ref), c))

    def walk(lab):
        if XCAFDoc_ShapeTool.IsAssembly_s(lab):
            comps = TDF_LabelSequence()
            XCAFDoc_ShapeTool.GetComponents_s(lab, comps, False)
            for j in range(1, comps.Length() + 1):
                c = comps.Value(j)
                ref = TDF_Label()
                XCAFDoc_ShapeTool.GetReferredShape_s(c, ref)
                if XCAFDoc_ShapeTool.IsAssembly_s(ref):
                    walk(ref)
                else:
                    leaf(c, ref)
        else:
            leaf(lab, lab)
    roots = TDF_LabelSequence()
    st.GetFreeShapes(roots)
    for i in range(1, roots.Length() + 1):
        walk(roots.Value(i))
    return out


def _lin(v):
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def classify_rgb(c):
    """raw colour read back -> our colour name ('NONE' if no colour, 'OTHER' if not ours); OpenCASCADE may hand colours
    back as linear RGB, so both encodings are tried"""
    if c is None:
        return 'NONE'
    if isinstance(c, tuple) and c and c[0] == 'mixed':
        return 'MIXED'
    best, bd = None, 1e9
    for name, rgb in COLOURS.items():
        for ref in (rgb, tuple(_lin(x) for x in rgb)):
            d = sum((a - b) ** 2 for a, b in zip(ref, c))
            if d < bd:
                best, bd = name, d
    return best if bd < 2e-3 else 'OTHER'


def readback_counts(path):
    parts = readback(path)
    cnt = collections.Counter(classify_rgb(c) for _, c in parts)
    pref = collections.Counter()
    bad_prefix = []
    for n, c in parts:
        k = classify_rgb(c)
        if k in PREFIX and PREFIX[k]:
            if not n.startswith(PREFIX[k]):
                bad_prefix.append((n[:80], k))
    return dict(parts=len(parts), counts=dict(cnt), label_prefix_mismatch=len(bad_prefix), examples=bad_prefix[:5])
