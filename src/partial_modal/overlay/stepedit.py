"""stepedit.py - read and edit an ISO 10303-21 (STEP AP203/AP214) file as TEXT, without re-exporting geometry.

The overlay never re-exports the delivered model through a CAD kernel (a build123d re-export turns every facet into an
ADVANCED_FACE and makes the file ~10x bigger: sample 1 was 199 MB naive vs 19 MB edited). Instead it:
  * renames PRODUCTs (the names viewers list in the part tree),
  * appends one STYLED_ITEM per geometry item in its part's colour, gathered in one
    MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION (how OpenCASCADE-based viewers such as CAD Assistant read colours),
  * when one instanced product must show two colours (SDS/2 assemblies), gives the odd occurrences their own product copy
    (new PRODUCT chain + new top-level geometry items that share the original shells, so no geometry is duplicated),
  * appends new FACETED_BREP products (the red parts).
Every other byte of the delivered file is copied unchanged.

Statement scanning: a statement starts at '#<id>=' at the start of a line or after ';'. A start found inside a quoted
string (possible in principle) is detected by quote parity and merged back, so names containing ';' or line breaks are safe.
"""
import re, array, collections, hashlib

_START = re.compile(rb'(?:^|;)[ \t\r\n]*(#(\d+)[ \t\r\n]*=[ \t\r\n]*)', re.M)
_TYPE = re.compile(rb'\(?[ \t\r\n]*([A-Z][A-Z0-9_]*)')
_STR = re.compile(r"'(?:[^']|'')*'")
_REF = re.compile(r'#(\d+)')

STYLABLE = {'FACETED_BREP', 'MANIFOLD_SOLID_BREP', 'BREP_WITH_VOIDS', 'SHELL_BASED_SURFACE_MODEL', 'MAPPED_ITEM',
            'FACE_BASED_SURFACE_MODEL', 'GEOMETRIC_CURVE_SET', 'TESSELLATED_SHELL', 'TESSELLATED_SOLID',
            'TRIANGULATED_FACE_SET', 'COMPLEX_TRIANGULATED_FACE_SET'}
REP_TYPES = {'SHAPE_REPRESENTATION', 'ADVANCED_BREP_SHAPE_REPRESENTATION', 'FACETED_BREP_SHAPE_REPRESENTATION',
             'MANIFOLD_SURFACE_SHAPE_REPRESENTATION', 'GEOMETRICALLY_BOUNDED_SURFACE_SHAPE_REPRESENTATION',
             'GEOMETRICALLY_BOUNDED_WIREFRAME_SHAPE_REPRESENTATION', 'EDGE_BASED_WIREFRAME_SHAPE_REPRESENTATION',
             'TESSELLATED_SHAPE_REPRESENTATION', 'SHAPE_REPRESENTATION_WITH_PARAMETERS'}


def strings_of(body):
    """the quoted string arguments of a statement body, '' unescaped, line breaks inside strings removed (Part 21)"""
    return [s[1:-1].replace("''", "'").replace('\r', '').replace('\n', '') for s in _STR.findall(body)]


def refs_of(body):
    """#refs of a statement body, in order, ignoring anything inside quoted strings"""
    return [int(x) for x in _REF.findall(_STR.sub("''", body))]


def replace_refs(body, mapping):
    """replace #refs (outside strings) by mapping[old] -> new"""
    out, last = [], 0
    for m in _STR.finditer(body):
        out.append(_REF.sub(lambda r: '#%d' % mapping.get(int(r.group(1)), int(r.group(1))), body[last:m.start()]))
        out.append(m.group(0))
        last = m.end()
    out.append(_REF.sub(lambda r: '#%d' % mapping.get(int(r.group(1)), int(r.group(1))), body[last:]))
    return ''.join(out)


def q(s):
    """a STEP string literal: ASCII only (non-ASCII -> '?'), backslash -> '/', quotes doubled"""
    s = ''.join(ch if 32 <= ord(ch) < 127 else '?' for ch in s).replace('\\', '/')
    return "'" + s.replace("'", "''") + "'"


def fnum(v):
    """deterministic STEP REAL formatting (always has a '.')"""
    if abs(v) < 5e-7:
        return '0.'
    return ('%.6f' % v).rstrip('0')


class StepFile:
    def __init__(self, path):
        self.path = path
        with open(path, 'rb') as f:
            self.raw = f.read()
        raw = self.raw
        m = re.search(rb'(^|[\r\n;])[ \t]*DATA[ \t\r\n]*;', raw, re.M)
        if not m:
            raise ValueError('no DATA section')
        self.data0 = m.end()
        e = re.search(rb'(^|[\r\n;])[ \t]*ENDSEC[ \t\r\n]*;', raw[self.data0:], re.M)
        self.data1 = self.data0 + (e.start() + len(e.group(1)) if e else len(raw) - self.data0)
        self.header = raw[:self.data0]
        self.sha256 = hashlib.sha256(raw).hexdigest()
        self._scan()

    # ------------------------------------------------------------------ scanning
    def _scan(self):
        raw, d0, d1 = self.raw, self.data0, self.data1
        starts, bodies, ids = [], [], []
        for m in _START.finditer(raw, d0, d1):
            starts.append(m.start(1)); bodies.append(m.end(1)); ids.append(int(m.group(2)))
        # quote parity: a start found inside a string is merged into the previous statement
        keep = []
        n = len(starts)
        i = 0
        merged = 0
        while i < n:
            j = i
            end = starts[j + 1] if j + 1 < n else d1
            while raw.count(b"'", starts[i], end) % 2 == 1 and j + 1 < n:
                j += 1; merged += 1
                end = starts[j + 1] if j + 1 < n else d1
            keep.append((ids[i], starts[i], bodies[i], end))
            i = j + 1
        self.merged_false_starts = merged
        self.ids = array.array('q', (k[0] for k in keep))
        self.start = array.array('q', (k[1] for k in keep))
        self.bstart = array.array('q', (k[2] for k in keep))
        self.end = array.array('q', (k[3] for k in keep))
        self.pos = {}
        tnames, tidx = [], {}
        self.tcode = array.array('i')
        for k, (eid, s0, b0, e0) in enumerate(keep):
            if eid in self.pos:
                raise ValueError('duplicate entity id #%d' % eid)
            self.pos[eid] = k
            mt = _TYPE.match(raw, b0)
            t = mt.group(1).decode() if mt else ''
            c = tidx.get(t)
            if c is None:
                c = tidx[t] = len(tnames); tnames.append(t)
            self.tcode.append(c)
        self.tnames = tnames
        self.by_type = collections.defaultdict(list)
        for k, c in enumerate(self.tcode):
            self.by_type[tnames[c]].append(self.ids[k])
        self.max_id = max(self.ids) if len(self.ids) else 0

    def type(self, eid):
        return self.tnames[self.tcode[self.pos[eid]]]

    def body(self, eid):
        """statement text after '=' up to (not including) the final ';'"""
        k = self.pos[eid]
        b = self.raw[self.bstart[k]:self.end[k]].decode('latin-1').rstrip()
        if b.endswith(';'):
            b = b[:-1]
        return b

    def is_complex(self, eid):
        k = self.pos[eid]
        return self.raw[self.bstart[k]:self.bstart[k] + 1] == b'('

    def refs(self, eid):
        return refs_of(self.body(eid))

    def strings(self, eid):
        return strings_of(self.body(eid))

    # ------------------------------------------------------------------ product structure
    def structure(self):
        """products, product definitions, shapes, representations, assembly occurrences -> self.S (dict of maps)"""
        S = {}
        prod = {}
        for i in self.by_type['PRODUCT']:
            st = self.strings(i)
            prod[i] = dict(id=i, gid=st[0] if st else '', name=st[1] if len(st) > 1 else '', descr=st[2] if len(st) > 2 else '')
        pdf_prod = {i: self.refs(i)[-1] for i in self.by_type['PRODUCT_DEFINITION_FORMATION'] +
                    self.by_type['PRODUCT_DEFINITION_FORMATION_WITH_SPECIFIED_SOURCE']}
        pd_pdf = {}
        for t in ('PRODUCT_DEFINITION', 'PRODUCT_DEFINITION_WITH_ASSOCIATED_DOCUMENTS'):
            for i in self.by_type[t]:
                r = self.refs(i)
                pd_pdf[i] = r[0]
        pd_prod = {pd: pdf_prod.get(f) for pd, f in pd_pdf.items()}
        pds_of = {}                      # definition (PD or NAUO) -> PRODUCT_DEFINITION_SHAPE
        for i in self.by_type['PRODUCT_DEFINITION_SHAPE']:
            r = self.refs(i)
            if r:
                pds_of.setdefault(r[0], i)
        sdr = {}                         # PDS -> [rep]
        for i in self.by_type['SHAPE_DEFINITION_REPRESENTATION']:
            r = self.refs(i)
            if len(r) >= 2:
                sdr.setdefault(r[0], []).append(r[1])
        nauo = {}
        for i in self.by_type['NEXT_ASSEMBLY_USAGE_OCCURRENCE']:
            st = self.strings(i); r = self.refs(i)
            nauo[i] = dict(id=i, oid=st[0] if st else '', name=st[1] if len(st) > 1 else '', relating=r[0], related=r[1])
        # shape_representation_relationship without transformation (links a product's SHAPE_REPRESENTATION to its brep rep)
        srr = collections.defaultdict(list)
        rr_of_cdsr = {}
        for i in self.by_type['SHAPE_REPRESENTATION_RELATIONSHIP'] + self.by_type['REPRESENTATION_RELATIONSHIP']:
            b = self.body(i)
            if 'TRANSFORMATION' in b:
                continue
            r = self.refs(i)
            if len(r) >= 2:
                srr[r[0]].append((i, r[1])); srr[r[1]].append((i, r[0]))
        for i in self.by_type['CONTEXT_DEPENDENT_SHAPE_REPRESENTATION']:
            r = self.refs(i)
            if len(r) >= 2:
                rr_of_cdsr[r[1]] = r[0]          # PDS(of NAUO) -> RR with transformation
        S.update(prod=prod, pd_prod=pd_prod, pds_of=pds_of, sdr=sdr, nauo=nauo, srr=srr, rr_of_cdsr=rr_of_cdsr,
                 prod_pd={v: k for k, v in pd_prod.items() if v is not None})
        self.S = S
        return S

    def rep_items(self, rep):
        """(rep body, item ids, context id)"""
        b = self.body(rep)
        r = refs_of(b)
        return b, r[:-1], r[-1]

    def shape_reps(self, pd):
        """all representations of a product definition: SDR reps + reps linked to them by plain SRR (transitively)"""
        S = self.S
        out, todo = [], list(S['sdr'].get(S['pds_of'].get(pd), []))
        seen = set()
        while todo:
            rp = todo.pop(0)
            if rp in seen or rp not in self.pos:
                continue
            seen.add(rp); out.append(rp)
            for _, other in S['srr'].get(rp, []):
                if other not in seen and self.type(other) in REP_TYPES:
                    todo.append(other)
        return out

    def geometry_items(self, pd):
        """stylable geometry items of a product (directly in its reps); [] for a pure assembly"""
        items = []
        for rp in self.shape_reps(pd):
            _, its, _ = self.rep_items(rp)
            for it in its:
                if it in self.pos and self.type(it) in STYLABLE:
                    items.append((rp, it))
        return items

    def parts(self):
        """the leaf parts a viewer shows, as a list of dicts:
             key        'p<PRODUCT id>' (a placed product: flat files, free shapes) or 'o<NAUO id>' (an assembly occurrence)
             product, pd, name (product name), inst (occurrence name or product name), gid (PRODUCT id string)
             items      [(rep, item)] stylable geometry of the product
           Products that are only assemblies (relating in a NAUO and without own geometry) are not parts."""
        S = self.S if hasattr(self, 'S') else self.structure()
        relating = {n['relating'] for n in S['nauo'].values()}
        related = collections.Counter(n['related'] for n in S['nauo'].values())
        out = []
        pos_order = sorted(S['prod'], key=lambda i: self.pos[i])
        for pid in pos_order:
            pd = S['prod_pd'].get(pid)
            if pd is None:
                continue
            items = self.geometry_items(pd)
            if pd in relating and not items:
                continue                    # assembly container
            if pd in related:
                continue                    # placed through occurrences (below)
            if not items:
                continue
            p = S['prod'][pid]
            out.append(dict(key='p%d' % pid, product=pid, pd=pd, name=p['name'], inst=p['name'], gid=p['gid'], descr=p['descr'],
                            nauo=None, items=items))
        for nid in sorted(S['nauo'], key=lambda i: self.pos[i]):
            n = S['nauo'][nid]
            pd = n['related']
            if pd in relating and not self.geometry_items(pd):
                continue                    # sub-assembly occurrence: its leaves are listed by their own NAUOs
            pid = S['pd_prod'].get(pd)
            if pid is None:
                continue
            items = self.geometry_items(pd)
            if not items:
                continue
            p = S['prod'][pid]
            out.append(dict(key='o%d' % nid, product=pid, pd=pd, name=p['name'], inst=n['name'] or p['name'], gid=p['gid'],
                            descr=p['descr'], nauo=nid, items=items))
        return out

    def length_unit_mm(self):
        """mm per file length unit; None if no length unit is found or the file mixes units"""
        found = set()
        for t in ('LENGTH_UNIT', 'CONVERSION_BASED_UNIT', 'NAMED_UNIT', 'SI_UNIT'):
            for eid in self.by_type.get(t, []):
                b = self.body(eid).replace(' ', '').replace('\n', '').replace('\r', '')
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


class StepWriter:
    """collects edits to a StepFile and writes the edited copy"""

    def __init__(self, sf):
        self.sf = sf
        self.repl = {}               # eid -> new body text (without '#id=' and ';')
        self.new = []                # appended statements (full text)
        self.nid = sf.max_id + 1
        self.header_desc = None

    def add(self, body):
        i = self.nid
        self.nid += 1
        self.new.append('#%d=%s;' % (i, body))
        return i

    def replace(self, eid, body):
        self.repl[eid] = body

    def current(self, eid):
        return self.repl.get(eid) or self.sf.body(eid)

    def write(self, path, file_name=None):
        sf = self.sf
        raw = sf.raw
        hdr = sf.header.decode('latin-1')
        if self.header_desc is not None:
            hdr, n = re.subn(r"FILE_DESCRIPTION\s*\(\s*\((?:'(?:[^']|'')*'\s*,?\s*)*\)", 'FILE_DESCRIPTION((%s)' % q(self.header_desc), hdr, count=1)
        if file_name is not None:
            hdr = re.sub(r"(FILE_NAME\s*\(\s*)'(?:[^']|'')*'", lambda m: m.group(1) + q(file_name), hdr, count=1)
        with open(path, 'wb') as f:
            f.write(hdr.encode('latin-1'))
            last = sf.data0
            for eid in sorted(self.repl, key=lambda e: sf.pos[e]):
                k = sf.pos[eid]
                f.write(raw[last:sf.start[k]])
                f.write(('#%d=%s;\n' % (eid, self.repl[eid])).encode('latin-1'))
                last = sf.end[k]
            f.write(raw[last:sf.data1])
            if not raw[last:sf.data1].endswith(b'\n') and self.new:
                f.write(b'\n')
            for s in self.new:
                f.write(s.encode('latin-1') + b'\n')
            f.write(raw[sf.data1:])


def closure(sf, roots, stop_types=()):
    """all entity ids reachable from roots (including roots), not descending into stop_types"""
    seen, todo = set(), list(roots)
    while todo:
        e = todo.pop()
        if e in seen or e not in sf.pos:
            continue
        seen.add(e)
        if sf.type(e) in stop_types and e not in roots:
            continue
        todo.extend(sf.refs(e))
    return seen
