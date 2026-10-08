#!/usr/bin/env python3
"""
ifc2step6 - IFC -> STEP AP214 faceted B-rep (millimetres), validated part by part.

Drop-in replacement for ifc2step5.py: same command line, same output flavour (FACETED_BREP / POLY_LOOP, schema
AUTOMOTIVE_DESIGN, no ADVANCED_FACE / tessellated entities), same product mapping (PRODUCT.id = IFC GlobalId,
PRODUCT.name = Name, PRODUCT.description = IFC class), same <out>.stats.json and the stats JSON on stdout.

    ifc2step6.py IN.ifc OUT.step [--mode hybrid|transcode|tess] [--threads N] [--prec N] [--nodedup] [--noplane] [--gzip]
    extras: [--no-verify] [--verify-procs N] [--no-surface-fallback] [--sidecar PATH] [--keep-tmp]

Input: IFC-SPF (IFC2X, IFC2X2_FINAL, IFC2X3, IFC4, IFC4X1..IFC4X3_ADD2), ifcZIP, gzip, ifcXML (IFC2x3 ISO 10303-28 and
IFC4 ifcXML, converted to SPF by the built-in reader). Mislabelled / legacy schema headers, Windows NaN tokens, text
after END-ISO-10303-21 and files cut mid-statement are repaired only when the repair is lossless (see prepare_input).

Per product (IfcProduct with a Body / Facetation / unnamed shape representation; openings, spaces, grids, annotations and
virtual elements are skipped exactly as the census skips them):
  1. geometry: faceted source items (IfcFacetedBrep(+WithVoids), IfcShellBasedSurfaceModel, IfcFaceBasedSurfaceModel,
     IfcPolygonalFaceSet incl. inner loops + PnIndex, IfcTriangulatedFaceSet + PnIndex, through IfcMappedItem chains)
     are transcoded exactly; everything else (extrusions, booleans / openings, sweeps, CSG, advanced B-rep) goes
     through the ifcopenshell kernel with polyhedral output (planar faces come out as exact polygons with holes,
     curved faces as facets; such parts are tagged `approx:curved` when the source holds curved geometry).
  2. topology repair (never adds or moves surface): vertices welded on the output grid (10^-prec mm), repeated
     points / zero-area loops removed, non-planar polygons split into triangles, hole loops wound against the outer
     loop, T-junctions split, shells separated into edge-connected components, each component oriented consistently
     and outward (signed volume), components enclosed by another component with opposite orientation written as
     voids (BREP_WITH_VOIDS), IfcFacetedBrepWithVoids voids written as voids (v5 wrote them as extra solids).
  3. verification: every part is read back with OpenCASCADE exactly as the grader's step_check does it (STEPControl
     reader -> per root: solids, BRepCheck_Analyzer, volume > 0, faces, finite bbox), in parallel worker processes on
     small chunk files. A part that fails goes down the fallback chain and is verified again:
        L1  every face triangulated (same vertices, same surface)
        L2  the other geometry source (kernel tessellation for a transcoded part, triangle mesh for a kernel part)
        L3  per solid: valid solids kept, the failing solids written as open shells (surface model)
        L4  whole part as a shell-based surface model (no solid claimed)
     Every representation change is tagged per part: PRODUCT.description = '<IfcClass> [v6:<tags>]' and the sidecar
     <out>.parts.json (per part: source, level, tags, solids, surfaces). Parts are never dropped and no geometry is
     invented (no hole filling, no hulls, no boxes).
"""
import sys, os, re, io, json, time, math, argparse, datetime, gzip, zipfile, shutil, tempfile, subprocess, collections

VERSION = 'ifc2step6 6.1.8'

try:
    import resource
except ImportError:  # Windows
    resource = None


def rss():
    if resource is None:
        return -1
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return r // (1 << 20) if sys.platform == 'darwin' else r // 1024


def log(msg):
    sys.stderr.write('[v6 %s] %s\n' % (time.strftime('%H:%M:%S'), msg))
    sys.stderr.flush()


# ====================================================================================================== text helpers

def step_str(v, limit=120):
    """ISO 10303-21 string body, safe for OpenCASCADE: runs of apostrophes become one '"', a single apostrophe is
    doubled, backslash escaped, non-ASCII written as \\X2\\hhhh\\X0\\; truncated before escaping."""
    v = re.sub("'{2,}", '"', str(v or ""))[:limit]
    out = []
    for ch in v:
        o = ord(ch)
        if ch == "'":
            # OCC 8.0.1's STEP lexer segfaults on an escaped apostrophe followed by a comma inside a string
            # ('Type OH, 8''x4'', H.M.' - Revit feet-inch names): written as the hex escape \X\27, which decodes
            # to the same apostrophe (name unchanged)
            out.append("\\X\\27")
        elif ch == "\\":
            out.append("\\\\")
        elif 32 <= o < 127:
            out.append(ch)
        elif 32 <= o < 0x10000:
            out.append("\\X2\\%04X\\X0\\" % o)
        else:
            out.append("?")
    return "".join(out)


def _rd(v):
    """direction component: 9 significant digits (normal error < 1e-9 rad)"""
    if v == 0.0:
        return "0."
    s = "%.9g" % v
    if "e" in s:
        m, _, e = s.partition("e")
        if "." not in m:
            m += "."
        return m + "E" + str(int(e))
    if "." not in s:
        s += "."
    return s


def _rfix(v, dec=6):
    """coordinate with fixed decimals (no loss of resolution for large georeferenced values)"""
    t = ('%.' + str(dec) + 'f') % v
    t = t.rstrip('0')
    if t.endswith('.') and t in ('-0.',):
        return '0.'
    return t if t not in ('-0.',) else '0.'


def _r(v):
    """compact STEP REAL (always with a '.')"""
    if v == 0.0:
        return "0."
    s = "%.10g" % v
    if "e" in s or "E" in s:
        m, _, e = s.partition("e")
        if "." not in m:
            m += "."
        return m + "E" + str(int(e))
    if "." not in s:
        s += "."
    return s


# ====================================================================================================== input prep

LEGACY_2X3 = ('IFC2X2_FINAL', 'IFC2X_FINAL', 'IFC2X2', 'IFC2X', 'IFC2X2_PLATFORM', 'IFC2X_PLATFORM', 'IFC2X3_FINAL',
              'IFC2X3_TC1', 'IFC2X3_RC1', 'IFC2X2_RC1')
LATER_4X3 = ('IFC4X1', 'IFC4X2', 'IFC4X3', 'IFC4X3_RC1', 'IFC4X3_RC2', 'IFC4X3_RC3', 'IFC4X3_RC4', 'IFC4X3_TC1',
             'IFC4X3_ADD1')
IFC4_VARIANTS = ('IFC4_ADD1', 'IFC4_ADD2', 'IFC4_ADD2_TC1', 'IFC4RC4', 'IFC4RC3', 'IFC4RC2', 'IFC4RC1', 'IFC4_RC4')


def sniff_bytes(head):
    if head[:4] == b'PK\x03\x04':
        return 'zip'
    if head[:2] == b'\x1f\x8b':
        return 'gzip'
    h = head.lstrip(b'\xef\xbb\xbf \r\n\t')
    if h[:5] == b'<?xml' or b'<ifcXML' in head[:8192] or b'iso_10303_28' in head[:8192] or b'<ifc:' in head[:8192]:
        return 'xml'
    if b'ISO-10303-21' in head[:8192]:
        return 'spf'
    return 'unknown'


def available_schemas():
    try:
        import ifcopenshell.ifcopenshell_wrapper as W
        return set(s.upper() for s in W.schema_names())
    except Exception:
        return {'IFC2X3', 'IFC4', 'IFC4X3_ADD2'}


def prepare_input(path, tmpdir, info):
    """-> path of an SPF file ifcopenshell can open (may be the input itself). Records every repair in info['input_fix']."""
    fixes = info.setdefault('input_fix', [])
    with open(path, 'rb') as fh:
        head = fh.read(1 << 16)
    kind = sniff_bytes(head)
    info['input_kind'] = kind
    if kind == 'zip':
        with zipfile.ZipFile(path) as z:
            infos = [i for i in z.infolist() if not i.is_dir()]
            cand = [i for i in infos if i.filename.lower().endswith(('.ifc', '.ifcxml', '.xml', '.txt', '.stp', '.step'))] or infos
            if not cand:
                raise RuntimeError('empty zip')
            m = max(cand, key=lambda i: i.file_size)
            out = os.path.join(tmpdir, 'unzipped.bin')
            with z.open(m) as a, open(out, 'wb') as b:
                shutil.copyfileobj(a, b, 1 << 24)
        fixes.append('unzipped:%s' % os.path.basename(m.filename)[:60])
        return prepare_input(out, tmpdir, info)
    if kind == 'gzip':
        out = os.path.join(tmpdir, 'gunzipped.bin')
        with gzip.open(path) as a, open(out, 'wb') as b:
            shutil.copyfileobj(a, b, 1 << 24)
        fixes.append('gunzipped')
        return prepare_input(out, tmpdir, info)
    if kind == 'xml':
        out = os.path.join(tmpdir, 'from_xml.ifc')
        n = ifcxml_to_spf(path, out, info)
        fixes.append('ifcxml_to_spf:%d_entities' % n)
        return out
    if kind != 'spf':
        raise RuntimeError('not an IFC file (no ISO-10303-21 / ifcXML header)')
    return path


def spf_schema(path):
    with open(path, 'rb') as fh:
        head = fh.read(1 << 16)
    m = re.search(rb"FILE_SCHEMA\s*\(\s*\(\s*'([^']*)'", head)
    return m.group(1).decode('latin1').strip().upper() if m else None


def rewrite_spf(src, dst, fn):
    """stream src -> dst applying fn(bytes)->bytes on 16 MB chunks split at line ends"""
    with open(src, 'rb') as a, open(dst, 'wb') as b:
        rest = b''
        while True:
            chunk = a.read(1 << 24)
            if not chunk:
                if rest:
                    b.write(fn(rest))
                break
            chunk = rest + chunk
            cut = chunk.rfind(b'\n')
            if cut < 0:
                rest = chunk
                continue
            b.write(fn(chunk[:cut + 1]))
            rest = chunk[cut + 1:]


def set_schema(src, dst, new):
    data_head = open(src, 'rb').read(1 << 16)
    m = re.search(rb"FILE_SCHEMA\s*\(\s*\(\s*'([^']*)'", data_head)
    with open(src, 'rb') as a, open(dst, 'wb') as b:
        if m:
            b.write(data_head[:m.start(1)] + new.encode() + data_head[m.end(1):])
        else:
            hs = data_head.find(b'ENDSEC;')
            b.write(data_head[:hs] + b"FILE_SCHEMA(('" + new.encode() + b"'));\n" + data_head[hs:])
        a.seek(len(data_head))
        shutil.copyfileobj(a, b, 1 << 24)


def detect_schema_by_entities(path, cands):
    """schema (of cands) whose entity set covers the most entity names used in the DATA section"""
    names = collections.Counter()
    rx = re.compile(rb'^\s*#\d+\s*=\s*([A-Za-z0-9_]+)\s*\(', re.M)
    with open(path, 'rb') as fh:
        n = 0
        for chunk in iter(lambda: fh.read(1 << 24), b''):
            for m in rx.finditer(chunk):
                names[m.group(1).upper()] += 1
            n += 1
            if n > 8:
                break
    try:
        import ifcopenshell.ifcopenshell_wrapper as W
    except Exception:
        return None, {}
    score = {}
    for s in cands:
        try:
            sch = W.schema_by_name(s)
            known = set(d.name().upper() for d in sch.declarations())
        except Exception:
            continue
        score[s] = sum(c for nm, c in names.items() if nm not in known)
    if not score:
        return None, {}
    best = min(score, key=lambda k: score[k])
    return best, score


def tail_repair(src, dst, info):
    """file cut mid-statement: keep complete statements only if nothing but the unfinished tail is lost
    (0 dangling references, IfcProject + IfcUnitAssignment present, <= 1 MB dropped)"""
    data = open(src, 'rb').read()
    end = data.rfind(b'END-ISO-10303-21;')
    if end >= 0:
        tail = data[end + len(b'END-ISO-10303-21;'):]
        if tail.strip(b'\x00 \r\n\t\x1a'):
            open(dst, 'wb').write(data[:end + len(b'END-ISO-10303-21;')] + b'\n')
            info.setdefault('input_fix', []).append('trailing_garbage_dropped:%d_bytes' % len(tail))
            return True
        return False
    cut = max(data.rfind(b';\r\n'), data.rfind(b';\n'))
    if cut < 0:
        return False
    body = data[:cut + 1]
    dropped = len(data) - len(body)
    if body.rstrip().endswith(b'ENDSEC;'):
        body = body.rstrip()[:-len(b'ENDSEC;')]
    ids = set(int(m.group(1)) for m in re.finditer(rb'#(\d+)\s*=', body))
    refs = set(int(m.group(1)) for m in re.finditer(rb'#(\d+)', re.sub(rb"'[^']*'", b'', body)))
    dangling = len(refs - ids)
    proj = re.search(rb'=\s*IFCPROJECT\s*\(', body, re.I) is not None
    units = re.search(rb'=\s*IFCUNITASSIGNMENT\s*\(', body, re.I) is not None
    if dangling or not proj or not units or dropped > 1 << 20:
        info['tail_repair_refused'] = '%d dangling refs, project=%s, units=%s, cut %d bytes' % (dangling, proj, units, dropped)
        return False
    nl = b'\r\n' if b'\r\n' in body[-64:] else b'\n'
    with open(dst, 'wb') as fh:
        fh.write(body.rstrip() + nl + b'ENDSEC;' + nl + b'END-ISO-10303-21;' + nl)
    info.setdefault('input_fix', []).append('truncated_tail_repaired:%d_bytes' % dropped)
    return True


NAN_RX = re.compile(rb'-?1\.#(?:IND|QNAN|INF|SNAN)0*|-?nan(?:\(ind\))?|-?inf(?=[,)])', re.I)


def open_ifc(path, tmpdir, info):
    """ifcopenshell.open with lossless repairs: legacy / later schema labels, schema chosen by entity names when the
    label does not parse, Windows NaN tokens, text after the end marker, truncated tail."""
    import ifcopenshell
    fixes = info.setdefault('input_fix', [])
    avail = available_schemas()
    sch = spf_schema(path)
    info['schema_declared'] = sch
    cur = path
    target = None
    if sch in LEGACY_2X3:
        target = 'IFC2X3'
    elif sch in LATER_4X3 or (sch and sch.startswith('IFC4X3') and sch not in avail):
        target = 'IFC4X3_ADD2' if 'IFC4X3_ADD2' in avail else ('IFC4X3' if 'IFC4X3' in avail else 'IFC4')
    elif sch in IFC4_VARIANTS:
        target = 'IFC4'
    elif sch is not None and sch not in avail:
        best, score = detect_schema_by_entities(path, [s for s in ('IFC2X3', 'IFC4', 'IFC4X3_ADD2') if s in avail])
        target = best
    if target and target != sch:
        nxt = os.path.join(tmpdir, 'schema.ifc')
        set_schema(cur, nxt, target)
        fixes.append('schema_%s_declared_%s' % (sch, target))
        cur = nxt
    errors = []
    for attempt in range(5):
        try:
            f = ifcopenshell.open(cur)
            if attempt or cur != path:
                info['opened_after'] = errors[-3:]
            return f, cur
        except Exception as e:
            msg = '%s: %s' % (type(e).__name__, str(e)[:300])
            errors.append(msg)
            log('open failed: ' + msg)
        nxt = os.path.join(tmpdir, 'repair%d.ifc' % attempt)
        if attempt == 0:
            # schema chosen by entity names (mislabelled IFC2X3 <-> IFC4 exports)
            best, score = detect_schema_by_entities(cur, [s for s in ('IFC2X3', 'IFC4', 'IFC4X3_ADD2') if s in avail])
            now = spf_schema(cur)
            if best and best != now and score.get(best, 1) < score.get(now, 1 << 60):
                set_schema(cur, nxt, best)
                fixes.append('schema_%s_relabelled_%s_by_entity_names' % (now, best))
                cur = nxt
                continue
        if attempt <= 1:
            n = [0]

            def fixnan(b):
                def sub(m):
                    n[0] += 1
                    return b'0.'
                return NAN_RX.sub(sub, b) if b'#' in b or b'nan' in b.lower() or b'inf' in b.lower() else b
            # only inside DATA statements: a token-level replacement of non-numbers that no parser accepts
            rewrite_spf(cur, nxt, fixnan)
            if n[0]:
                fixes.append('nan_tokens_zeroed:%d' % n[0])
                cur = nxt
                continue
        if attempt <= 2:
            if tail_repair(cur, nxt, info):
                cur = nxt
                continue
        if attempt <= 3:
            # normalized header (some exporters write headers ifcopenshell rejects)
            data = open(cur, 'rb').read()
            h = re.search(rb'HEADER;(.*?)ENDSEC;', data, re.S)
            if h:
                std = (b"HEADER;\nFILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');\n"
                       b"FILE_NAME('model.ifc','2000-01-01T00:00:00',(''),(''),'','','');\n"
                       b"FILE_SCHEMA(('" + (spf_schema(cur) or 'IFC2X3').encode() + b"'));\nENDSEC;")
                open(nxt, 'wb').write(data[:h.start()] + std + data[h.end():])
                fixes.append('header_normalized')
                cur = nxt
                continue
        break
    raise RuntimeError('unable to parse IFC: ' + ' | '.join(errors[-3:]))


# ====================================================================================================== ifcXML -> SPF

def _xml_local(tag):
    return tag.rsplit('}', 1)[-1] if '}' in tag else tag.split(':')[-1]


def ifcxml_to_spf(src, dst, info):
    """ifcXML (IFC2x3 ISO 10303-28 ed.2 'iso_10303_28'/'uos', or IFC4 'ifcXML') -> IFC-SPF, using the ifcopenshell
    schema for attribute order and types. Entities are matched by element name, references by id/ref (or by
    nesting), attributes by element or XML-attribute name. Returns the number of entities written."""
    import xml.etree.ElementTree as ET
    import ifcopenshell.ifcopenshell_wrapper as W
    # schema from the root / namespace
    with open(src, 'rb') as fh:
        head = fh.read(1 << 16).decode('utf-8', 'replace')
    schema = 'IFC4' if ('IFC4' in head.upper() and 'IFC2X3' not in head.upper()) else 'IFC2X3'
    m = re.search(r'IFC4X3[_A-Z0-9]*|IFC4|IFC2X3', head.upper())
    if m:
        schema = {'IFC4X3': 'IFC4X3_ADD2'}.get(m.group(0), m.group(0))
        if schema.startswith('IFC4X3'):
            schema = 'IFC4X3_ADD2'
    if schema not in available_schemas():
        schema = 'IFC4' if schema.startswith('IFC4') else 'IFC2X3'
    sch = W.schema_by_name(schema)
    decl_by_lower = {}
    for d in sch.declarations():
        decl_by_lower[d.name().lower()] = d
    info['ifcxml_schema'] = schema
    tree = ET.parse(src)
    root = tree.getroot()
    ids = {}          # xml id -> step id
    out_ents = {}     # step id -> (decl name, element)
    order = []
    counter = [0]

    def new_id():
        counter[0] += 1
        return counter[0]

    def is_entity_el(el):
        d = decl_by_lower.get(_xml_local(el.tag).lower())
        return d is not None and isinstance(d, W.entity) and not d.is_abstract()

    # pass 1: number every entity element (top-level and nested)
    def walk_number(el):
        if is_entity_el(el) and el.get('ref') is None and not el.get('href'):
            sid = new_id()
            xid = el.get('id')
            if xid is not None:
                ids[xid] = sid
            el.set('__sid', str(sid))
            out_ents[sid] = el
            order.append(sid)
        for c in el:
            walk_number(c)
    walk_number(root)

    def ref_of(el):
        r = el.get('ref') or el.get('href')
        if r is not None:
            r = r.lstrip('#')
            return ids.get(r)
        s = el.get('__sid')
        return int(s) if s else None

    def esc(s):
        return "'" + step_str(s, 1 << 20) + "'"

    def fmt_simple(text, typ_name):
        t = (text or '').strip()
        tn = typ_name.lower()
        if tn in ('real', 'number'):
            try:
                return _r(float(t))
            except ValueError:
                return '$'
        if tn == 'integer':
            try:
                return str(int(float(t)))
            except ValueError:
                return '$'
        if tn == 'boolean':
            return '.T.' if t.lower() in ('true', '1', 't') else '.F.'
        if tn == 'logical':
            return {'true': '.T.', 'false': '.F.'}.get(t.lower(), '.U.')
        if tn == 'binary':
            return '"' + t + '"'
        return esc(t)

    def underlying(pt):
        """parameter type -> ('simple', name) | ('entity', decl) | ('select', decl) | ('enum', decl) | ('aggr', inner) | ('named', decl)"""
        if isinstance(pt, W.simple_type):
            return ('simple', pt.declared_type())
        if isinstance(pt, W.named_type):
            d = pt.declared_type()
            if isinstance(d, W.entity):
                return ('entity', d)
            if isinstance(d, W.select_type):
                return ('select', d)
            if isinstance(d, W.enumeration_type):
                return ('enum', d)
            if isinstance(d, W.type_declaration):
                return ('typedecl', d)
        if isinstance(pt, W.aggregation_type):
            return ('aggr', pt.type_of_element())
        return ('unknown', None)

    def typedecl_base(d):
        pt = d.declared_type()
        while True:
            u = underlying(pt)
            if u[0] == 'typedecl':
                pt = u[1].declared_type()
                continue
            return u

    def value_from_el(el, pt):
        """el = the attribute element (holding text or child elements) -> SPF token"""
        u = underlying(pt)
        kids = list(el)
        if u[0] == 'simple':
            return fmt_simple(el.text, u[1])
        if u[0] == 'typedecl':
            b = typedecl_base(u[1])
            if b[0] == 'simple':
                return fmt_simple(el.text, b[1])
            if b[0] == 'aggr':
                return aggr_from(el, b[1])
            return fmt_simple(el.text, 'string')
        if u[0] == 'enum':
            return '.' + (el.text or '').strip().upper() + '.'
        if u[0] == 'entity':
            if kids:
                r = ref_of(kids[0])
                return '#%d' % r if r else '$'
            r = ref_of(el)
            return '#%d' % r if r else '$'
        if u[0] == 'select':
            if not kids:
                return fmt_simple(el.text, 'string')
            return select_value(kids[0])
        if u[0] == 'aggr':
            return aggr_from(el, u[1])
        return '$'

    def select_value(k):
        nm = _xml_local(k.tag)
        d = decl_by_lower.get(nm.lower())
        if d is None:
            # IFC4 ifcXML: <IfcLabel-wrapper> or <...-wrapper>
            nm2 = nm[:-8] if nm.lower().endswith('-wrapper') else nm
            d = decl_by_lower.get(nm2.lower())
            if d is None:
                return fmt_simple(k.text, 'string')
        if isinstance(d, W.entity):
            r = ref_of(k)
            return '#%d' % r if r else '$'
        if isinstance(d, W.type_declaration):
            b = typedecl_base(d)
            if b[0] == 'simple':
                return '%s(%s)' % (d.name().upper(), fmt_simple(k.text if k.get('value') is None else k.get('value'), b[1]))
            if b[0] == 'aggr':
                return '%s(%s)' % (d.name().upper(), aggr_from(k, b[1]))
        if isinstance(d, W.enumeration_type):
            return '.' + (k.text or '').strip().upper() + '.'
        return '$'

    def aggr_from(el, inner):
        kids = list(el)
        u = underlying(inner)
        toks = []
        if not kids:
            # IFC4 list of simple values in text: "1. 2. 3."
            txt = (el.text or '').split()
            for t in txt:
                if u[0] == 'simple':
                    toks.append(fmt_simple(t, u[1]))
                elif u[0] == 'typedecl':
                    b = typedecl_base(u[1])
                    toks.append(fmt_simple(t, b[1] if b[0] == 'simple' else 'string'))
                else:
                    toks.append(fmt_simple(t, 'string'))
            return '(' + ','.join(toks) + ')'
        for k in kids:
            if u[0] == 'entity':
                r = ref_of(k)
                if r:
                    toks.append('#%d' % r)
            elif u[0] == 'select':
                toks.append(select_value(k))
            elif u[0] == 'aggr':
                toks.append(aggr_from(k, u[1]))
            elif u[0] == 'typedecl':
                b = typedecl_base(u[1])
                if b[0] == 'aggr':
                    toks.append(aggr_from(k, b[1]))
                else:
                    toks.append(fmt_simple(k.text if k.get('value') is None else k.get('value'), b[1] if b[0] == 'simple' else 'string'))
            elif u[0] == 'enum':
                toks.append('.' + (k.text or '').strip().upper() + '.')
            else:
                toks.append(fmt_simple(k.text, u[1] if u[0] == 'simple' else 'string'))
        return '(' + ','.join(toks) + ')'

    def attr_value_text(txt, pt):
        """IFC4 ifcXML attributes written as XML attributes (simple values, enums, lists of simple values)"""
        u = underlying(pt)
        if u[0] == 'simple':
            return fmt_simple(txt, u[1])
        if u[0] == 'typedecl':
            b = typedecl_base(u[1])
            if b[0] == 'simple':
                return fmt_simple(txt, b[1])
            if b[0] == 'aggr':
                ub = underlying(b[1])
                return '(' + ','.join(fmt_simple(t, ub[1] if ub[0] == 'simple' else 'real') for t in txt.split()) + ')'
            return fmt_simple(txt, 'string')
        if u[0] == 'enum':
            return '.' + txt.strip().upper() + '.'
        if u[0] == 'aggr':
            ub = underlying(u[1])
            if ub[0] == 'typedecl':
                ub = typedecl_base(ub[1])
            return '(' + ','.join(fmt_simple(t, ub[1] if ub[0] == 'simple' else 'real') for t in txt.split()) + ')'
        if u[0] == 'select':
            return fmt_simple(txt, 'string')
        return '$'

    n_written = 0
    with open(dst, 'w', encoding='latin-1', newline='\n') as out:
        out.write("ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('converted from ifcXML by %s'),'2;1');\n" % VERSION)
        out.write("FILE_NAME('%s','%s',(''),(''),'','','');\n" % (step_str(os.path.basename(src)), datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S')))
        out.write("FILE_SCHEMA(('%s'));\nENDSEC;\nDATA;\n" % schema)
        for sid in order:
            el = out_ents[sid]
            d = decl_by_lower[_xml_local(el.tag).lower()]
            attrs = d.all_attributes()
            derived = d.derived()
            kids = {}
            for c in el:
                kids.setdefault(_xml_local(c.tag).lower(), c)
            xattr = {k.lower(): v for k, v in el.attrib.items()}
            toks = []
            for i, at in enumerate(attrs):
                if derived and i < len(derived) and derived[i]:
                    toks.append('*')
                    continue
                nm = at.name().lower()
                if nm in kids:
                    c = kids[nm]
                    if c.get('{http://www.w3.org/2001/XMLSchema-instance}nil') == 'true' and not list(c):
                        toks.append('$')
                    else:
                        toks.append(value_from_el(c, at.type_of_attribute()))
                elif nm in xattr:
                    toks.append(attr_value_text(xattr[nm], at.type_of_attribute()))
                else:
                    toks.append('$')
            out.write('#%d=%s(%s);\n' % (sid, d.name().upper(), ','.join(toks)))
            n_written += 1
        out.write('ENDSEC;\nEND-ISO-10303-21;\n')
    return n_written


# ====================================================================================================== mesh core
import numpy as np

# 6.1.8: zero-width spikes cancelled (exact); open source shells measured (gap_max_mm) and closed when every free edge
# lies within GAP_CLOSE_MM of another free edge
DESPIKE = os.environ.get('V6_NO_DESPIKE') != '1'
DEGEN_FIX = os.environ.get('V6_NO_DEGEN_FIX') != '1'     # zero-area faces dropped before the T-junction split
NET_DEDUP = os.environ.get('V6_NO_NET_DEDUP') != '1'     # coincident faces resolved by orientation count
CO_UNION = os.environ.get('V6_NO_COPLANAR_UNION') != '1'  # overlapping coplanar faces of open shells -> signed union
GAP_CLOSE_MM = float(os.environ.get('V6_GAP_CLOSE_MM', '0.1'))     # 6.1.9: the converter's declared sew tolerance
SEW_NOCHAIN = os.environ.get('V6_SEW_CHAIN') != '1'                  # 6.1.9: seam sewing moves no vertex by more than tol


class Shell:
    """faces: list of faces, face = list of loops (lists of welded vertex indices), loop 0 = outer, wound so that the
    face normal (right hand) points out of the solid."""
    __slots__ = ('faces', 'closed', 'vol', 'tags', 'voids', 'role', 'gap', 'flat', 'sew')

    def __init__(self, faces, closed, vol, role):
        self.faces = faces; self.closed = closed; self.vol = vol; self.tags = set(); self.voids = []; self.role = role
        self.gap = None     # open source shell: free-edge gap measure (Repair.gap_stats)
        self.flat = None    # closed shell with all vertices in one plane (flat_shell), cached
        self.sew = 0.0      # largest vertex move (mm) of the seam sewing of its source piece (Repair.sew)


def reduce_loop(lp):
    """cancel zero-width spikes of a closed loop: repeated points and immediate reversals a -> b -> a (the boundary runs
    out along an edge and back along the same edge, e.g. a collinear tail once its T-junction vertex is inserted),
    cyclically until none remain. Exact: the face keeps its area and surface; only the zero-width tail goes."""
    s = []
    for v in lp:
        if s and s[-1] == v:
            continue
        if len(s) >= 2 and s[-2] == v:
            s.pop()
            continue
        s.append(v)
    while len(s) >= 3:
        if s[0] == s[-1]:
            s.pop()
        elif s[-2] == s[0]:
            s.pop()
        elif s[-1] == s[1]:
            s.pop(0)
        else:
            break
    return s


def newell(P):
    """P (k,3) -> unnormalised Newell normal (|n| = 2 * area)"""
    Q = np.roll(P, -1, axis=0)
    return np.array([np.sum((P[:, 1] - Q[:, 1]) * (P[:, 2] + Q[:, 2])),
                     np.sum((P[:, 2] - Q[:, 2]) * (P[:, 0] + Q[:, 0])),
                     np.sum((P[:, 0] - Q[:, 0]) * (P[:, 1] + Q[:, 1]))])


def loop_normals(X, loops):
    """unnormalised Newell normals of many loops at once (relative to each loop's first vertex: precise far from
    the origin). loops: list of index lists (len >= 3) -> (len(loops), 3)"""
    if not loops:
        return np.zeros((0, 3))
    lens = np.fromiter((len(l) for l in loops), np.int64, len(loops))
    tot = int(lens.sum())
    idx = np.fromiter((i for l in loops for i in l), np.int64, tot)
    starts = np.zeros(len(loops), np.int64)
    if len(loops) > 1:
        starts[1:] = np.cumsum(lens)[:-1]
    P = X[idx] - np.repeat(X[idx[starts]], lens, axis=0)
    nxt = np.arange(tot) + 1
    nxt[starts + lens - 1] = starts
    Q = P[nxt]
    c = np.empty((tot, 3))
    c[:, 0] = (P[:, 1] - Q[:, 1]) * (P[:, 2] + Q[:, 2])
    c[:, 1] = (P[:, 2] - Q[:, 2]) * (P[:, 0] + Q[:, 0])
    c[:, 2] = (P[:, 0] - Q[:, 0]) * (P[:, 1] + Q[:, 1])
    return np.add.reduceat(c, starts, axis=0)


def loop_perimeters(X, loops):
    """perimeter of many loops at once -> (len(loops),)"""
    if not loops:
        return np.zeros(0)
    lens = np.fromiter((len(l) for l in loops), np.int64, len(loops))
    tot = int(lens.sum())
    idx = np.fromiter((i for l in loops for i in l), np.int64, tot)
    starts = np.zeros(len(loops), np.int64)
    if len(loops) > 1:
        starts[1:] = np.cumsum(lens)[:-1]
    nxt = np.arange(tot) + 1
    nxt[starts + lens - 1] = starts
    d = X[idx[nxt]] - X[idx]
    return np.add.reduceat(np.sqrt(np.einsum('ij,ij->i', d, d)), starts)


ZERO_AREA_REL = 1e-12      # |2 * area| <= ZERO_AREA_REL * perimeter^2: the loop has no area (all vertices on one line)


def zero_area_mask(X, loops):
    """loops whose vertices are all collinear (no area, no plane): True"""
    if not loops:
        return np.zeros(0, bool)
    N = loop_normals(X, loops)
    ln = np.sqrt(np.einsum('ij,ij->i', N, N))
    P = loop_perimeters(X, loops)
    return ln <= ZERO_AREA_REL * P * P


def _plane_basis(n):
    n = n / (np.linalg.norm(n) + 1e-300)
    a = np.array([1.0, 0, 0]) if abs(n[0]) < 0.9 else np.array([0, 1.0, 0])
    u = np.cross(n, a); u /= np.linalg.norm(u)
    v = np.cross(n, u)
    return u, v


def _area2(p):
    x, y = p[:, 0], p[:, 1]
    return float(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y))


def _pt_in_tri(p, a, b, c):
    d1 = (p[0] - b[0]) * (a[1] - b[1]) - (a[0] - b[0]) * (p[1] - b[1])
    d2 = (p[0] - c[0]) * (b[1] - c[1]) - (b[0] - c[0]) * (p[1] - c[1])
    d3 = (p[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (p[1] - a[1])
    neg = d1 < 0 or d2 < 0 or d3 < 0
    pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (neg and pos)


def earcut(face, X, n):
    """triangulate a planar-ish face (outer + hole loops of vertex indices; coordinates X) projected on the plane with
    normal n. Holes are bridged into the outer loop (mutually visible vertices), then ears are clipped. Returns a list
    of triangles (index triples, wound like the outer loop) or None when the polygon defeats the clipper."""
    u, v = _plane_basis(n)
    o = X[face[0][0]].copy()       # projected relative to one vertex: precise far from the origin (6.1.8)
    proj = lambda idx: np.stack([(X[idx] - o) @ u, (X[idx] - o) @ v], axis=1)
    outer = list(face[0])
    P = proj(np.array(outer))
    ext = float(np.abs(P).max()) if len(P) else 1.0
    eps = 1e-12 * max(ext, 1e-6) ** 2     # cross products below this are collinear (zero-area ear)
    if _area2(P) < 0:  # work CCW in (u,v); the face normal is n so outer must be CCW
        outer = outer[::-1]
        flipped = True
    else:
        flipped = False
    ring = outer[:]
    holes = []
    for h in face[1:]:
        h = list(h)
        Ph = proj(np.array(h))
        if _area2(Ph) > 0:
            h = h[::-1]
        holes.append(h)
    # bridge holes: rightmost hole vertex first
    def coords(i):
        return np.array([(X[i] - o) @ u, (X[i] - o) @ v])
    holes.sort(key=lambda h: -max(coords(i)[0] for i in h))
    for h in holes:
        hc = [coords(i) for i in h]
        k = max(range(len(h)), key=lambda j: hc[j][0])
        hp = hc[k]
        rc = [coords(i) for i in ring]
        best, bd = None, None
        for j, q in enumerate(rc):
            d = (q[0] - hp[0]) ** 2 + (q[1] - hp[1]) ** 2
            if bd is not None and d >= bd:
                continue
            # segment hp-q must not cross ring or hole edges
            ok = True
            for poly, pc in ((ring, rc), (h, hc)):
                m = len(poly)
                for t in range(m):
                    a, b = pc[t], pc[(t + 1) % m]
                    if poly[t] in (ring[j], h[k]) or poly[(t + 1) % m] in (ring[j], h[k]):
                        continue
                    if _seg_cross(hp, q, a, b):
                        ok = False
                        break
                if not ok:
                    break
            if ok:
                best, bd = j, d
        if best is None:
            return None
        ring = ring[:best + 1] + h[k:] + h[:k + 1] + ring[best:]
    # ear clipping
    idx = ring[:]
    C = {i: coords(i) for i in set(idx)}
    tris = []
    guard = 0
    while len(idx) > 3 and guard < 10 * len(ring) * len(ring) + 100:
        guard += 1
        m = len(idx)
        clipped = False
        for t in range(m):
            i0, i1, i2 = idx[(t - 1) % m], idx[t], idx[(t + 1) % m]
            a, b, c = C[i0], C[i1], C[i2]
            cr = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
            if cr <= eps:
                continue
            inside = False
            for j in idx:
                if j in (i0, i1, i2):
                    continue
                pj = C[j]
                if (pj[0] == a[0] and pj[1] == a[1]) or (pj[0] == b[0] and pj[1] == b[1]) or (pj[0] == c[0] and pj[1] == c[1]):
                    continue
                if _pt_in_tri(pj, a, b, c):
                    inside = True
                    break
            if inside:
                continue
            tris.append((i0, i1, i2))
            del idx[t]
            clipped = True
            break
        if not clipped:
            # degenerate remainder: drop zero-area ears (collinear) or give up
            removed = False
            for t in range(m):
                i0, i1, i2 = idx[(t - 1) % m], idx[t], idx[(t + 1) % m]
                a, b, c = C[i0], C[i1], C[i2]
                cr = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
                if abs(cr) <= eps:
                    del idx[t]
                    removed = True
                    break
            if not removed:
                return None
    if len(idx) == 3:
        a, b, c = (C[i] for i in idx)
        cr = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        if cr > eps:
            tris.append(tuple(idx))
    if flipped:
        tris = [(c, b, a) for a, b, c in tris]
    return tris


def _seg_cross(p1, p2, p3, p4):
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    d1 = orient(p3, p4, p1); d2 = orient(p3, p4, p2); d3 = orient(p1, p2, p3); d4 = orient(p1, p2, p4)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and d1 != 0 and d2 != 0 and d3 != 0 and d4 != 0


class Repair:
    """topology repair of one source piece on the output grid. Never moves a vertex off the grid point it rounds to
    and never creates a face that is not part of the source surface."""

    def __init__(self, prec):
        self.prec = prec
        self.qs = 10.0 ** prec            # grid steps per mm
        self.tol_planar = max(1.0 / self.qs, 1e-4)    # mm: polygon accepted as planar
        self.tol_t = 2.0 / self.qs        # mm: T-junction vertex on edge
        self.tol_sew = max(10.0 / self.qs, 0.02) if prec <= 3 else 0.02   # mm: seam vertices merged (0.1 mm at prec 2)
        self.stats = collections.Counter()
        self.merge = os.environ.get('V6_NO_MERGE') != '1'
        self.last_sew_move = 0.0      # largest vertex move of the sewing since the caller reset it (sew_max_mm)

    # -------------------------------------------------------------- weld
    def weld(self, V):
        """V float (n,3) mm -> (Q int64 (m,3) grid coords, inv (n,)) or None when coordinates are corrupt"""
        if len(V) == 0:
            return np.zeros((0, 3), np.int64), np.zeros(0, np.int64)
        if not np.isfinite(V).all() or np.abs(V).max() > 1e13:
            return None
        Q = np.round(V * self.qs).astype(np.int64)
        Qc = np.ascontiguousarray(Q)
        u, inv = np.unique(Qc.view([('', np.int64)] * 3).ravel(), return_inverse=True)
        return u.view(np.int64).reshape(-1, 3), inv.ravel()

    # -------------------------------------------------------------- faces
    def clean_faces(self, faces, inv, X):
        """remap to welded ids, drop repeated points / degenerate loops, split pinched loops, wind holes against the
        outer loop, triangulate non-planar faces. X = welded coordinates in mm (float)."""
        st = self.stats
        stage = []
        invl = inv.tolist() if inv is not None else None
        for f in faces:
            loops = []
            for k, lp in enumerate(f):
                q = [invl[i] for i in lp] if invl is not None else list(lp)
                if len(q) > 1:
                    c = [v for j, v in enumerate(q) if v != q[j - 1]]
                else:
                    c = q
                if DESPIKE and len(c) >= 3 and len(set(c)) != len(c):
                    c2 = reduce_loop(c)
                    if len(c2) != len(c):
                        st['spike_vertices_removed'] += len(c) - len(c2)
                        c = c2
                if len(c) < 3:
                    if k == 0:
                        loops = None
                        break
                    st['hole_loops_degenerate_dropped'] += 1
                    continue
                loops.append(c)
            if not loops:
                st['faces_degenerate_dropped'] += 1
                continue
            o = loops[0]
            if len(o) > 3 and len(set(o)) != len(o):
                if len(loops) == 1:
                    st['faces_pinched_split'] += 1
                    for p_ in self._split_pinched(o):
                        stage.append([p_])
                    continue
                st['faces_pinched_with_holes'] += 1
            stage.append(loops)
        if not stage:
            return []
        # vectorised: normals of every loop, zero-area removal, hole winding, planarity
        loops = [lp for f in stage for lp in f]
        N = loop_normals(X, loops)
        ln = np.sqrt(np.einsum('ij,ij->i', N, N))
        out = []
        k = 0
        tol = self.tol_planar
        Nl = N.tolist(); lnl = ln.tolist()
        for f in stage:
            m = len(f)
            if m > 1:
                # the outer boundary is the loop of largest area (kernel polyhedral output does not always list it
                # first; a hole can never be larger than its face)
                j0 = max(range(m), key=lambda j: lnl[k + j])
                if j0:
                    f = [f[j0]] + f[:j0] + f[j0 + 1:]
                    order = [k + j0] + list(range(k, k + j0)) + list(range(k + j0 + 1, k + m))
                    Nl[k:k + m] = [Nl[i] for i in order]
                    lnl[k:k + m] = [lnl[i] for i in order]
                    st['outer_loop_reordered'] += 1
            if lnl[k] < 1e-12:
                st['faces_zero_area_dropped'] += 1
                k += m
                continue
            no = Nl[k]
            res = [f[0]]
            for j in range(1, m):
                if lnl[k + j] < 1e-12:
                    st['hole_loops_zero_area_dropped'] += 1
                    continue
                nh = Nl[k + j]
                h = f[j]
                if nh[0] * no[0] + nh[1] * no[1] + nh[2] * no[2] > 0:
                    h = h[::-1]
                    st['hole_loops_rewound'] += 1
                res.append(h)
            k += m
            if len(res) == 1 and len(res[0]) == 3:
                out.append(res)
                continue
            # planarity: max distance of every loop vertex to the plane through the outer loop's centroid
            n_ = np.array(no) / lnl[k - m]
            allidx = [i for lp in res for i in lp]
            A = X[allidx]
            c = X[res[0]].mean(axis=0)
            if np.abs((A - c) @ n_).max() <= tol:
                out.append(res)
                continue
            tris = earcut(res, X, n_)
            if tris is None:
                st['faces_nonplanar_untriangulable'] += 1
                out.append(res)
                continue
            st['faces_nonplanar_triangulated'] += 1
            out.extend([[list(t)] for t in tris])
        return out

    def _split_pinched(self, lp):
        res = []
        stack = []
        pos = {}
        for v in lp:
            if v in pos:
                i = pos[v]
                sub = stack[i:]
                del stack[i + 1:]
                for w in sub[1:]:
                    pos.pop(w, None)
                if len(sub) >= 3:
                    res.append(sub)
            else:
                pos[v] = len(stack)
                stack.append(v)
        if len(stack) >= 3:
            res.append(stack)
        return res

    # -------------------------------------------------------------- edges
    @staticmethod
    def edge_arrays(faces):
        """directed edges of all loops -> (a, b, face index)"""
        A, B, F = [], [], []
        for fi, f in enumerate(faces):
            for lp in f:
                m = len(lp)
                A.extend(lp)
                B.extend(lp[1:]); B.append(lp[0])
                F.extend([fi] * m)
        return np.array(A, np.int64), np.array(B, np.int64), np.array(F, np.int64)

    def dedup_faces(self, faces):
        """identical faces (same vertex cycle, same orientation): keep one. A pair of faces with the same cycle in
        opposite orientation whose edges are all shared with further faces is the contact wall of two solids that
        touch face to face (e.g. bolt head on shank exported as one shell): both are removed, which joins the two
        solids into their exact union (same point set, no surface added). A double wall that is the whole shell
        (zero-thickness plate) is kept."""
        seen = {}
        out = []
        self.last_twins = []
        if NET_DEDUP:
            # 6.1.8: a cycle given more often in one orientation than the other (e.g. SDS/2 stud end cap given 3 times,
            # twice outward and once inward) is one face of the boundary: one copy of the majority orientation is kept
            # and the rest dropped (the surface is unchanged). Equal counts keep one copy of each (pair rule below).
            grp = {}
            for fi, f in enumerate(faces):
                if len(f) != 1:
                    continue
                o = f[0]
                k = min(range(len(o)), key=lambda i: o[i])
                c = tuple(o[k:] + o[:k])
                r = c[::-1]
                k2 = min(range(len(r)), key=lambda i: r[i])
                rc = tuple(r[k2:] + r[:k2])
                g_ = grp.setdefault(min(c, rc), [[], []])
                g_[0 if c <= rc else 1].append(fi)
            skip = set()
            for fw, rv in grp.values():
                if fw and rv and len(fw) != len(rv):
                    keep_ = (fw if len(fw) > len(rv) else rv)[0]
                    for fi in fw + rv:
                        if fi != keep_:
                            skip.add(fi)
            if skip:
                self.stats['coincident_faces_net_resolved'] += len(skip)
                faces = [f for fi, f in enumerate(faces) if fi not in skip]
        for f in faces:
            o = f[0]
            k = min(range(len(o)), key=lambda i: o[i])
            key = (tuple(o[k:] + o[:k]), len(f))
            if key in seen:
                self.stats['faces_duplicate_dropped'] += 1
                continue
            seen[key] = len(out)
            out.append(f)
        # opposite pairs (hole-free faces only)
        canon = {}
        for i, f in enumerate(out):
            if len(f) != 1:
                continue
            o = f[0]
            k = min(range(len(o)), key=lambda j: o[j])
            canon[tuple(o[k:] + o[:k])] = i
        pairs = []
        for cyc, i in canon.items():
            r = cyc[::-1]
            k = min(range(len(r)), key=lambda j: r[j])
            rc = tuple(r[k:] + r[:k])
            j = canon.get(rc)
            if j is not None and i < j:
                pairs.append((i, j))
        if not pairs:
            return out
        # an edge of a pair must also be used twice by faces outside all pairs (the walls of the two touching
        # solids); double-sided surfaces (every face given twice) therefore stay untouched
        inpair = set(i for p_ in pairs for i in p_)
        rest = [f for i, f in enumerate(out) if i not in inpair]
        A, B, F = self.edge_arrays(rest) if rest else (np.zeros(0, np.int64),) * 3
        nv = 1 + max([i for f in out for lp in f for i in lp])
        key = np.minimum(A, B) * nv + np.maximum(A, B)
        uk, cnt = np.unique(key, return_counts=True)
        use = dict(zip(uk.tolist(), cnt.tolist()))
        drop = set()
        for i, j in pairs:
            o = out[i][0]
            m = len(o)
            if all(use.get(min(o[t], o[(t + 1) % m]) * nv + max(o[t], o[(t + 1) % m]), 0) >= 2 for t in range(m)):
                drop.add(i); drop.add(j)
        if drop:
            self.stats['contact_face_pairs_removed'] += len(drop) // 2
        self.last_twins = [(i, j) for i, j in pairs if i not in drop]
        if drop:
            keep = [i for i in range(len(out)) if i not in drop]
            ren = {o: n for n, o in enumerate(keep)}
            self.last_twins = [(ren[i], ren[j]) for i, j in self.last_twins]
            out = [out[i] for i in keep]
        return out

    def boundary_count(self, faces, nv):
        A, B, F = self.edge_arrays(faces)
        if len(A) == 0:
            return 0, A, B
        key = np.minimum(A, B) * nv + np.maximum(A, B)
        uk, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
        bnd = cnt[inv] == 1
        return int(bnd.sum()), A[bnd], B[bnd]

    def sew(self, faces, X, tol):
        """merge boundary vertices closer than tol (mm) - closes tessellation seams where two faces were exported with
        slightly different vertices (moves a vertex by < tol, never adds a face). Kept only if open edges decrease."""
        nb, ba, bb = self.boundary_count(faces, len(X))
        if nb == 0:
            return faces, 0
        bv = np.unique(np.concatenate([ba, bb]))
        if len(bv) > 100000:
            return faces, 0
        P = X[bv]
        order = np.argsort(P[:, 0], kind='stable')
        xs = P[order, 0]
        merged = 0
        rep = {}
        if SEW_NOCHAIN:
            # 6.1.9: leader clustering - in x order, an unassigned boundary vertex keeps its place and takes every
            # unassigned boundary vertex within tol of IT; no chaining, so no vertex moves by more than tol (6.0-6.1.8
            # merged through union-find chains: up to 0.33 mm at tol 0.1 in class-1 models)
            for ii in range(len(order)):
                i = order[ii]
                vi = int(bv[i])
                if vi in rep:
                    continue
                hi = np.searchsorted(xs, xs[ii] + tol, side='right')
                if hi <= ii + 1:
                    continue
                cj = order[ii + 1:hi]
                d = np.linalg.norm(P[cj] - P[i], axis=1)
                for j in cj[d <= tol].tolist():
                    vj = int(bv[j])
                    if vj != vi and vj not in rep:
                        rep[vj] = vi
                        merged += 1
        else:
            parent = {}

            def find(a):
                while parent.get(a, a) != a:
                    a = parent[a]
                return a
            for ii in range(len(order)):
                i = order[ii]
                hi = np.searchsorted(xs, xs[ii] + tol, side='right')
                if hi <= ii + 1:
                    continue
                cj = order[ii + 1:hi]
                d = np.linalg.norm(P[cj] - P[i], axis=1)
                for j in cj[d <= tol].tolist():
                    a, b = find(int(bv[i])), find(int(bv[j]))
                    if a != b:
                        parent[max(a, b)] = min(a, b)
                        merged += 1
            rep = {v: find(v) for v in list(parent.keys())}
        if not merged:
            return faces, 0
        mv = [v for v, r_ in rep.items() if v != r_]
        move = float(np.sqrt(((X[mv] - X[[rep[v] for v in mv]]) ** 2).sum(axis=1)).max()) if mv else 0.0
        out = []
        for f in faces:
            nf = []
            for k, lp in enumerate(f):
                q = [rep.get(i, i) for i in lp]
                c = [v for j, v in enumerate(q) if v != q[j - 1]] if len(q) > 1 else q
                if len(c) < 3 or len(set(c)) < 3:
                    if k == 0:
                        nf = None
                        break
                    continue
                nf.append(c)
            if nf:
                out.append(nf)
        # zero-area faces created by the merge are dropped
        if out:
            N = loop_normals(X, [f_[0] for f_ in out])
            keep = np.einsum('ij,ij->i', N, N) > 1e-20
            out = [f_ for f_, k in zip(out, keep.tolist()) if k]
        nb2, _, _ = self.boundary_count(out, len(X))
        if nb2 >= nb:
            return faces, 0
        self.stats['seam_vertices_merged'] += merged
        self.last_sew_move = max(self.last_sew_move, move)
        return out, merged

    def tjunctions(self, faces, X):
        """split boundary edges at boundary vertices lying on them (exact: the vertex is already on the edge)"""
        A, B, F = self.edge_arrays(faces)
        if len(A) == 0:
            return faces, 0
        nv = len(X)
        key = np.minimum(A, B) * nv + np.maximum(A, B)
        uk, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
        bnd = cnt[inv] == 1
        if not bnd.any():
            return faces, 0
        ba, bb, bf = A[bnd], B[bnd], F[bnd]
        bv = np.unique(np.concatenate([ba, bb]))
        if len(bv) > 200000:
            return faces, 0
        Pv = X[bv]
        order = np.argsort(Pv[:, 0])
        xs = Pv[order, 0]
        tol = self.tol_t
        inserts = {}
        for a, b, fi in zip(ba.tolist(), bb.tolist(), bf.tolist()):
            pa, pb = X[a], X[b]
            lo = np.searchsorted(xs, min(pa[0], pb[0]) - tol)
            hi = np.searchsorted(xs, max(pa[0], pb[0]) + tol, side='right')
            if hi <= lo:
                continue
            cand = bv[order[lo:hi]]
            cand = cand[(cand != a) & (cand != b)]
            if len(cand) == 0:
                continue
            d = pb - pa
            L2 = float(d @ d)
            if L2 <= 0:
                continue
            C = X[cand]
            t = ((C - pa) @ d) / L2
            Lq = math.sqrt(L2)
            ok = (t * Lq > tol) & ((1 - t) * Lq > tol)
            if not ok.any():
                continue
            C2, t2, c2 = C[ok], t[ok], cand[ok]
            proj = pa + np.outer(t2, d)
            dist = np.linalg.norm(C2 - proj, axis=1)
            sel = dist <= tol
            if not sel.any():
                continue
            ins = [int(v) for _, v in sorted(zip(t2[sel].tolist(), c2[sel].tolist()))]
            inserts[(fi, a, b)] = ins
        if not inserts:
            return faces, 0
        n = 0
        out = []
        for fi, f in enumerate(faces):
            nf = []
            hit = False
            for lp in f:
                m = len(lp)
                nl = []
                for j in range(m):
                    a, b = lp[j], lp[(j + 1) % m]
                    nl.append(a)
                    ins = inserts.get((fi, a, b))
                    if ins:
                        nl.extend(ins)
                        n += len(ins)
                        hit = True
                nf.append(nl)
            if hit and DESPIKE:
                # a collinear tail (the boundary runs out and back along one line) becomes a -> b -> a once its
                # T-junction vertex is in: the zero-width tail is cancelled (exact)
                nf2 = []
                for k, nl in enumerate(nf):
                    r_ = reduce_loop(nl)
                    if len(r_) != len(nl):
                        self.stats['spike_vertices_removed'] += len(nl) - len(r_)
                    if len(r_) < 3:
                        if k == 0:
                            nf2 = None
                            break
                        continue
                    nf2.append(r_)
                if nf2 is None:
                    self.stats['faces_zero_width_dropped'] += 1
                    continue
                if len(nf2) == 1 and len(set(nf2[0])) != len(nf2[0]):
                    for p_ in self._split_pinched(nf2[0]):
                        out.append([p_])
                    self.stats['faces_pinched_split'] += 1
                    continue
                nf = nf2
            out.append(nf)
        self.stats['tjunction_vertices_inserted'] += n
        return out, n

    def drop_degenerate(self, faces, X):
        """faces whose outer loop has no area (every vertex on one line, e.g. a collinear ear of a triangulated
        polygon): no surface - dropped (exact; the T-junction this can leave is split next). Such a face reached the
        writer as PLANE with DIRECTION (0,0,0), on which OCC raises and drops the whole solid (410b3c2d beam 7071G2)."""
        if not faces:
            return faces
        m = zero_area_mask(X, [f[0] for f in faces])
        if not m.any():
            return faces
        self.stats['faces_zero_area_dropped_late'] += int(m.sum())
        return [f for f, d in zip(faces, m.tolist()) if not d]

    def gap_stats(self, faces, X, cap=4000):
        """open source shell: its free edges (used by one face), non-manifold edges (3+ faces) and the largest distance
        from a point of a free edge (ends, quarter points, middle) to the nearest OTHER free edge (gap_max_mm; None when a
        free edge has no other free edge to match). Measured on the shell as written."""
        A, B, F = self.edge_arrays(faces)
        if len(A) == 0:
            return None
        nv = len(X)
        key = np.minimum(A, B) * nv + np.maximum(A, B)
        uk, first, cnt = np.unique(key, return_index=True, return_counts=True)
        free = first[cnt == 1]
        nmf = first[cnt >= 3]
        info = {'free_edges': int(len(free)), 'nonmanifold_edges': int(len(nmf)), 'gap_max_mm': 0.0}
        n = len(free)
        if n == 0:
            return info
        if n + len(nmf) > cap:
            info['gap_max_mm'] = None
            info['gap_note'] = 'more than %d free / non-manifold edges' % cap
            return info
        # candidates: the free edges first, then the non-manifold ones (gap_any_mm: nearest edge of either kind - the
        # width of a crack whose other side is an edge shared by 3+ faces, e.g. two overlapping coplanar faces)
        ce = np.concatenate([free, nmf])
        Pa = X[A[ce]]; D = X[B[ce]] - Pa
        o = Pa[0].copy()
        Pa = Pa - o                                  # local frame: precise far from the origin
        L2 = np.maximum(np.einsum('ij,ij->i', D, D), 1e-300)
        ts = np.array([0.0, 0.25, 0.5, 0.75, 1.0])
        g = 0.0; ga = 0.0
        for k in range(n):
            P = Pa[k] + np.outer(ts, D[k])                                  # (5, 3)
            R = P[:, None, :] - Pa[None, :, :]                              # (5, m, 3)
            t = np.clip(np.einsum('kmj,mj->km', R, D) / L2, 0.0, 1.0)
            d = np.linalg.norm(R - t[..., None] * D[None], axis=2)          # (5, m)
            d[:, k] = np.inf
            g = max(g, float(d[:, :n].min(axis=1).max()) if n > 1 else math.inf)
            ga = max(ga, float(d.min(axis=1).max()) if d.shape[1] > 1 else math.inf)
        info['gap_max_mm'] = round(g, 4) if math.isfinite(g) else None
        info['gap_any_mm'] = round(ga, 4) if math.isfinite(ga) else None
        return info

    def coplanar_union(self, faces, X):
        """open source shell whose bad edges (free / used by 3+ faces) come from overlapping coplanar faces (e.g. an end
        face given as two polygons that overlap in a 0.07 mm strip, or three overlapping faces one of which cancels the
        overlap): every group of coplanar faces touching a bad edge is replaced by the faces of its signed union - the
        plane is cut into the cells of all their boundaries, a cell is covered when the face orientations over it sum to
        >= 1 (outward) or <= -1 (inward). Exact: the union adds no area beyond the input faces and every vertex lies on an
        input boundary (input vertices, or crossings of input edges). -> (faces, X, n_groups) or None"""
        try:
            import shapely
            from shapely.geometry import Polygon, Point
            from shapely.ops import unary_union, polygonize
        except Exception:
            self.stats['coplanar_union_no_shapely'] += 1
            return None
        A, B, F = self.edge_arrays(faces)
        if len(A) == 0:
            return None
        nv = len(X)
        key = np.minimum(A, B) * nv + np.maximum(A, B)
        uk, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
        badf = sorted(set(F[cnt[inv] != 2].tolist()))
        if not badf or len(badf) > 400:
            return None
        loops0 = [f[0] for f in faces]
        N = loop_normals(X, loops0)
        ln = np.sqrt(np.einsum('ij,ij->i', N, N))
        ok_n = ln > 0
        U = np.zeros_like(N)
        U[ok_n] = N[ok_n] / ln[ok_n, None]
        tol = max(5.0 / self.qs, 0.05) if self.prec <= 3 else 0.05    # grouping: faces exported 0.02 mm off one plane
        used = set()
        new_faces = {}
        drop = set()
        Xl = [X]
        nextid = [nv]
        grid = {}
        for b in badf:
            if b in used or not ok_n[b]:
                continue
            nb = U[b]
            o = X[faces[b][0][0]].copy()
            # coplanar group: parallel normal (either sense) and every vertex within tol of the plane
            par = np.abs(U @ nb) >= 1 - 1e-5        # near-parallel; the vertex distance below decides
            grp = []
            for j in np.flatnonzero(par & ok_n).tolist():
                if j in used:
                    continue
                vj = [i for lp in faces[j] for i in lp]
                if float(np.abs((X[vj] - o) @ nb).max()) <= tol:
                    grp.append(j)
            if len(grp) < 2:
                continue
            u_, v_ = _plane_basis(nb)
            if float(np.dot(np.cross(u_, v_), nb)) < 0:
                v_ = -v_
            def P2(lp):
                Q_ = X[lp] - o
                return list(zip((Q_ @ u_).tolist(), (Q_ @ v_).tolist()))
            polys, signs = [], []
            bad = False
            for j in grp:
                pg = Polygon(P2(faces[j][0]), [P2(h) for h in faces[j][1:]])
                if not pg.is_valid or pg.area <= 0:
                    bad = True
                    break
                polys.append(pg)
                signs.append(1 if float(U[j] @ nb) > 0 else -1)
            if bad:
                continue
            cells = list(polygonize(unary_union([pg.boundary for pg in polys])))
            pos, neg = [], []
            zero = False
            for c in cells:
                if c.area <= 1e-12:
                    continue
                pt = c.representative_point()
                hit = [sg for pg, sg in zip(polys, signs) if pg.covers(pt)]
                cov = sum(hit)
                if cov >= 1:
                    pos.append(c)
                elif cov <= -1:
                    neg.append(c)
                elif hit:
                    zero = True        # faces cancelling to nothing (contact wall / double-sided sheet): not this rule
                    break
            if zero:
                continue
            # vertex lookup: 2D coordinates of the group's vertices
            vmap = {}
            for j in grp:
                for lp in faces[j]:
                    for i, (x_, y_) in zip(lp, P2(lp)):
                        vmap[(round(x_, 6), round(y_, 6))] = i
            def vid(x_, y_):
                k_ = (round(x_, 6), round(y_, 6))
                i = vmap.get(k_)
                if i is not None:
                    return i
                q = np.round((o + x_ * u_ + y_ * v_) * self.qs) / self.qs     # on the output grid
                gk = tuple(np.round(q * self.qs).astype(np.int64).tolist())
                i = grid.get(gk)
                if i is None:
                    i = nextid[0]; nextid[0] += 1
                    Xl.append(q[None, :]); grid[gk] = i
                    self.stats['coplanar_union_vertices_added'] += 1
                vmap[k_] = i
                return i
            out = []
            for region, sg in ((unary_union(pos) if pos else None, 1), (unary_union(neg) if neg else None, -1)):
                if region is None or region.is_empty:
                    continue
                parts = list(region.geoms) if hasattr(region, 'geoms') else [region]
                for pg in parts:
                    if pg.geom_type != 'Polygon' or pg.area <= 0:
                        continue
                    pg = shapely.geometry.polygon.orient(pg, 1.0 if sg > 0 else -1.0)
                    ext = [vid(x_, y_) for x_, y_ in list(pg.exterior.coords)[:-1]]
                    holes = [[vid(x_, y_) for x_, y_ in list(r_.coords)[:-1]] for r_ in pg.interiors]
                    ext = reduce_loop(ext)
                    if len(ext) < 3:
                        continue
                    fnew = [ext] + [h for h in (reduce_loop(h) for h in holes) if len(h) >= 3]
                    # a union of faces that were each planar within tol_planar but lie up to `tol` apart: split into
                    # triangles on its own vertices when it is not planar itself (as clean_faces does)
                    allv = [i for lp in fnew for i in lp]
                    Xa = np.vstack(Xl)
                    nrm = newell(Xa[ext])
                    nn = float(np.linalg.norm(nrm))
                    if nn > 0 and float(np.abs((Xa[allv] - Xa[ext[0]]) @ (nrm / nn)).max()) > self.tol_planar:
                        tris = earcut(fnew, Xa, nrm / nn)
                        if tris:
                            self.stats['coplanar_union_faces_triangulated'] += 1
                            out.extend([[list(t)] for t in tris])
                            continue
                    out.append(fnew)
            if not out:
                continue
            for j in grp:
                used.add(j); drop.add(j)
            new_faces[grp[0]] = out
        if not new_faces:
            return None
        res = []
        for i, f in enumerate(faces):
            if i in new_faces:
                res.extend(new_faces[i])
            elif i not in drop:
                res.append(f)
        X2 = np.vstack(Xl) if len(Xl) > 1 else X
        return res, X2, len(new_faces)

    def bad_edge_count(self, faces, nv):
        A, B, F = self.edge_arrays(faces)
        if len(A) == 0:
            return 0, 0
        key = np.minimum(A, B) * nv + np.maximum(A, B)
        uk, cnt = np.unique(key, return_counts=True)
        return int((cnt != 2).sum()), len(uk)

    def union_presew(self, faces, X):
        """a piece with a few bad edges (free / 3+ faces): coplanar_union before sewing; kept only when the bad edges,
        counted after the T-junction split, decrease -> (faces, X) or None"""
        nb, ne = self.bad_edge_count(faces, len(X))
        if nb == 0 or nb > 64 or nb > 0.25 * ne:
            return None
        cu = self.coplanar_union(faces, X)
        if cu is None:
            return None
        fsu, X2, ng = cu
        st0 = dict(self.stats)
        a_, _ = self.tjunctions(faces, X)
        b_, _ = self.tjunctions(fsu, X2)
        self.stats.clear(); self.stats.update(st0)      # trial splits are not counted
        n0, _ = self.bad_edge_count(a_, len(X))
        n1, _ = self.bad_edge_count(b_, len(X2))
        if n1 < n0:
            self.stats['coplanar_overlap_groups_merged'] += ng
            return fsu, X2
        return None

    def close_within(self, faces, X, tol):
        """an open source shell whose every free edge lies within tol of another free edge: its boundary vertices
        within tol merged + T-junctions split (moves a vertex by <= tol, adds no face). -> closed Shell or None"""
        fs, nm = self.sew(faces, X, tol)
        fs, nt = self.tjunctions(fs, X)
        shs = self.shells(fs, X, 'solid')
        if len(shs) == 1 and shs[0].closed and shs[0].vol != 0:
            return shs[0]
        return None

    # -------------------------------------------------------------- components + orientation
    def shells(self, faces, X, role):
        """split into edge-connected components, orient each consistently and outward -> [Shell]"""
        if not faces:
            return []
        A, B, F = self.edge_arrays(faces)
        nv = len(X)
        nf = len(faces)
        lo, hi = np.minimum(A, B), np.maximum(A, B)
        key = lo * nv + hi
        order = np.argsort(key, kind='stable')
        ks = key[order]
        # groups of equal keys
        brk = np.flatnonzero(np.diff(ks)) + 1
        starts = np.concatenate([[0], brk]); ends = np.concatenate([brk, [len(ks)]])
        cnt = ends - starts
        # manifold edges: exactly 2 uses
        two = starts[cnt == 2]
        e1 = order[two]; e2 = order[two + 1]
        f1, f2 = F[e1], F[e2]
        same_dir = (A[e1] == A[e2])          # both uses a->b : inconsistent
        # union-find by label propagation
        lab = np.arange(nf)
        if len(f1):
            for _ in range(200):
                m = np.minimum(lab[f1], lab[f2])
                old = lab.copy()
                np.minimum.at(lab, f1, m); np.minimum.at(lab, f2, m)
                lab = lab[lab]
                lab = lab[lab]
                if np.array_equal(old, lab):
                    break
        comps = collections.defaultdict(list)
        for fi, l in enumerate(lab.tolist()):
            comps[l].append(fi)
        # per component: closed? (every edge of the component used exactly twice inside the component)
        # closed per component: every edge used exactly twice by faces of the same component
        lu = lab[F]
        k2 = key * (nf + 1) + lu
        u2, inv2, c2 = np.unique(k2, return_inverse=True, return_counts=True)
        face_open = np.zeros(nf, bool)
        np.logical_or.at(face_open, F, c2[inv2] != 2)
        # inconsistent pairs per component
        bad = collections.defaultdict(list)
        if len(f1):
            for a, b in zip(f1[same_dir].tolist(), f2[same_dir].tolist()):
                bad[lab[a]].append((a, b))
        out = []
        for l, fl in comps.items():
            closed = not face_open[fl].any()
            fl_faces = [faces[i] for i in fl]
            if l in bad:
                fl_faces, ok = self._orient_bfs(fl, faces, f1, f2, same_dir, lab, l)
                self.stats['shells_orientation_unified'] += 1
                if not ok:
                    self.stats['shells_non_orientable'] += 1
            vol = self.signed_volume(fl_faces, X)
            sh = Shell(fl_faces, closed, vol, role)
            out.append(sh)
        if len(out) > 1:
            self.stats['pieces_split_into_components'] += 1
        return out

    def _orient_bfs(self, fl, faces, f1, f2, same_dir, lab, l):
        sel = (lab[f1] == l)
        adj = collections.defaultdict(list)
        for a, b, s in zip(f1[sel].tolist(), f2[sel].tolist(), same_dir[sel].tolist()):
            adj[a].append((b, s)); adj[b].append((a, s))
        flip = {}
        ok = True
        for s0 in fl:
            if s0 in flip:
                continue
            flip[s0] = False
            stack = [s0]
            while stack:
                x = stack.pop()
                for y, s in adj[x]:
                    want = flip[x] ^ s
                    if y not in flip:
                        flip[y] = want; stack.append(y)
                    elif flip[y] != want:
                        ok = False
        res = []
        for i in fl:
            f = faces[i]
            res.append([lp[::-1] for lp in f] if flip.get(i) else f)
        return res, ok

    @staticmethod
    def signed_volume(faces, X):
        if not faces:
            return 0.0
        c = X[faces[0][0][0]]
        tot = 0.0
        T0, T1, T2 = [], [], []
        for f in faces:
            for lp in f:
                p0 = lp[0]
                for j in range(1, len(lp) - 1):
                    T0.append(p0); T1.append(lp[j]); T2.append(lp[j + 1])
        if not T0:
            return 0.0
        a = X[T0] - c; b = X[T1] - c; d = X[T2] - c
        return float(np.einsum('ij,ij->i', a, np.cross(b, d)).sum() / 6.0)

    @staticmethod
    def tris_of(faces, X):
        T0, T1, T2 = [], [], []
        for f in faces:
            for lp in f:
                p0 = lp[0]
                for j in range(1, len(lp) - 1):
                    T0.append(p0); T1.append(lp[j]); T2.append(lp[j + 1])
        return X[T0], X[T1], X[T2]

    @staticmethod
    def inside(points, tri):
        """points (k,3) inside the closed triangle soup tri=(A,B,C)? parity of ray hits, majority over 3 directions"""
        A, B, C = tri
        res = np.zeros(len(points), int)
        for dvec in ((0.5773502, 0.5773503, 0.5773504), (-0.30151, 0.90453, 0.30151), (0.70711, -0.10000, -0.69999)):
            d = np.array(dvec); d /= np.linalg.norm(d)
            e1 = B - A; e2 = C - A
            pv = np.cross(d, e2)
            det = np.einsum('ij,ij->i', e1, pv)
            okd = np.abs(det) > 1e-12
            inv = np.where(okd, 1.0 / np.where(okd, det, 1.0), 0.0)
            for k, p in enumerate(points):
                tv = p - A
                u = np.einsum('ij,ij->i', tv, pv) * inv
                qv = np.cross(tv, e1)
                v = (qv @ d) * inv
                t = np.einsum('ij,ij->i', e2, qv) * inv
                hit = okd & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1e-9)
                res[k] += int(hit.sum()) & 1
        return res >= 2

    def clearly_open(self, faces, X):
        """more than half of the edges free (loose faces): not a solid with a defect but an open surface"""
        A, B, F = self.edge_arrays(faces)
        if len(A) == 0:
            return True
        key = np.minimum(A, B) * len(X) + np.maximum(A, B)
        uk, cnt = np.unique(key, return_counts=True)
        free = int((cnt == 1).sum())
        return free > 0.5 * len(uk) or len(faces) <= 2

    # -------------------------------------------------------------- coplanar merge
    def merge_coplanar(self, faces, X):
        """adjacent faces of one oriented shell lying in one plane (every vertex within tol_planar of the seed face's
        plane, same facing) become one polygon face (with holes): exact - the surface and the boundary vertices are
        unchanged, only interior edges disappear. Groups whose boundary is not a set of simple loops (pinch vertex,
        several outer loops) are left as they are."""
        nf = len(faces)
        if nf < 3:
            return faces
        single = [len(f) == 1 for f in faces]
        N = loop_normals(X, [f[0] for f in faces])
        ar = np.sqrt(np.einsum('ij,ij->i', N, N))
        ar[ar <= 0] = 1e-300
        U = (N / ar[:, None]).tolist()
        emap = {}
        for fi, f in enumerate(faces):
            if not single[fi]:
                continue
            lp = f[0]
            m = len(lp)
            for j in range(m):
                emap[(lp[j], lp[(j + 1) % m])] = fi
        tol = self.tol_planar
        group = [-1] * nf
        groups = []
        for seed in np.argsort(-ar).tolist():
            if group[seed] != -1 or not single[seed]:
                continue
            g = len(groups)
            group[seed] = g
            mem = [seed]
            n0 = U[seed]
            n0a = np.array(n0)
            p0 = X[faces[seed][0][0]]
            stack = [seed]
            while stack:
                fi = stack.pop()
                lp = faces[fi][0]
                m = len(lp)
                for j in range(m):
                    nb = emap.get((lp[(j + 1) % m], lp[j]))
                    if nb is None or group[nb] != -1:
                        continue
                    u = U[nb]
                    if u[0] * n0[0] + u[1] * n0[1] + u[2] * n0[2] < 0.999:
                        continue
                    if np.abs((X[faces[nb][0]] - p0) @ n0a).max() > tol:
                        continue
                    group[nb] = g
                    mem.append(nb)
                    stack.append(nb)
            groups.append(mem)
        out = [f for fi, f in enumerate(faces) if not single[fi]]
        merged = 0
        for mem in groups:
            if len(mem) == 1:
                out.append(faces[mem[0]])
                continue
            mset = set(mem)
            nxt = {}
            ok = True
            for fi in mem:
                lp = faces[fi][0]
                m = len(lp)
                for j in range(m):
                    a, b = lp[j], lp[(j + 1) % m]
                    nb = emap.get((b, a))
                    if nb is not None and nb in mset:
                        continue
                    if a in nxt:
                        ok = False
                        break
                    nxt[a] = b
                if not ok:
                    break
            loops = []
            if ok:
                seen = set()
                for st in list(nxt):
                    if st in seen:
                        continue
                    lp = []
                    v = st
                    while v is not None and v not in seen:
                        seen.add(v); lp.append(v); v = nxt.get(v)
                    if v != st or len(lp) < 3:
                        ok = False
                        break
                    loops.append(lp)
            if ok and loops:
                n0a = np.array(U[mem[0]])
                sg = [float(newell(X[lp]) @ n0a) for lp in loops]
                outer = [lp for lp, a in zip(loops, sg) if a > 0]
                holes = [lp for lp, a in zip(loops, sg) if a < 0]
                if len(outer) == 1 and len(outer) + len(holes) == len(loops):
                    out.append([outer[0]] + holes)
                    merged += len(mem) - 1
                    continue
            out.extend(faces[fi] for fi in mem)
        if merged:
            self.stats['coplanar_faces_merged'] += merged
        return out



def flat_shell(s, X, tol):
    """a closed shell all of whose vertices lie within tol of one plane encloses no volume (a surface patch covered
    from both sides): not a solid. Cached on the shell (Shell.flat)."""
    if s.flat is not None:
        return s.flat
    flat = False
    if s.closed:
        loops = [f[0] for f in s.faces]
        N = loop_normals(X, loops)
        area = 0.5 * float(np.sqrt(np.einsum('ij,ij->i', N, N)).sum())
        if abs(s.vol) <= area * tol:
            idx = np.unique(np.fromiter((i for f in s.faces for lp in f for i in lp), np.int64))
            P = X[idx] - X[idx].mean(0)
            if len(P) < 4:
                flat = True
            else:
                n = np.linalg.svd(P, full_matrices=False)[2][-1]
                flat = float(np.abs(P @ n).max()) <= tol
    s.flat = flat
    return flat


def organise_solids(shells, X, repair, allow_voids=True):
    """closed shells of one solid piece -> list of solid Shells (outward, with .voids), list of open Shells.
    A closed component enclosed by another closed component and wound opposite to it in the source is a void of it;
    otherwise it is a separate solid (overlapping solids stay separate). Each outer shell is made positive."""
    closed = [s for s in shells if s.closed and abs(s.vol) > 0 and not (DEGEN_FIX and flat_shell(s, X, repair.tol_planar))]
    opened = [s for s in shells if not s.closed or s.vol == 0 or (DEGEN_FIX and flat_shell(s, X, repair.tol_planar))]
    if len(closed) > 1:
        repair.stats['shells_multi_component'] += 1
    # bbox + size
    info = []
    for s in closed:
        idx = np.unique(np.fromiter((i for f in s.faces for lp in f for i in lp), np.int64))
        P = X[idx]
        info.append((P.min(0), P.max(0)))
    order = sorted(range(len(closed)), key=lambda i: -abs(closed[i].vol))
    parent = {}
    tri_cache = {}
    for pos, i in enumerate(order):
        bi = info[i]
        for j in order[:pos]:
            if parent.get(j) is not None:
                continue   # voids cannot contain shells we care about
            bj = info[j]
            if (bi[0] >= bj[0] - 1e-9).all() and (bi[1] <= bj[1] + 1e-9).all():
                if j not in tri_cache:
                    tri_cache[j] = Repair.tris_of(closed[j].faces, X)
                # probe points: centroids of the 3 largest faces of shell i (on its surface)
                fs = closed[i].faces
                cents = []
                for f in sorted(fs, key=lambda f: -len(f[0]))[:3]:
                    cents.append(X[f[0]].mean(0))
                if all(Repair.inside(np.array(cents), tri_cache[j])):
                    if allow_voids and (closed[i].vol > 0) != (closed[j].vol > 0):
                        parent[i] = j
                    break
    solids = []
    for i in order:
        s = closed[i]
        if parent.get(i) is not None:
            continue
        if s.vol < 0:
            s.faces = [[lp[::-1] for lp in f] for f in s.faces]
            s.vol = -s.vol
            s.tags.add('reoriented')
            repair.stats['shells_reoriented'] += 1
        solids.append(s)
    for i, j in parent.items():
        v = closed[i]
        o = closed[j]
        # void must be wound opposite to the (now positive) outer shell: negative volume
        if v.vol > 0:
            v.faces = [[lp[::-1] for lp in f] for f in v.faces]
            v.vol = -v.vol
        o.voids.append(v)
        o.tags.add('void')
        repair.stats['voids_found'] += 1
    return solids, opened


# ====================================================================================================== STEP writer

HEADER_IDS = {}


def header_text(name, prefix='.MILLI.', unc=0.01):
    """fixed header + global entities #101..#120 (contexts, units, origin, axis-aligned directions)"""
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    h = ["ISO-10303-21;\nHEADER;\n", "FILE_DESCRIPTION((''),'2;1');\n",
         "FILE_NAME('%s','%s',(''),(''),'%s','ifcopenshell','');\n" % (step_str(name, 200), ts, VERSION),
         "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 3 1 1 }'));\n", "ENDSEC;\nDATA;\n"]
    g = ["#101=APPLICATION_CONTEXT('automotive design');",
         "#102=APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2000,#101);",
         "#103=PRODUCT_CONTEXT('',#101,'mechanical');",
         "#104=PRODUCT_DEFINITION_CONTEXT('part definition',#101,'design');",
         "#105=(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(%s,.METRE.));" % prefix,
         "#106=(NAMED_UNIT(*)PLANE_ANGLE_UNIT()SI_UNIT($,.RADIAN.));",
         "#107=(NAMED_UNIT(*)SOLID_ANGLE_UNIT()SI_UNIT($,.STERADIAN.));",
         "#108=UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(%s),#105,'distance_accuracy_value','');" % _r(unc),
         "#109=(GEOMETRIC_REPRESENTATION_CONTEXT(3)GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#108))"
         "GLOBAL_UNIT_ASSIGNED_CONTEXT((#105,#106,#107))REPRESENTATION_CONTEXT('',''));",
         "#110=CARTESIAN_POINT('',(0.,0.,0.));",
         "#111=DIRECTION('',(0.,0.,1.));",
         "#112=DIRECTION('',(1.,0.,0.));",
         "#113=AXIS2_PLACEMENT_3D('',#110,#111,#112);",
         "#114=DIRECTION('',(0.,0.,-1.));",
         "#115=DIRECTION('',(-1.,0.,0.));",
         "#116=DIRECTION('',(0.,1.,0.));",
         "#117=DIRECTION('',(0.,-1.,0.));"]
    return ''.join(h), '\n'.join(g) + '\n'


COMMON_DIRS = {(0, 0, 1): 111, (1, 0, 0): 112, (0, 0, -1): 114, (-1, 0, 0): 115, (0, 1, 0): 116, (0, -1, 0): 117}
FIRST_ID = 200
TAIL = "ENDSEC;\nEND-ISO-10303-21;\n"


class Frag:
    __slots__ = ('off', 'size', 'pd', 'sdr', 'nsol', 'nsurf', 'nfaces', 'vol', 'nopen', 'ghash', 'needs', 'far')

    def __init__(self, off, size, pd, sdr, nsol, nsurf, nfaces, vol, nopen=0, ghash=None, needs=None, far=None):
        self.off = off; self.size = size; self.pd = pd; self.sdr = sdr; self.nsol = nsol; self.nsurf = nsurf
        self.nfaces = nfaces; self.vol = vol; self.nopen = nopen; self.ghash = ghash; self.needs = needs
        self.far = far          # whole-km offset (mm) when the part lies beyond FAR_MM from the origin (see far_offset)


# Far from the origin (geo-referenced models: 1.5e9 / 3.0e9 mm seen in SDS/2 exports) OpenCASCADE's 1e-7 mm tolerances
# are finer than the coordinates' own floating-point resolution (ulp(3e9) = 4.8e-7 mm): the STEP reader's shape healing
# throws and BRepCheck fails solids that are valid - in place and when placed by a MAPPED_ITEM alike. The same solid
# written 1 km from the origin reads back valid. Opt-in (V6_FAR_VERIFY=1, to ship together with the same rule in the
# grader's step_check): a far part that fails every in-place level (L0..L2) is verified once more on a copy of its own
# STEP block translated by a whole number of kilometres; if that copy is a valid solid the exact L0 solid is kept (tag
# far-origin). The output STEP always keeps the source coordinates. (Finding and code: IFC verification-residue fixer.)
FAR_MM = float(os.environ.get('V6_FAR_MM', '1e7'))
# 6.1.6: hard-off. Far-mode output read in place was invalid on far models (f451e1f2: 9,243 of 13,093 solids; 15,060 of
# 38,646 overall vs 1 of 38,640 in normal mode). V6_FAR_VERIFY is ignored; V6_FAR_VERIFY_TEST=1 enables it for tests only.
FAR_VERIFY = os.environ.get('V6_FAR_VERIFY_TEST', '0') == '1'


def far_offset(lo, hi):
    """whole-km offset (tuple of int mm) for a part with world bbox lo..hi beyond FAR_MM, else None"""
    if max(float(np.abs(lo).max()), float(np.abs(hi).max())) <= FAR_MM:
        return None
    return tuple(int(v) for v in (np.floor(np.asarray(lo, np.float64) / 1e6) * 1e6).tolist())


_CP_RE = re.compile(rb"CARTESIAN_POINT\('',\(([^)]*)\)\)")


def shift_points(data, off):
    """every CARTESIAN_POINT of a STEP block moved by -off (mm), exact decimal arithmetic"""
    from decimal import Decimal
    o = [Decimal(int(v)) for v in off]

    def one(m):
        vals = m.group(1).split(b',')
        res = []
        for k, v in enumerate(vals):
            x = format(Decimal(v.decode().strip()) - (o[k] if k < 3 else 0), 'f')
            res.append(x if '.' in x else x + '.')
        return b"CARTESIAN_POINT('',(" + ','.join(res).encode() + b"))"
    return _CP_RE.sub(one, data)


class Shared:
    """geometry written once (representation + REPRESENTATION_MAP), placed by every instance with a MAPPED_ITEM"""
    __slots__ = ('key', 'off', 'size', 'rmap', 'nsol', 'nsurf', 'nfaces', 'vol', 'nopen', 'lo', 'hi', 'src', 'tags', 'curved', 'gap', 'merged', 'sew')

    def __init__(self, key, off, size, rmap, nsol, nsurf, nfaces, vol, nopen, lo, hi):
        self.key = key; self.off = off; self.size = size; self.rmap = rmap; self.nsol = nsol; self.nsurf = nsurf
        self.nfaces = nfaces; self.vol = vol; self.nopen = nopen; self.lo = lo; self.hi = hi; self.src = None
        self.tags = set(); self.curved = False; self.gap = None; self.merged = False; self.sew = 0.0


class Spool:
    """fragments (all entities of one part) appended to a spool file with globally unique ids"""

    def __init__(self, path, prec, noplane=False):
        self.path = path
        self.fh = open(path, 'wb', buffering=1 << 22)
        self.off = 0
        self.n = FIRST_ID
        self.prec = prec
        self.fmt = '%.' + str(prec) + 'f'
        self.qs = 10.0 ** prec
        self.noplane = noplane
        self.bb = [1e300, 1e300, 1e300, -1e300, -1e300, -1e300]
        self.n_faces_total = 0
        self.degenerate_skipped = 0

    def close(self):
        self.fh.flush(); self.fh.close()

    def emit(self, name, pid, desc, solids, surfaces, X, shared_key=None):
        """one part -> Frag. solids: [Shell (outward) with .voids]; surfaces: [Shell] (open shells); X welded coords mm.
        shared_key: write the geometry as a shared representation (+ REPRESENTATION_MAP) instead of a part -> Shared"""
        shells = []
        for s_ in solids:
            shells.append(s_)
            shells.extend(s_.voids)
        shells.extend(surfaces)
        faces = [f for sh in shells for f in sh.faces]
        if not faces:
            return None
        dg = zero_area_mask(X, [f[0] for f in faces])
        if dg.any():
            # last guard (6.1.8): a face without area has no plane; written with DIRECTION (0,0,0) it makes OCC drop the
            # whole solid. Repair drops such faces before the T-junction split, so this should not trigger.
            self.degenerate_skipped += int(dg.sum())
            k = 0
            for sh in shells:
                m = len(sh.faces)
                sh.faces = [f for f, d in zip(sh.faces, dg[k:k + m].tolist()) if not d]
                k += m
            for s_ in solids:
                s_.voids = [v for v in s_.voids if v.faces]
            solids = [s_ for s_ in solids if s_.faces]
            surfaces = [x for x in surfaces if x.faces]
            shells = []
            for s_ in solids:
                shells.append(s_)
                shells.extend(s_.voids)
            shells.extend(surfaces)
            faces = [f for sh in shells for f in sh.faces]
            if not faces:
                return None
        buf = []
        ap = buf.append
        n = self.n
        fmt = self.fmt
        # points (every vertex used by a loop), formatted in one go
        used = np.unique(np.fromiter((i for f in faces for lp in f for i in lp), np.int64))
        coords = X[used]
        lo, hi = coords.min(0), coords.max(0)
        b = self.bb if shared_key is None else [0.0] * 6
        if shared_key is None:
            for k in range(3):
                b[k] = min(b[k], float(lo[k])); b[k + 3] = max(b[k + 3], float(hi[k]))

        def num(x):
            s = fmt % x
            if '.' in s:
                s = s.rstrip('0')
            else:
                s += '.'
            return '0.' if s == '-0.' else s
        pid_of = {}
        for vi, (x, y, z) in zip(used.tolist(), coords.tolist()):
            n += 1
            ap("#%d=CARTESIAN_POINT('',(%s,%s,%s));\n" % (n, num(x), num(y), num(z)))
            pid_of[vi] = n
        # face planes: normals of all outer loops at once
        N = loop_normals(X, [f[0] for f in faces])
        ln = np.sqrt(np.einsum('ij,ij->i', N, N))
        ln[ln <= 0] = 1.0
        N = N / ln[:, None]
        Nl = np.round(N, 9).tolist()
        p0 = X[np.fromiter((f[0][0] for f in faces), np.int64, len(faces))]
        dl = np.round(np.einsum('ij,ij->i', N, p0), self.prec + 1).tolist()
        dirs = {}
        planes = {}
        fid = []
        for fi, f in enumerate(faces):
            bounds = []
            for k, lp in enumerate(f):
                n += 1
                ap("#%d=POLY_LOOP('',(%s));\n" % (n, ','.join(['#%d' % pid_of[i] for i in lp])))
                n += 1
                ap("#%d=%s('',#%d,.T.);\n" % (n, 'FACE_OUTER_BOUND' if (k == 0 and len(f) > 1) else 'FACE_BOUND', n - 1))
                bounds.append(n)
            nx, ny, nz = Nl[fi]
            pk = (nx, ny, nz, dl[fi])
            pl = planes.get(pk)
            if pl is None:
                dk = (nx, ny, nz)
                dn = COMMON_DIRS.get(dk) or dirs.get(dk)
                if dn is None:
                    n += 1
                    ap("#%d=DIRECTION('',(%s,%s,%s));\n" % (n, _rd(nx), _rd(ny), _rd(nz)))
                    dirs[dk] = dn = n
                n += 1
                ap("#%d=AXIS2_PLACEMENT_3D('',#%d,#%d,$);\n" % (n, pid_of[f[0][0]], dn))
                n += 1
                ap("#%d=PLANE('',#%d);\n" % (n, n - 1))
                planes[pk] = pl = n
            n += 1
            ap("#%d=FACE_SURFACE('',(%s),#%d,.T.);\n" % (n, ','.join(['#%d' % x for x in bounds]), pl))
            fid.append(n)
        # shells (one id per shell, in the order of `shells`); surfaces are OPEN_SHELLs
        pos = 0
        sid = {}
        surf_set = set(id(x) for x in surfaces)
        items = []
        has_voids = False
        vol = 0.0
        for sh in shells:
            m = len(sh.faces)
            ids = fid[pos:pos + m]
            pos += m
            n += 1
            sid[id(sh)] = n
            ap("#%d=%s('',(%s));\n" % (n, 'OPEN_SHELL' if id(sh) in surf_set else 'CLOSED_SHELL', ','.join(['#%d' % x for x in ids])))
        for s_ in solids:
            vol += s_.vol
            if s_.voids:
                has_voids = True
                vids = []
                for v in s_.voids:
                    n += 1
                    ap("#%d=ORIENTED_CLOSED_SHELL('',*,#%d,.F.);\n" % (n, sid[id(v)]))
                    vids.append(n)
                    vol += v.vol
                n += 1
                ap("#%d=BREP_WITH_VOIDS('',#%d,(%s));\n" % (n, sid[id(s_)], ','.join(['#%d' % x for x in vids])))
            else:
                n += 1
                ap("#%d=FACETED_BREP('',#%d);\n" % (n, sid[id(s_)]))
            items.append(n)
        if surfaces:
            n += 1
            ap("#%d=SHELL_BASED_SURFACE_MODEL('',(%s));\n" % (n, ','.join(['#%d' % sid[id(x)] for x in surfaces])))
            items.append(n)
        if surfaces and not solids:
            kind = 'MANIFOLD_SURFACE_SHAPE_REPRESENTATION'
        elif surfaces or has_voids:
            kind = 'SHAPE_REPRESENTATION'
        else:
            kind = 'FACETED_BREP_SHAPE_REPRESENTATION'
        if shared_key is not None:
            n += 1
            ap("#%d=%s('',(#113,%s),#109);\n" % (n, kind, ','.join(['#%d' % i for i in items])))
            n += 1
            ap("#%d=REPRESENTATION_MAP(#113,#%d);\n" % (n, n - 1))
            self.n = n
            data = ''.join(buf).encode('ascii', 'replace')
            off = self.off
            self.fh.write(data)
            self.off += len(data)
            # (the bbox of instances is accumulated when they are placed)
            return Shared(shared_key, off, len(data), n, len(solids), len(surfaces), len(faces), vol,
                          sum(1 for x in solids if not x.closed), lo, hi)
        nm = step_str(name or 'part')
        n += 1; prod = n
        ap("#%d=PRODUCT('%s','%s','%s',(#103));\n" % (n, step_str(pid, 64) if pid else nm, nm, step_str(desc or '', 120)))
        n += 1
        ap("#%d=PRODUCT_RELATED_PRODUCT_CATEGORY('part','',(#%d));\n" % (n, prod))
        n += 1
        ap("#%d=PRODUCT_DEFINITION_FORMATION('','',#%d);\n" % (n, prod))
        n += 1; pd = n
        ap("#%d=PRODUCT_DEFINITION('design','',#%d,#104);\n" % (n, n - 1))
        n += 1
        ap("#%d=PRODUCT_DEFINITION_SHAPE('','',#%d);\n" % (n, pd))
        n += 1
        ap("#%d=%s('%s',(#113,%s),#109);\n" % (n, kind, nm, ','.join(['#%d' % i for i in items])))
        n += 1; sdr = n
        ap("#%d=SHAPE_DEFINITION_REPRESENTATION(#%d,#%d);\n" % (n, n - 2, n - 1))
        self.n = n
        data = ''.join(buf).encode('ascii', 'replace')
        off = self.off
        self.fh.write(data)
        self.off += len(data)
        # translation-invariant geometry hash: identical parts (mapped copies) are verified once
        import hashlib
        h = hashlib.blake2b(digest_size=16)
        h.update(np.round((coords - coords[0]) * self.qs).astype(np.int64).tobytes())
        loc = {v: k for k, v in enumerate(used.tolist())}
        h.update(np.fromiter((loc[i] if j else -1 - loc[i] for f in faces for lp in f for j, i in enumerate(lp)), np.int64).tobytes())
        h.update(repr([(len(s_.faces), len(s_.voids), s_.closed) for s_ in solids] + [(len(x.faces),) for x in surfaces]).encode())
        far = far_offset(lo, hi)
        return Frag(off, len(data), pd, sdr, len(solids), len(surfaces), len(faces), vol,
                    sum(1 for x in solids if not x.closed), h.hexdigest() if far is None else None, far=far)

    def emit_instance(self, name, pid, desc, sh, R, t):
        """a part that places shared geometry: MAPPED_ITEM(REPRESENTATION_MAP, AXIS2_PLACEMENT_3D(t, R[:,2], R[:,0]))"""
        buf = []
        ap = buf.append
        n = self.n
        n += 1
        ap("#%d=CARTESIAN_POINT('',(%s,%s,%s));\n" % (n, _rfix(t[0]), _rfix(t[1]), _rfix(t[2])))
        n += 1
        ap("#%d=DIRECTION('',(%s,%s,%s));\n" % (n, _r(R[0][2]), _r(R[1][2]), _r(R[2][2])))
        n += 1
        ap("#%d=DIRECTION('',(%s,%s,%s));\n" % (n, _r(R[0][0]), _r(R[1][0]), _r(R[2][0])))
        n += 1
        ap("#%d=AXIS2_PLACEMENT_3D('',#%d,#%d,#%d);\n" % (n, n - 3, n - 2, n - 1))
        n += 1
        ap("#%d=MAPPED_ITEM('',#%d,#%d);\n" % (n, sh.rmap, n - 1))
        mi = n
        nm = step_str(name or 'part')
        n += 1; prod = n
        ap("#%d=PRODUCT('%s','%s','%s',(#103));\n" % (n, step_str(pid, 64) if pid else nm, nm, step_str(desc or '', 120)))
        n += 1
        ap("#%d=PRODUCT_RELATED_PRODUCT_CATEGORY('part','',(#%d));\n" % (n, prod))
        n += 1
        ap("#%d=PRODUCT_DEFINITION_FORMATION('','',#%d);\n" % (n, prod))
        n += 1; pd = n
        ap("#%d=PRODUCT_DEFINITION('design','',#%d,#104);\n" % (n, n - 1))
        n += 1
        ap("#%d=PRODUCT_DEFINITION_SHAPE('','',#%d);\n" % (n, pd))
        n += 1
        ap("#%d=SHAPE_REPRESENTATION('%s',(#113,#%d),#109);\n" % (n, nm, mi))
        n += 1; sdr = n
        ap("#%d=SHAPE_DEFINITION_REPRESENTATION(#%d,#%d);\n" % (n, n - 2, n - 1))
        self.n = n
        data = ''.join(buf).encode('ascii', 'replace')
        off = self.off
        self.fh.write(data)
        self.off += len(data)
        # bbox: the 8 corners of the shared bbox, placed
        Rm = np.array(R)
        lo, hi = sh.lo, sh.hi
        C = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]) @ Rm.T + np.array(t)
        b = self.bb
        for k in range(3):
            b[k] = min(b[k], float(C[:, k].min())); b[k + 3] = max(b[k + 3], float(C[:, k].max()))
        return Frag(off, len(data), pd, sdr, sh.nsol, sh.nsurf, sh.nfaces, sh.vol, sh.nopen, 'inst:%s' % (sh.key,), sh.key,
                    far=far_offset(C.min(0), C.max(0)))

    def read(self, fr):
        with open(self.path, 'rb') as fh:
            fh.seek(fr.off)
            return fh.read(fr.size)


# ====================================================================================================== IFC geometry

SKIP_TYPES = ("IfcOpeningElement", "IfcSpace", "IfcGrid", "IfcAnnotation", "IfcVirtualElement", "IfcOpeningStandardCase")
CURVED_TYPES = ('IfcCircle', 'IfcEllipse', 'IfcBSplineCurve', 'IfcBSplineCurveWithKnots', 'IfcRationalBSplineCurveWithKnots',
                'IfcBSplineSurface', 'IfcBSplineSurfaceWithKnots', 'IfcRationalBSplineSurfaceWithKnots', 'IfcCylindricalSurface',
                'IfcSphericalSurface', 'IfcToroidalSurface', 'IfcSurfaceOfRevolution', 'IfcSweptDiskSolid',
                'IfcSweptDiskSolidPolygonal', 'IfcRevolvedAreaSolid', 'IfcRevolvedAreaSolidTapered', 'IfcRightCircularCylinder',
                'IfcRightCircularCone', 'IfcSphere', 'IfcCircleProfileDef', 'IfcCircleHollowProfileDef', 'IfcEllipseProfileDef',
                'IfcClothoid', 'IfcSpiral', 'IfcCosineSpiral', 'IfcSineSpiral', 'IfcSecondOrderPolynomialSpiral',
                'IfcSeventhOrderPolynomialSpiral', 'IfcIndexedPolyCurve', 'IfcCompositeCurve', 'IfcAdvancedBrep',
                'IfcAdvancedBrepWithVoids', 'IfcAdvancedFace', 'IfcFixedReferenceSweptAreaSolid', 'IfcSurfaceCurveSweptAreaSolid',
                'IfcDirectrixCurveSweptAreaSolid', 'IfcSectionedSolidHorizontal', 'IfcSectionedSpine')
RADIUS_ATTRS = ('FilletRadius', 'EdgeRadius', 'InnerFilletRadius', 'OuterFilletRadius', 'WebEdgeRadius', 'FlangeEdgeRadius',
                'InternalFilletRadius', 'CentreLineRadius', 'LegSlope', 'WebSlope', 'FlangeSlope', 'FlangeEdgeRadius')
SURFACE_ITEM_TYPES = ('IfcShellBasedSurfaceModel', 'IfcFaceBasedSurfaceModel', 'IfcSurface', 'IfcGeometricCurveSet',
                      'IfcAnnotationFillArea', 'IfcFaceSurface', 'IfcTessellatedFaceSet')


def body_items(pr):
    """items of the product's body representation: Body > Facetation > unnamed (one representation, not their sum)"""
    rep = getattr(pr, "Representation", None)
    if rep is None:
        return None, None
    by = {}
    for r in rep.Representations or []:
        rid = r.RepresentationIdentifier
        if rid in (None, "Body", "Facetation"):
            by.setdefault(rid, []).append(r)
    for rid in ("Body", "Facetation", None):
        if rid in by:
            items = [it for r in by[rid] for it in (r.Items or [])]
            if items:
                return items, rid
    return None, None


_curved_cache = {}
_curved_names = None
FACETED_ITEM_TYPES = {'IfcFacetedBrep', 'IfcFacetedBrepWithVoids', 'IfcShellBasedSurfaceModel', 'IfcFaceBasedSurfaceModel',
                      'IfcPolygonalFaceSet', 'IfcTriangulatedFaceSet', 'IfcTriangulatedIrregularNetwork'}


def _curved_type_names(f):
    """CURVED_TYPES and all their subtypes in the file's schema (upper-case names)"""
    global _curved_names
    if _curved_names is not None:
        return _curved_names
    names = set(t.upper() for t in CURVED_TYPES)
    try:
        import ifcopenshell.ifcopenshell_wrapper as W
        sch = W.schema_by_name(f.schema)
        def sub(d):
            for c in d.subtypes():
                names.add(c.name().upper()); sub(c)
        for t in CURVED_TYPES:
            try:
                sub(sch.declaration_by_name(t))
            except Exception:
                pass
    except Exception:
        pass
    _curved_names = names
    return names


def item_curved(f, it):
    """True when the item's geometry holds curved surfaces / curves (its kernel facets approximate them)"""
    t = it.is_a()
    if t in FACETED_ITEM_TYPES:
        return False
    k = it.id()
    r = _curved_cache.get(k)
    if r is not None:
        return r
    if t == 'IfcMappedItem':
        rep = it.MappingSource.MappedRepresentation
        r = _curved_cache.get(('rep', rep.id()))
        if r is None:
            r = any(item_curved(f, si) for si in rep.Items)
            _curved_cache[('rep', rep.id())] = r
        _curved_cache[k] = r
        return r
    names = _curved_type_names(f)
    r = False
    try:
        for e in f.traverse(it):
            tn = e.is_a().upper()
            if tn in names:
                r = True
                break
            if tn.endswith('PROFILEDEF'):
                for a in RADIUS_ATTRS:
                    v = getattr(e, a, None)
                    if isinstance(v, (int, float)) and v > 0:
                        r = True
                        break
                if r:
                    break
            elif tn == 'IFCTRIMMEDCURVE':
                bc = e.BasisCurve
                if bc is not None and not bc.is_a('IfcLine'):
                    r = True
                    break
    except Exception:
        r = False
    _curved_cache[k] = r
    return r


class Piece:
    __slots__ = ('V', 'faces', 'role', 'group')

    def __init__(self, V, faces, role, group):
        self.V = V; self.faces = faces; self.role = role; self.group = group


def m44(m):
    return np.array([[float(x) for x in row] for row in m], dtype=np.float64)


class Transcoder:
    """faceted IFC items -> Pieces (exact copy of the source facets, transformed to mm)"""

    def __init__(self, f, sc):
        self.f = f
        self.sc = sc            # mm per file unit
        self.group = 0
        import ifcopenshell.util.placement as up
        self.up = up

    def shell_faces(self, shell, M):
        raw = []
        idx = {}
        faces = []
        for fc in shell.CfsFaces:
            bounds = fc.Bounds
            loops = []
            outer_k = None
            for k, b in enumerate(bounds):
                lp = b.Bound
                if not lp.is_a("IfcPolyLoop"):
                    return None
                ids = []
                for p in lp.Polygon:
                    pid = p.id()
                    j = idx.get(pid)
                    if j is None:
                        c = p.Coordinates
                        j = len(raw)
                        raw.append((c[0], c[1], c[2] if len(c) > 2 else 0.0))
                        idx[pid] = j
                    ids.append(j)
                if getattr(b, "Orientation", True) is False:
                    ids = ids[::-1]
                if b.is_a("IfcFaceOuterBound") and outer_k is None:
                    outer_k = len(loops)
                loops.append(ids)
            if not loops:
                continue
            if outer_k is not None and outer_k != 0:
                loops.insert(0, loops.pop(outer_k))
            elif outer_k is None and len(loops) > 1:
                loops.append(None)   # marker: choose the outer loop by area after transform
            faces.append(loops)
        if not raw:
            return np.zeros((0, 3)), []
        V = self.xf(np.array(raw, np.float64), M)
        for fl in faces:
            if fl and fl[-1] is None:
                fl.pop()
                areas = [np.linalg.norm(newell(V[lp])) if len(lp) >= 3 else 0 for lp in fl]
                k = int(np.argmax(areas))
                fl.insert(0, fl.pop(k))
        return V, faces

    def xf(self, P, M):
        return (P @ M[:3, :3].T + M[:3, 3]) * self.sc

    def item(self, it, M, out, depth=0):
        t = it.is_a()
        if t in ("IfcFacetedBrep", "IfcFacetedBrepWithVoids"):
            r = self.shell_faces(it.Outer, M)
            if r is None:
                return False
            self.group += 1
            g = self.group
            out.append(Piece(r[0], r[1], 'solid', g))
            if t == "IfcFacetedBrepWithVoids":
                for v in it.Voids or []:
                    rv = self.shell_faces(v, M)
                    if rv is None:
                        return False
                    out.append(Piece(rv[0], rv[1], 'void', g))
            return True
        if t == "IfcShellBasedSurfaceModel":
            for sh in it.SbsmBoundary:
                r = self.shell_faces(sh, M)
                if r is None:
                    return False
                self.group += 1
                out.append(Piece(r[0], r[1], 'closed_surface' if sh.is_a('IfcClosedShell') else 'surface', self.group))
            return True
        if t == "IfcFaceBasedSurfaceModel":
            for sh in it.FbsmFaces:
                r = self.shell_faces(sh, M)
                if r is None:
                    return False
                self.group += 1
                out.append(Piece(r[0], r[1], 'surface', self.group))
            return True
        if t in ("IfcPolygonalFaceSet", "IfcTriangulatedFaceSet"):
            coords = it.Coordinates.CoordList
            P = np.array([(c[0], c[1], c[2] if len(c) > 2 else 0.0) for c in coords], np.float64)
            pn = getattr(it, 'PnIndex', None)
            if pn:
                pmap = [int(i) - 1 for i in pn]
                remap = lambda i: pmap[int(i) - 1]
            else:
                remap = lambda i: int(i) - 1
            faces = []
            if t == "IfcTriangulatedFaceSet":
                for tri in it.CoordIndex:
                    faces.append([[remap(i) for i in tri]])
            else:
                for fa in it.Faces:
                    loops = [[remap(i) for i in fa.CoordIndex]]
                    for inner in (getattr(fa, 'InnerCoordIndices', None) or []):
                        loops.append([remap(i) for i in inner])
                    faces.append(loops)
            V = self.xf(P, M)
            closed = getattr(it, 'Closed', None)
            self.group += 1
            out.append(Piece(V, faces, 'surface' if closed is False else 'solid', self.group))
            return True
        if t == "IfcMappedItem":
            if depth > 8:
                return False
            try:
                om = m44(self.up.get_mappeditem_transformation(it))
            except Exception:
                return False
            M2 = M @ om
            for si in it.MappingSource.MappedRepresentation.Items:
                if not self.item(si, M2, out, depth + 1):
                    return False
            return True
        return False

    def items_local(self, items):
        """faceted items in their own (representation map) frame, mm -> Pieces or None"""
        out = []
        I = np.eye(4)
        for it in items:
            if not self.item(it, I, out):
                return None
        return out

    def product(self, pr, items):
        """-> list of Pieces, or None if any item is not faceted / the placement cannot be evaluated"""
        try:
            M = m44(self.up.get_local_placement(pr.ObjectPlacement)) if pr.ObjectPlacement is not None else np.eye(4)
        except Exception:
            return None
        out = []
        for it in items:
            if not self.item(it, M, out):
                return None
        return out


def repair_null_curve_segments(f):
    """IfcCompositeCurveSegment without a ParentCurve (Tekla 2017i writes `#0`, a reference to no entity, read as $; the
    attribute is mandatory) makes the kernel reject the whole profile, and the product was lost ('SHEAR TAB' PL3/4"X12":
    the empty segment sits next to a closed polyline segment that alone bounds the plate). Such a segment carries no
    geometry; it is dropped from the in-memory curve when at least one real segment remains (the source file is not
    touched). -> number of curves changed"""
    n = 0
    for cc in f.by_type('IfcCompositeCurve'):
        try:
            segs = cc.Segments or ()
            keep = [sg for sg in segs if getattr(sg, 'ParentCurve', None) is not None]
            if keep and len(keep) < len(segs):
                cc.Segments = keep
                n += 1
        except Exception:
            continue
    return n


def kernel_settings(ttype='poly'):
    import ifcopenshell.geom
    import ifcopenshell.ifcopenshell_wrapper as W
    s = ifcopenshell.geom.settings()
    applied = {}
    dfl = float(os.environ.get("DEFLECTION", "0") or 0)
    ang = float(os.environ.get("ANG_DEFLECTION", "0") or 0)
    if dfl > 0:
        try:
            s.set("mesher-linear-deflection", dfl); applied["mesher-linear-deflection"] = dfl
        except Exception:
            applied["mesher-linear-deflection"] = "err"
    if ang > 0:
        try:
            s.set("mesher-angular-deflection", ang); applied["mesher-angular-deflection"] = ang
        except Exception:
            applied["mesher-angular-deflection"] = "err"
    for key, val in (("use-world-coords", True), ("weld-vertices", True)):
        try:
            s.set(key, val)
        except Exception:
            try:
                s.set(getattr(s, key.upper().replace("-", "_")), val)
            except Exception:
                pass
    tt = None
    try:
        tt = W.POLYHEDRON_WITH_HOLES if ttype == 'poly' else W.TRIANGLE_MESH
        s.set("triangulation-type", tt)
    except Exception:
        tt = None
    return s, applied, (ttype if tt is not None else 'tri')


def kernel_geometry(g, mode):
    """ifcopenshell triangulation -> (V mm, faces, item ids per face)"""
    V = np.array(g.verts, np.float64).reshape(-1, 3) * 1000.0
    if mode == 'poly':
        pf = g.polyhedral_faces_with_holes
        if pf:
            faces = [[list(lp) for lp in fc] for fc in pf]
            iids = list(g.item_ids) if len(g.item_ids) == len(faces) else None
            return V, faces, iids
    F = np.array(g.faces, np.int64).reshape(-1, 3)
    faces = [[list(t)] for t in F.tolist()]
    iids = list(g.item_ids) if len(g.item_ids) == len(faces) else None
    return V, faces, iids


# fork-based isolation only on Linux (the fleet): on macOS a forked child of a process that has loaded ifcopenshell /
# OpenCASCADE and runs a thread can die at once, which would exclude healthy products
CAN_FORK = hasattr(os, 'fork') and sys.platform.startswith('linux')


def create_shape_isolated(mode, product, timeout=None, extra_gb=None):
    """ifcopenshell create_shape in a forked child with an address-space cap and a timeout: a kernel run-away on one
    product (seen: 1.4 MB SDS/2 file, one faceted bolt, OCC grew to 124 GB) costs that product, not the conversion.
    -> (mode, (V, faces, iids)) or None"""
    import pickle, select
    timeout = timeout or int(os.environ.get('V6_KERNEL_RETRY_TIMEOUT', '180'))
    extra_gb = extra_gb or int(os.environ.get('V6_KERNEL_RETRY_GB', '12'))
    if not CAN_FORK:
        try:
            s2, _, m2 = kernel_settings(mode)
            import ifcopenshell.geom
            return m2, kernel_geometry(ifcopenshell.geom.create_shape(s2, product).geometry, m2)
        except Exception:
            return None
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:
        data = b''
        try:
            os.close(r)
            try:
                vm = int(open('/proc/self/statm').read().split()[0]) * os.sysconf('SC_PAGE_SIZE')
                lim = vm + (extra_gb << 30)
                resource.setrlimit(resource.RLIMIT_AS, (lim, lim))
            except Exception:
                pass
            import ifcopenshell.geom
            s2, _, m2 = kernel_settings(mode)
            g = kernel_geometry(ifcopenshell.geom.create_shape(s2, product).geometry, m2)
            data = pickle.dumps((m2, g), protocol=4)
        except BaseException:
            data = b''
        try:
            mv = memoryview(data)
            while len(mv):
                k = os.write(w, mv)
                mv = mv[k:]
            os.close(w)
        finally:
            os._exit(0)
    os.close(w)
    chunks = []
    t0 = time.time()
    ok = True
    try:
        while True:
            left = timeout - (time.time() - t0)
            if left <= 0:
                ok = False
                break
            rl, _, _ = select.select([r], [], [], min(left, 5.0))
            if rl:
                b = os.read(r, 1 << 20)
                if not b:
                    break
                chunks.append(b)
    finally:
        if not ok:
            try:
                os.kill(pid, 9)
            except Exception:
                pass
        try:
            os.waitpid(pid, 0)
        except Exception:
            pass
        os.close(r)
    if not ok:
        log('kernel run-away on #%s (%s): killed after %ds' % (product.id(), mode, timeout))
        return 'killed'
    if not chunks:
        return None
    try:
        return pickle.loads(b''.join(chunks))
    except Exception:
        return None


def kernel_run_isolated(f, prods, threads, mode, stats_key, stats, on_shape, extra_gb=None, stall=None):
    """kernel_run in a forked child with an address-space cap and a timeout (fallback regeneration: the products that
    get here are the odd ones, and an ifcopenshell run-away must not take the converter with it). Shapes stream back
    through a pipe as they come; a killed child costs only the products it had not finished."""
    import pickle, select, struct
    if not CAN_FORK or os.environ.get('V6_NO_ISOLATION') == '1':
        return kernel_run(f, prods, threads, mode, stats_key, stats, on_shape)
    extra_gb = extra_gb or int(os.environ.get('V6_KERNEL_RETRY_GB', '12'))
    timeout = int(os.environ.get('V6_KERNEL_BATCH_TIMEOUT', '0') or 0) or (300 + 20 * len(prods))
    stall = stall or int(os.environ.get('V6_KERNEL_STALL', '900'))       # no shape for this long -> the child is stuck
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:
        try:
            os.close(r)
            try:
                vm = int(open('/proc/self/statm').read().split()[0]) * os.sysconf('SC_PAGE_SIZE')
                lim = vm + (extra_gb << 30)
                resource.setrlimit(resource.RLIMIT_AS, (lim, lim))
            except Exception:
                pass

            def send(eid, V, faces, iids):
                b = pickle.dumps((eid, V, faces, iids), protocol=4)
                mv = memoryview(struct.pack('<Q', len(b)) + b)
                while len(mv):
                    k = os.write(w, mv)
                    mv = mv[k:]
            st2 = {}
            kernel_run(f, prods, threads, mode, stats_key, st2, send)
            b = pickle.dumps(('__stats__', st2), protocol=4)
            mv = memoryview(struct.pack('<Q', len(b)) + b)
            while len(mv):
                k = os.write(w, mv)
                mv = mv[k:]
            os.close(w)
        except BaseException:
            pass
        finally:
            os._exit(0)
    os.close(w)
    buf = b''
    t0 = time.time()
    t_last = t0
    got = 0
    killed = False
    try:
        while True:
            now_ = time.time()
            left = timeout - (now_ - t0)
            if left <= 0 or now_ - t_last > stall:
                killed = True
                break
            rl, _, _ = select.select([r], [], [], min(left, 5.0))
            if not rl:
                continue
            t_last = time.time()
            b = os.read(r, 1 << 22)
            if not b:
                break
            buf += b
            while len(buf) >= 8:
                n = struct.unpack('<Q', buf[:8])[0]
                if len(buf) < 8 + n:
                    break
                rec = pickle.loads(buf[8:8 + n])
                buf = buf[8 + n:]
                if rec[0] == '__stats__':
                    stats.update(rec[1])
                    continue
                got += 1
                try:
                    on_shape(*rec)
                except Exception as e:
                    log('kernel geometry %s failed: %s' % (rec[0], e))
    finally:
        if killed:
            try:
                os.kill(pid, 9)
            except Exception:
                pass
        try:
            _, status = os.waitpid(pid, 0)
        except Exception:
            status = 0
        os.close(r)
    died = bool(killed or status)
    if died and got < len(prods):
        log('isolated kernel batch %s: %d/%d shapes, child %s' % (stats_key, got, len(prods), 'timed out / stalled' if killed else 'died (%s)' % status))
        stats[stats_key + '_isolation'] = {'shapes': got, 'products': len(prods), 'killed': killed, 'status': status}
    return {'died': died, 'killed': killed, 'status': status, 'got': got}


def kernel_pass_isolated(f, prods, threads, mode, stats_key, stats, on_shape):
    """the main kernel pass in memory-capped children, one product group at a time (ifcopenshell 0.9.0 can run away on
    single products: 233 GB / 173 GB / 150 GB seen). A group whose child dies (address-space cap, crash, stall) keeps
    the shapes it delivered; the rest is bisected down to the single product, which is left out and listed
    (kernel_memory_exceeded) - the conversion goes on. Products the kernel simply does not produce stay 'missing'.
    -> list of excluded products"""
    if not CAN_FORK or os.environ.get('V6_KERNEL_ISOLATE', '1') != '1' or not prods:
        kernel_run(f, prods, threads, mode, stats_key, stats, on_shape)
        return []
    gsize = int(os.environ.get('V6_KERNEL_GROUP', '500'))
    cap_gb = int(os.environ.get('V6_KERNEL_GROUP_GB', '16'))
    queue = [prods[i:i + gsize] for i in range(0, len(prods), gsize)]
    excluded = []
    st = {'groups': 0, 'children_died': 0, 'bisections': 0}
    t0 = time.time()
    while queue:
        g = queue.pop(0)
        got = set()

        def cb(eid, V, faces, iids):
            got.add(eid)
            on_shape(eid, V, faces, iids)
        st['groups'] += 1
        sub = {}
        res = kernel_run_isolated(f, g, threads, mode, stats_key, sub, cb, extra_gb=cap_gb)
        for k_, v_ in sub.items():
            if isinstance(v_, dict) and isinstance(stats.get(k_), dict) and k_ == stats_key:
                for kk in ('products', 'shapes', 'retried_single', 'missing', 'runaway_killed'):
                    stats[k_][kk] = stats[k_].get(kk, 0) + (v_.get(kk) or 0)
            elif k_ == stats_key:
                stats[k_] = dict(v_)
            else:
                stats.setdefault(k_, v_)
        if not res['died']:
            continue
        st['children_died'] += 1
        rest = [p for p in g if p.id() not in got]
        if not rest:
            continue
        if len(rest) == 1:
            excluded.append(rest[0])
            log('kernel product #%s excluded: its child died (%s)' % (rest[0].id(), 'cap/stall' if res['killed'] else res['status']))
            continue
        st['bisections'] += 1
        h = len(rest) // 2
        queue[0:0] = [rest[:h], rest[h:]]
        if st['groups'] % 20 == 0:
            log('[kernel isolated] %d groups, %d excluded, %.0fs' % (st['groups'], len(excluded), time.time() - t0))
    st['excluded'] = len(excluded)
    st['sec'] = round(time.time() - t0, 1)
    stats[stats_key + '_groups'] = st
    return excluded


def kernel_run(f, prods, threads, mode, stats_key, stats, on_shape=None):
    """kernel pass; products with openings are meshed as triangles (see below), the rest in the requested mode"""
    if mode == 'poly' and os.environ.get('V6_OPENINGS_POLY') != '1':
        # ifcopenshell 0.9.0's polyhedral output (POLYHEDRON_WITH_HOLES) of a boolean result can run away: data-3
        # Seaport L4 (SDS/2) angle a3717 (12-face faceted brep minus two 18-face faceted hole prisms) grows past 12 GB
        # in one create_shape and took the converter to 173 GB; its triangle mesh takes 0.14 s (valid solid). Opening
        # products are 1-7 s each in polyhedral mode, 0.1-0.2 s as triangles; coplanar triangles are merged back into
        # the same planar polygons with holes by Repair.merge_coplanar (exact). (Finding: verification-residue fixer.)
        op = [p for p in prods if getattr(p, 'HasOpenings', None)]
        if op:
            rest = [p for p in prods if not getattr(p, 'HasOpenings', None)]
            done, m = _kernel_run(f, rest, threads, 'poly', stats_key, stats, on_shape) if rest else (set(), 'poly')
            d2, _ = _kernel_run(f, op, threads, 'tri', stats_key + '_openings_tri', stats, on_shape)
            return done | d2, m
    return _kernel_run(f, prods, threads, mode, stats_key, stats, on_shape)


def _kernel_run(f, prods, threads, mode, stats_key, stats, on_shape=None):
    """iterate the kernel over products; every shape is handed to on_shape(eid, V, faces, iids) as it comes (streaming,
    bounded memory). Products the iterator skips are retried one by one with create_shape (polyhedral, then
    triangle mesh). Returns (set of product ids done, mode)."""
    import ifcopenshell.geom
    s, applied, m = kernel_settings(mode)
    stats.setdefault('deflection_settings', applied)
    done = set()
    if not prods:
        return done, m
    t0 = time.time()
    it = None
    try:
        it = ifcopenshell.geom.iterator(s, f, max(1, threads), include=prods)
        ok = it.initialize()
    except Exception as e:
        log('kernel iterator init failed: %s' % e)
        ok = False
    n = 0
    if ok:
        while True:
            sh = it.get()
            try:
                g = kernel_geometry(sh.geometry, m)
                done.add(sh.id)
                if on_shape is not None:
                    on_shape(sh.id, *g)
            except Exception as e:
                log('kernel geometry %s failed: %s' % (getattr(sh, 'id', '?'), e))
            n += 1
            if n % 5000 == 0:
                log('[kernel %s] %d/%d %.0fs rss=%dMB' % (mode, n, len(prods), time.time() - t0, rss()))
            if not it.next():
                break
        del it
    miss = [p for p in prods if p.id() not in done]
    retried = 0
    killed = 0
    for p in miss:
        for mm in ((mode, 'tri') if mode == 'poly' else (mode,)):
            res = create_shape_isolated(mm, p)
            if res == 'killed':
                killed += 1
                break                       # a run-away product is not tried again in another mode
            if res is None:
                continue
            m2, g = res
            done.add(p.id())
            retried += 1
            if on_shape is not None:
                try:
                    on_shape(p.id(), *g)
                except Exception as e:
                    log('kernel geometry %s failed: %s' % (p.id(), e))
            break
    stats[stats_key] = {'products': len(prods), 'shapes': len(done), 'retried_single': retried,
                        'missing': len(prods) - len(done), 'runaway_killed': killed, 'sec': round(time.time() - t0, 2)}
    return done, m


# ====================================================================================================== part building

def build_part(pieces, repair, tri=False):
    """Pieces of one product -> (X, solids, surfaces, tags). tri: every face triangulated (fallback L1)."""
    tags = set()
    if not pieces:
        return None
    shared_v = all(p.V is pieces[0].V for p in pieces)
    Vs = [p.V for p in pieces if len(p.V)] if not shared_v else [pieces[0].V]
    if not Vs or not len(Vs[0]):
        return None
    V = np.concatenate(Vs) if len(Vs) > 1 else Vs[0]
    w = repair.weld(V)
    if w is None:
        return 'corrupt'
    Q, inv = w
    X = Q.astype(np.float64) / repair.qs
    solids, surfaces = [], []
    off = 0
    group_solids = collections.defaultdict(list)
    voids = []
    for p in pieces:
        n = len(p.V) if not shared_v else 0
        faces = [[[i + off for i in lp] for lp in fc] for fc in p.faces] if off else p.faces
        off += n
        fs = repair.clean_faces(faces, inv, X)
        if tri:
            fs = triangulate_all(fs, X, repair)
        fs = repair.dedup_faces(fs)
        if not fs:
            continue
        tw = repair.last_twins
        dbl = False
        if p.role in ('solid', 'closed_surface') and tw and 2 * len(tw) >= 0.5 * len(fs):
            dbl = True
            # double-sided mesh (each face also given reversed, SDS/2 library parts): one copy of each pair is kept
            # (same surface); the rest is processed as usual - closed components become solids, open ones surfaces
            drop = set(j for i, j in tw)
            fs = [fc for k, fc in enumerate(fs) if k not in drop]
            repair.stats['double_sided_pieces_single_sided'] += 1
            tags.add('double-sided')
        repair.last_sew_move = 0.0
        if CO_UNION and p.role in ('solid', 'closed_surface') and not dbl and len(fs) <= 5000:
            # overlapping coplanar faces resolved before the seam sewing can move their vertices (6.1.8)
            cu = repair.union_presew(fs, X)
            if cu is not None:
                fs, X = cu
                tags.add('coplanar_overlap_merged')
        if p.role in ('solid', 'closed_surface', 'void'):
            fs2, nm = repair.sew(fs, X, repair.tol_sew)
            if nm:
                fs = repair.dedup_faces(fs2)
                tags.add('sewn')
        if DEGEN_FIX:
            fs = repair.drop_degenerate(fs, X)
        fs, nt = repair.tjunctions(fs, X)
        if nt:
            tags.add('tjunction')
            if DEGEN_FIX:
                fs = repair.drop_degenerate(fs, X)
        shs = repair.shells(fs, X, p.role)
        if repair.last_sew_move:
            for sh_ in shs:
                sh_.sew = repair.last_sew_move
        if p.role in ('solid', 'closed_surface'):
            # double-sided source: the winding of the kept copies says nothing, so no component is taken as a void
            sol, opn = organise_solids(shs, X, repair, allow_voids=not dbl)
            if not tri and repair.merge:
                for s_ in sol:
                    for sh_ in [s_] + s_.voids:
                        if sh_.closed and len(sh_.faces) >= 4 and sum(1 for f_ in sh_.faces if len(f_) == 1 and len(f_[0]) == 3) >= 0.3 * len(sh_.faces):
                            n_ = len(sh_.faces)
                            sh_.faces = repair.merge_coplanar(sh_.faces, X)
                            if len(sh_.faces) != n_:
                                tags.add('merged')      # internal (not a part tag): L0c retries such parts unmerged
            for s in sol:
                tags |= s.tags
                if s.voids:
                    tags.add('void')
            if len(shs) > 1:
                tags.add('components')
            solids.extend(sol)
            group_solids[p.group].extend(sol)
            for s in opn:
                fl_ = bool(DEGEN_FIX and s.closed and flat_shell(s, X, repair.tol_planar))
                if fl_:
                    # a closed shell with every vertex in one plane encloses nothing (a patch covered from both sides)
                    repair.stats['flat_closed_shells_as_surface'] += 1
                if dbl or fl_ or repair.clearly_open(s.faces, X):
                    # (a double-sided source whose single side is open is a zero-thickness sheet: no solid to try)
                    # loose faces in the source (most edges free, e.g. grating bars given as separate quads):
                    # written as a surface, not offered as a solid
                    surfaces.append(s)
                    # loose source faces next to a valid solid of the same piece are kept as faces (info tag
                    # stray-faces); a piece without any solid is an open surface (tag open-surface)
                    t_ = 'stray-faces' if sol else 'open-surface'
                    s.tags.add(t_); tags.add(t_)
                    repair.stats['open_shells_as_surface'] += 1
                else:
                    # a solid source whose shell is open. Measured (6.1.8): when every free edge lies within GAP_CLOSE_MM
                    # (0.01 mm) of another free edge, those vertices are merged (no face added) and the shell is written
                    # as an exact closed solid, no tag (sidecar gap_max_mm + closed_within_mm). Otherwise it is offered
                    # to the reader as a closed shell (the verifier decides), tag open_in_source, sidecar gap_max_mm.
                    if CO_UNION:
                        # overlapping coplanar faces -> their signed union (exact, info tag coplanar_overlap_merged)
                        cu = repair.coplanar_union(s.faces, X)
                        if cu is not None:
                            fsu, X2, ng_ = cu
                            fsu, _ = repair.tjunctions(fsu, X2)
                            fsu = repair.drop_degenerate(fsu, X2)
                            shu = repair.shells(fsu, X2, 'solid')
                            if len(shu) == 1 and shu[0].closed and abs(shu[0].vol) > 0 and not flat_shell(shu[0], X2, repair.tol_planar):
                                X = X2
                                s3 = shu[0]
                                if s3.vol < 0:
                                    s3.faces = [[lp[::-1] for lp in f] for f in s3.faces]; s3.vol = -s3.vol
                                s3.sew = s.sew
                                s3.tags.add('coplanar_overlap_merged'); tags.add('coplanar_overlap_merged')
                                repair.stats['coplanar_overlap_shells_closed'] += 1
                                solids.append(s3)
                                group_solids[p.group].append(s3)
                                continue
                            repair.stats['coplanar_union_not_closed'] += 1
                    gi = repair.gap_stats(s.faces, X)
                    s2 = None
                    if gi is not None and gi.get('gap_max_mm') is not None and gi['gap_max_mm'] <= GAP_CLOSE_MM:
                        s2 = repair.close_within(s.faces, X, GAP_CLOSE_MM)
                    if s2 is not None:
                        if s2.vol < 0:
                            s2.faces = [[lp[::-1] for lp in f] for f in s2.faces]; s2.vol = -s2.vol
                        s2.gap = dict(gi, closed_within_mm=GAP_CLOSE_MM)
                        repair.stats['open_shells_closed_within_tol'] += 1
                        solids.append(s2)
                        group_solids[p.group].append(s2)
                        continue
                    s.gap = gi
                    repair.stats['open_in_source_shells'] += 1
                    s.tags.add('open_in_source')
                    tags.add('open_in_source')
                    if s.vol < 0:
                        s.faces = [[lp[::-1] for lp in f] for f in s.faces]; s.vol = -s.vol
                    solids.append(s)
        elif p.role == 'void':
            voids.append((p.group, shs))
        else:
            surfaces.extend(shs)
    if not solids and not surfaces and not voids:
        # every face fell out in repair (degenerate source): keep the cleaned source faces as a surface model
        raw = []
        off = 0
        for p in pieces:
            n = len(p.V) if not shared_v else 0
            faces = [[[i + off for i in lp] for lp in fc] for fc in p.faces] if off else p.faces
            off += n
            raw += [fc for fc in repair.clean_faces(faces, inv, X)]
        if raw:
            surfaces = [Shell(raw, False, 0.0, 'surface')]
            tags.add('open-surface')
            repair.stats['parts_repair_emptied_kept_as_surface'] += 1
    for g, shs in voids:
        hosts = group_solids.get(g) or []
        for v in shs:
            if not v.closed or not hosts:
                surfaces.append(v)
                continue
            host = max(hosts, key=lambda s: s.vol)
            if v.vol > 0:
                v.faces = [[lp[::-1] for lp in f] for f in v.faces]; v.vol = -v.vol
            host.voids.append(v)
            tags.add('void')
            repair.stats['explicit_voids'] += 1
    if solids and 'open-surface' in tags:
        # the part is a valid solid; its extra open source faces are kept as faces (info), not an open-surface part
        tags.discard('open-surface'); tags.add('stray-faces')
    return X, solids, surfaces, tags


def triangulate_all(faces, X, repair):
    out = []
    for f in faces:
        if len(f) == 1 and len(f[0]) == 3:
            out.append(f)
            continue
        n = newell(X[f[0]])
        tris = earcut(f, X, n) if np.linalg.norm(n) > 0 else None
        if tris is None:
            repair.stats['faces_untriangulable_kept'] += 1
            out.append(f)
            continue
        out.extend([[list(t)] for t in tris])
    return out


# ====================================================================================================== verification

VERIFY_CODE_MARK = '--_verify'


def verify_worker(listfile, outfile):
    """runs in a python with pythonocc: for each chunk STEP file, per root exactly the grader's step_check checks"""
    from OCC.Core.STEPControl import STEPControl_Reader
    from OCC.Core.IFSelect import IFSelect_RetDone
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopAbs import TopAbs_SOLID, TopAbs_FACE, TopAbs_SHELL
    from OCC.Core.BRepCheck import BRepCheck_Analyzer
    from OCC.Core.GProp import GProp_GProps
    from OCC.Core.Bnd import Bnd_Box
    try:
        from OCC.Core.BRepGProp import brepgprop
        vol_props = brepgprop.VolumeProperties
    except ImportError:
        from OCC.Core.BRepGProp import brepgprop_VolumeProperties as vol_props
    try:
        from OCC.Core.BRepBndLib import brepbndlib
        bnd_add = brepbndlib.Add
    except ImportError:
        from OCC.Core.BRepBndLib import brepbndlib_Add as bnd_add
    files = json.load(open(listfile))
    with open(outfile, 'w') as out:
        for fn in files:
            r = STEPControl_Reader()
            st = r.ReadFile(fn)
            if st != IFSelect_RetDone:
                out.write(json.dumps({'file': fn, 'read_fail': int(st)}) + '\n')
                continue
            model = r.WS().Model()
            nroots = r.NbRootsForTransfer()
            for i in range(1, nroots + 1):
                rec = {'file': fn}
                try:
                    ent = r.RootForTransfer(i)
                    rec['eid'] = int(model.StringLabel(ent).ToCString().lstrip('#'))
                    ok = r.TransferRoot(i)
                    if not ok:
                        rec['empty'] = True
                        out.write(json.dumps(rec) + '\n')
                        continue
                    sh = r.Shape(r.NbShapes())
                except Exception as e:
                    rec['error'] = str(e)[:100]
                    out.write(json.dumps(rec) + '\n')
                    continue
                if sh is None or sh.IsNull():
                    rec['empty'] = True
                    out.write(json.dumps(rec) + '\n')
                    continue
                ex = TopExp_Explorer(sh, TopAbs_SOLID)
                sols = []
                while ex.More():
                    sols.append(ex.Current()); ex.Next()
                nf = 0
                exf = TopExp_Explorer(sh, TopAbs_FACE)
                while exf.More():
                    nf += 1; exf.Next()
                ns = 0
                exs = TopExp_Explorer(sh, TopAbs_SHELL)
                while exs.More():
                    ns += 1; exs.Next()
                rec.update(solids=len(sols), faces=nf, shells=ns)
                b = Bnd_Box()
                try:
                    bnd_add(sh, b, False)
                    if not b.IsVoid():
                        bb = b.Get()
                        rec['finite'] = all(math.isfinite(v) and abs(v) < 1e10 for v in bb)
                except Exception:
                    pass
                vals, vols = [], []
                for s in sols:
                    try:
                        v_ = bool(BRepCheck_Analyzer(s).IsValid())
                    except Exception:
                        v_ = False
                    g = GProp_GProps()
                    try:
                        vol_props(s, g); vv = g.Mass()
                    except Exception:
                        vv = float('nan')
                    vals.append(v_); vols.append(vv if math.isfinite(vv) else None)
                rec['valid'] = vals; rec['vols'] = vols
                out.write(json.dumps(rec) + '\n')
    return 0


_occ_py = [None]


def occ_python():
    if _occ_py[0] is not None:
        return _occ_py[0] or None
    cands = [os.environ.get('V6_OCC_PYTHON'), sys.executable]
    exe = os.path.realpath(sys.executable)
    d = os.path.dirname(os.path.dirname(exe))
    cands += [os.path.join(os.path.dirname(d), 'env', 'bin', 'python'), os.path.join(d, '..', 'env', 'bin', 'python'),
              '/opt/conv/env/bin/python']
    for c in cands:
        if not c or not os.path.exists(c):
            continue
        try:
            r = subprocess.run([c, '-c', 'import OCC.Core.STEPControl, OCC.Core.BRepCheck'], capture_output=True, timeout=120)
            if r.returncode == 0:
                _occ_py[0] = c
                return c
        except Exception:
            continue
    _occ_py[0] = ''
    return None


class Verifier:
    def __init__(self, spool, tmpdir, procs, header_entities, shared=None):
        self.shared = shared if shared is not None else {}
        self.spool = spool
        self.tmpdir = tmpdir
        self.procs = max(1, procs)
        self.gents = header_entities
        self.py = occ_python()
        self.rounds = 0
        self.sec = 0.0

    def available(self):
        return self.py is not None

    def run(self, frags):
        """frags: list of (key, Frag) -> dict key -> result dict. Every chunk file is read in its own process (OCC
        8.0.1 can segfault reading a second large STEP in the same process); a chunk whose reader crashes is bisected
        down to the part that crashes it."""
        if not frags:
            return {}
        t0 = time.time()
        self.rounds += 1
        self.spool.fh.flush()
        rd = os.path.join(self.tmpdir, 'v%d' % self.rounds)
        os.makedirs(rd, exist_ok=True)
        self.hdr = ("ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION((''),'2;1');\nFILE_NAME('v','2000-01-01T00:00:00',(''),(''),'','','');\n"
                    "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 3 1 1 }'));\nENDSEC;\nDATA;\n" + self.gents).encode()
        limit_b = int(float(os.environ.get('V6_VERIFY_CHUNK_MB', '12')) * (1 << 20))
        bykey = {}
        chunks = []
        cur, cur_b = [], 0
        # identical geometry (up to translation) is verified once: the first part of each hash group stands for all
        groups = collections.defaultdict(list)
        reps = []
        for key, fr in frags:
            if fr.ghash is not None and os.environ.get('V6_VERIFY_DEDUPE') == '1':
                # off by default: OCC 8.0.1 BRepCheck results depend on where a solid sits (located copies of a
                # valid shared solid can fail), so every part is read back where it is
                groups[fr.ghash].append(key)
                if len(groups[fr.ghash]) > 1:
                    continue
            reps.append((key, fr))
        self.deduped = getattr(self, 'deduped', 0) + len(frags) - len(reps)
        if not os.environ.get('V6_VERIFY_CHUNK_MB'):
            # enough chunks to keep every verifier process busy, each between 0.5 and 12 MB
            tot = sum(fr.size for _, fr in reps)
            limit_b = int(min(12 << 20, max(512 << 10, tot / (3.0 * self.procs))))
        with open(self.spool.path, 'rb') as sp:
            for key, fr in reps:
                bykey[fr.pd] = key; bykey[fr.sdr] = key
                sp.seek(fr.off)
                data = sp.read(fr.size)
                if fr.far is not None and getattr(self, 'far_shift', False) and fr.needs is None:
                    data = shift_points(data, fr.far)
                    self.far_parts = getattr(self, 'far_parts', 0) + 1
                # chunk items: (key, part data, shared key or None); shared blocks are written once per chunk file
                if fr.size >= limit_b // 3:
                    chunks.append([(key, data, fr.needs)])          # big part: its own file
                    continue
                cur.append((key, data, fr.needs)); cur_b += fr.size
                if cur_b >= limit_b or len(cur) >= 2000:
                    chunks.append(cur); cur, cur_b = [], 0
            if cur:
                chunks.append(cur)
        self.bykey = bykey
        self.rd = rd
        self.nfile = 0
        res = {}
        queue = [self._write(ch) for ch in chunks]
        res.update(self._pool(queue))
        for g, keys in groups.items():
            if len(keys) > 1 and keys[0] in res:
                for k in keys[1:]:
                    res[k] = res[keys[0]]
        self.sec += time.time() - t0
        if not os.environ.get('V6_KEEP_TMP'):
            shutil.rmtree(rd, ignore_errors=True)
        return res

    def _write(self, ch):
        self.nfile += 1
        fn = os.path.join(self.rd, 'c%06d.stp' % self.nfile)
        need = []
        for item in ch:
            k = item[2]
            if k is not None and k not in need:
                need.append(k)
        with open(fn, 'wb') as fh:
            fh.write(self.hdr)
            if need:
                with open(self.spool.path, 'rb') as sp:
                    for k in need:
                        shd = self.shared.get(k)
                        if shd is not None:
                            sp.seek(shd.off)
                            fh.write(sp.read(shd.size))
            for item in ch:
                fh.write(item[1])
            fh.write(TAIL.encode())
        return (fn, ch)

    def _pool(self, queue):
        """run one verifier process per chunk file, at most self.procs at a time; bisect crashing chunks"""
        res = {}
        running = []
        last_log = time.time()
        queue = list(queue)
        queue.sort(key=lambda x: -sum(len(it[1]) for it in x[1]))
        while queue or running:
            dl = getattr(self, 'deadline', None)
            if dl is not None and time.time() > dl:
                # verify time budget used up: stop reading back; parts without a result are 'budget' (not failed)
                self.exhausted = True
                for pr, fn, ch, of in running:
                    try:
                        pr.kill(); pr.wait(timeout=30)
                    except Exception:
                        pass
                    got = set()
                    if os.path.exists(of):
                        for line in open(of):
                            try:
                                r = json.loads(line)
                            except Exception:
                                continue
                            k = self.bykey.get(r.get('eid'))
                            if k is not None and 'eid' in r and ('valid' in r or r.get('empty')):
                                res[k] = r; got.add(k)
                    for it in ch:
                        if it[0] not in got:
                            res[it[0]] = {'budget': True}
                for fn, ch in queue:
                    for it in ch:
                        res[it[0]] = {'budget': True}
                running, queue = [], []
                log('verify budget used up: stopped')
                break
            while queue and len(running) < self.procs:
                fn, ch = queue.pop(0)
                lf = fn + '.json'; of = fn + '.out'
                json.dump([fn], open(lf, 'w'))
                pr = subprocess.Popen([self.py, os.path.abspath(__file__), VERIFY_CODE_MARK, lf, of],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                running.append((pr, fn, ch, of))
            still = []
            for pr, fn, ch, of in running:
                rc = pr.poll()
                if rc is None:
                    still.append((pr, fn, ch, of))
                    continue
                got = set()
                if os.path.exists(of):
                    for line in open(of):
                        try:
                            r = json.loads(line)
                        except Exception:
                            continue
                        k = self.bykey.get(r.get('eid'))
                        if k is not None:
                            res[k] = r; got.add(k)
                if rc != 0:
                    rest = [it for it in ch if it[0] not in got]
                    if len(rest) == 1 or len(ch) == 1:
                        for it in rest:
                            res[it[0]] = {'crash': rc}
                        self.crashes = getattr(self, 'crashes', 0) + 1
                    elif rest:
                        h = len(rest) // 2
                        queue.append(self._write(rest[:h]))
                        queue.append(self._write(rest[h:]))
                if not os.environ.get('V6_KEEP_TMP'):
                    for x in (fn, fn + '.json', of):
                        try:
                            os.remove(x)
                        except OSError:
                            pass
            running = still
            if running:
                time.sleep(0.05)
            if time.time() - last_log > 120:
                log('verify: %d files queued, %d running, %d results' % (len(queue), len(running), len(res)))
                last_log = time.time()
        return res


def judge(r, fr):
    """verification result -> (ok, reason)"""
    if r is not None and r.get('budget'):
        return False, 'budget'
    if r is None:
        return False, 'no_result'
    if r.get('crash') is not None:
        return False, 'reader_crash'
    if r.get('read_fail') or r.get('error'):
        return False, 'read_fail'
    if r.get('empty'):
        return False, 'empty'
    if not r.get('faces'):
        return False, 'no_faces'
    if r.get('finite') is False:
        return False, 'nonfinite'
    vals = r.get('valid') or []
    vols = r.get('vols') or []
    if any(not v for v in vals):
        return False, 'invalid'
    if any((v is None or not (v > 0)) for v in vols):
        return False, 'nonpos'
    if fr.nsol and len(vals) == 0:
        return False, 'solids_lost'
    if fr.nsol and fr.vol > 0 and vols and not fr.nopen:
        tv = sum(vols)
        if abs(tv - fr.vol) > 0.02 * fr.vol + 1e-6:
            return False, 'volume_differs'
    return True, None


# ====================================================================================================== main pipeline

class PartRec:
    __slots__ = ('eid', 'gid', 'name', 'cls', 'src', 'level', 'tags', 'frag', 'ok', 'why', 'curved', 'hist', 'inst', 'vres', 'gap', 'merged', 'sew')

    def __init__(self, eid, gid, name, cls, src, curved):
        self.eid = eid; self.gid = gid; self.name = name; self.cls = cls; self.src = src; self.level = 0
        self.tags = set(); self.frag = None; self.ok = None; self.why = None; self.curved = curved; self.hist = []
        self.gap = None       # open source shells of the written representation (gap_of)
        self.merged = False   # the written representation has coplanar faces merged (Repair.merge_coplanar)
        self.sew = 0.0        # largest seam-sewing vertex move (mm) in the written representation (sew_max_mm)
        self.inst = None      # (shared key, R, t) when the part places shared geometry
        self.vres = None      # read-back result of the representation that is written (verify_worker record)


DESC_TAGS = {'L1': 'L1-triangulated', 'L2': 'L2-alt-source', 'L3': 'L3-partial-surface', 'L4': 'L4-surface',
             'approx-curved': 'approx-curved', 'unverified': 'unverified', 'open-surface': 'open-surface'}


def describe(rec):
    t = [DESC_TAGS[k] for k in ('approx-curved', 'L1', 'L2', 'L3', 'L4', 'open-surface', 'unverified') if k in rec.tags]
    return rec.cls + (' [v6:%s]' % ','.join(t) if t else '')


def part_name(pr):
    nm = getattr(pr, 'Name', None)
    if nm:
        return str(nm)
    return "%s_%s" % (pr.is_a(), getattr(pr, 'GlobalId', None) or pr.id())


def main(argv=None):
    ap = argparse.ArgumentParser(description=VERSION)
    ap.add_argument("ifc")
    ap.add_argument("out")
    ap.add_argument("--mode", default="hybrid", choices=["transcode", "tess", "hybrid"])
    ap.add_argument("--threads", type=int, default=0)
    ap.add_argument("--nodedup", action="store_true", help="(v5 compatibility; points are always welded on the output grid)")
    ap.add_argument("--noplane", action="store_true", help="(v5 compatibility; ignored: OpenCASCADE drops faces without a surface)")
    ap.add_argument("--prec", type=int, default=6)
    ap.add_argument("--gzip", action="store_true")
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--verify-procs", type=int, default=0)
    ap.add_argument("--no-surface-fallback", action="store_true")
    ap.add_argument("--sidecar", default=None)
    ap.add_argument("--keep-tmp", action="store_true")
    a = ap.parse_args(argv)
    if os.environ.get('V6_NO_SURFACE_FALLBACK') == '1':
        a.no_surface_fallback = True
    if os.environ.get('V6_NO_VERIFY') == '1':
        a.no_verify = True
    threads = a.threads if a.threads > 0 else (os.cpu_count() or 4)
    T0 = time.time()
    stats = {"input": a.ifc, "mode": a.mode, "nodedup": a.nodedup, "noplane": a.noplane, "prec": a.prec,
             "in_bytes": os.path.getsize(a.ifc), "converter": VERSION}
    outdir = os.path.dirname(os.path.abspath(a.out)) or '.'
    tmpdir = tempfile.mkdtemp(prefix='.v6tmp_', dir=outdir)
    info = {}
    try:
        return _run(a, threads, stats, tmpdir, info, T0)
    finally:
        if not (a.keep_tmp or os.environ.get('V6_KEEP_TMP')):
            shutil.rmtree(tmpdir, ignore_errors=True)


PHASE = ['start']
T_START = [time.time()]


def _heartbeat(t0):
    # the fleet worker kills a converter whose log is silent for 30 min (stall = kernel hang): say we are alive
    while True:
        time.sleep(120)
        log('alive: %s, %.0fs, rss=%dMB' % (PHASE[0], time.time() - t0, rss()))


def _run(a, threads, stats, tmpdir, info, T0):
    import ifcopenshell
    import ifcopenshell.util.unit
    import threading
    threading.Thread(target=_heartbeat, args=(T0,), daemon=True).start()
    T_START[0] = T0
    t = time.time()
    src = prepare_input(a.ifc, tmpdir, info)
    f, src = open_ifc(src, tmpdir, info)
    stats["parse_sec"] = round(time.time() - t, 2)
    stats["schema"] = f.schema
    stats["schema_declared"] = info.get('schema_declared')
    stats["input_kind"] = info.get('input_kind')
    stats["input_fix"] = info.get('input_fix') or None
    if os.environ.get('V6_NO_CURVE_REPAIR') != '1':
        stats["null_curve_segments_dropped"] = repair_null_curve_segments(f)
    try:
        m_per_unit = float(ifcopenshell.util.unit.calculate_unit_scale(f))
    except Exception:
        m_per_unit = 1.0
    stats["m_per_ifc_unit"] = m_per_unit
    stats["file_length_unit"] = length_unit_name(f)
    sc = m_per_unit * 1000.0
    prec = a.prec
    repair = Repair(prec)
    spool = Spool(os.path.join(tmpdir, 'spool.bin'), prec)
    hdr, gents = header_text(os.path.basename(a.ifc))
    tc = Transcoder(f, sc)
    recs = []
    kernel_list = []
    n_norep = n_unsup = n_corrupt = 0
    t_tc = time.time()
    products = f.by_type("IfcProduct")
    nprod = len(products)
    log('%s: %d products, schema %s, unit %s' % (VERSION, nprod, f.schema, stats["file_length_unit"]))
    PHASE[0] = 'transcode'
    # instancing: products whose body is one IfcMappedItem of a representation map shared with other such products
    # (no openings) place one shared geometry with a rigid transform (MAPPED_ITEM) instead of a copy each
    shared = {}
    inst_count = collections.Counter()
    use_inst = os.environ.get('V6_NO_INSTANCING') != '1'
    if use_inst:
        for pr in products:
            if pr.is_a() in SKIP_TYPES:
                continue
            k = inst_key(pr)
            if k is not None:
                inst_count[k] += 1
    pending_inst = collections.defaultdict(list)   # key -> recs waiting for kernel-made shared geometry
    absurd = []                                    # parts left out: coordinates beyond 1e10 mm (corrupt source)
    n_open_kernel = 0
    n_inst_nonrigid = 0
    n_inst_far = 0
    for pn, pr in enumerate(products):
        if pn % 20000 == 0 and pn:
            log('[transcode] %d/%d parts=%d %.0fs rss=%dMB' % (pn, nprod, len(recs), time.time() - t_tc, rss()))
        if pr.is_a() in SKIP_TYPES:
            continue
        items, rid = body_items(pr)
        if not items:
            n_norep += 1
            continue
        curved = any(item_curved(f, it) for it in items)
        openings = [o.RelatedOpeningElement for o in (getattr(pr, 'HasOpenings', None) or [])]
        if openings and not curved:
            for op in openings:
                oi, _ = body_items(op)
                if oi and any(item_curved(f, it) for it in oi):
                    curved = True
                    break
        rec = PartRec(pr.id(), getattr(pr, 'GlobalId', None), part_name(pr), pr.is_a(), 'tc', curved)
        recs.append(rec)
        # ---- instancing
        k = inst_key(pr) if use_inst else None
        if k is not None and inst_count[k] >= 2:
            RT = inst_transform(tc, pr, items[0])
            if RT is None:
                n_inst_nonrigid += 1
            else:
                R, t = RT
                rec.inst = (k, R, t)
                sh = shared.get(k)
                if sh is None:
                    srcs = items[0].MappingSource.MappedRepresentation.Items
                    pieces = tc.items_local(srcs) if a.mode != 'tess' else None
                    if pieces is not None:
                        bp = build_part(pieces, repair)
                        if bp is not None and bp != 'corrupt':
                            sh = spool.emit(None, None, None, bp[1], bp[2], bp[0], shared_key=k)
                            if sh is not None:
                                sh.src = 'tc'; sh.curved = curved
                                sh.tags = {t_ for t_ in bp[3] if t_ in KEEP_TAGS}
                                sh.gap = gap_of(bp[1] + bp[2]); sh.merged = 'merged' in bp[3]; sh.sew = sew_of(bp[1] + bp[2])
                                shared[k] = sh
                    if sh is None and k not in pending_inst and a.mode != 'transcode':
                        # first instance goes to the kernel; its shape (back in the map frame) becomes the shared one
                        rec.src = 'kernel'
                        pending_inst[k] = []
                        kernel_list.append(rec)
                        continue
                if sh is not None:
                    emit_instance_rec(spool, rec, sh)
                    continue
                if k in pending_inst:
                    rec.src = 'kernel'
                    pending_inst[k].append(rec)
                    continue
                rec.inst = None
        if openings and a.mode != 'transcode':
            # openings void the element in IFC whatever its representation: the kernel applies them (v5 transcoded
            # faceted bodies without their openings - holes and cuts were missing)
            n_open_kernel += 1
            rec.src = 'kernel'
            kernel_list.append(rec)
            continue
        if a.mode == 'tess':
            rec.src = 'kernel'
            kernel_list.append(rec)
            continue
        pieces = tc.product(pr, items)
        if pieces is None:
            n_unsup += 1
            rec.src = 'kernel'
            kernel_list.append(rec)
            continue
        bp = build_part(pieces, repair)
        if bp == 'corrupt' or bp is None:
            if bp == 'corrupt':
                n_corrupt += 1
            rec.src = 'kernel'
            kernel_list.append(rec)
            continue
        if absurd_part(bp, rec, absurd):
            continue
        emit_rec(spool, rec, bp, level=0)
    stats["transcode_with_openings_to_kernel"] = n_open_kernel
    stats["transcode_products"] = sum(1 for r in recs if r.src == 'tc' and r.frag is not None)
    stats["transcode_skipped"] = len(kernel_list)
    stats["transcode_no_body_rep"] = n_norep
    stats["transcode_unsupported"] = n_unsup
    stats["transcode_corrupt_coords_tessellated"] = n_corrupt
    stats["transcode_coverage_pct"] = round(100.0 * stats["transcode_products"] / max(1, len(recs)), 1)
    stats["transcode_sec"] = round(time.time() - t_tc, 2)
    # ---- half-space clipping products whose kernel split may be wrong (see exact_clip)
    if kernel_list and a.mode != 'transcode' and os.environ.get('V6_NO_EXACT_CLIP') != '1':
        CLIP_ITEMS.clear(); CLIP_EXACT.clear()
        for r in kernel_list:
            if r.inst is not None:
                continue
            pr = f.by_id(r.eid)
            if getattr(pr, 'HasOpenings', None):
                continue
            items, _ = body_items(pr)
            if items and len(items) == 1 and halfspace_chain(items[0]) is not None:
                CLIP_ITEMS[r.eid] = items[0]
        stats['exact_clip'] = {'candidates': len(CLIP_ITEMS)}
    # ---- kernel pass
    t_k = time.time()
    kmem = []                                      # products left out: their kernel run died (memory cap / crash / stall)
    PHASE[0] = 'kernel %d products' % len(kernel_list)
    if kernel_list and a.mode != 'transcode':
        byid = {r.eid: r for r in kernel_list}
        prods = [f.by_id(r.eid) for r in kernel_list]

        def on_shape(eid, V, faces, iids):
            r = byid.get(eid)
            if r is None or r.frag is not None:
                return
            if eid in CLIP_ITEMS:
                V, faces, iids = clip_fix(f, eid, V, faces, iids, stats, m_per_unit)
                if eid in CLIP_EXACT:
                    r.tags.add('exact-clip')
            if r.inst is not None and r.inst[0] in pending_inst and r.inst[0] not in shared:
                k, R, t = r.inst
                Vm = (V - np.array(t)) @ np.array(R)       # world -> map frame (R orthonormal)
                bp = build_part(kernel_pieces(f, Vm, faces, iids), repair)
                if bp is not None and bp != 'corrupt':
                    sh = spool.emit(None, None, None, bp[1], bp[2], bp[0], shared_key=k)
                    if sh is not None:
                        sh.src = 'kernel'; sh.curved = r.curved
                        sh.tags = {t_ for t_ in bp[3] if t_ in KEEP_TAGS}
                        sh.gap = gap_of(bp[1] + bp[2]); sh.merged = 'merged' in bp[3]; sh.sew = sew_of(bp[1] + bp[2])
                        shared[k] = sh
                        emit_instance_rec(spool, r, sh)
                        return
                r.inst = None
            pieces = kernel_pieces(f, V, faces, iids)
            bp = build_part(pieces, repair)
            if bp is None or bp == 'corrupt':
                if bp == 'corrupt':
                    absurd.append(r); r.tags.add('excluded-corrupt-coordinates')
                return
            if absurd_part(bp, r, absurd):
                return
            if r.curved:
                r.tags.add('approx-curved')
            emit_rec(spool, r, bp, level=0)
        kexcl = kernel_pass_isolated(f, prods, threads, 'poly', 'kernel_pass', stats, on_shape)
        # instances waiting for kernel-made shared geometry
        second = []
        for k, lst in pending_inst.items():
            sh = shared.get(k)
            for r in lst:
                if sh is not None:
                    emit_instance_rec(spool, r, sh)
                else:
                    r.inst = None
                    second.append(r)
        if second:
            byid = {r.eid: r for r in second}
            kexcl += kernel_pass_isolated(f, [f.by_id(r.eid) for r in second], threads, 'poly', 'kernel_pass2', stats, on_shape)
        byid_all = {r.eid: r for r in recs}
        for p_ in kexcl:
            r_ = byid_all.get(p_.id())
            if r_ is not None and r_.frag is None:
                r_.tags.add('kernel_memory_exceeded')
                kmem.append(r_)
        # ---- opening-tool repair, retry only (6.1.6): a product with openings whose kernel result with the ORIGINAL
        # opening tools is empty is run once more with contact walls removed from its opening shells (see
        # repair_opening_shells); every other product keeps its original result, and the tools are restored after.
        # (6.1.2-6.1.5 repaired the tools before the pass: on SDS/2 v2020 pipe-cope models that lost 36 valid parts.)
        if os.environ.get('V6_NO_OPENING_REPAIR') != '1':
            km_ids = set(id(r_) for r_ in kmem) | set(id(r_) for r_ in absurd)
            retry = [r_ for r_ in kernel_list if r_.frag is None and id(r_) not in km_ids and r_.inst is None
                     and getattr(f.by_id(r_.eid), 'HasOpenings', None)]
            info = {'empty_with_openings': len(retry)}
            if retry:
                prods_r = [f.by_id(r_.eid) for r_ in retry]
                rinfo, undo = repair_opening_shells(prods_r)
                info.update(rinfo)
                try:
                    if rinfo.get('shells_repaired'):
                        byid = {r_.eid: r_ for r_ in retry}
                        kernel_pass_isolated(f, prods_r, threads, 'poly', 'kernel_opening_retry', stats, on_shape)
                        rec_ = [r_ for r_ in retry if r_.frag is not None]
                        for r_ in rec_:
                            r_.tags.add('opening-tool-repaired')
                        info['recovered'] = len(rec_)
                finally:
                    for sh_, faces_ in undo:
                        try:
                            sh_.CfsFaces = faces_
                        except Exception:
                            pass
            stats['opening_shell_repair'] = info
    stats["instancing"] = {'shared_representations': len(shared), 'instances': sum(1 for r in recs if r.frag is not None and r.frag.needs is not None),
                           'not_rigid_expanded': n_inst_nonrigid, 'far_expanded': n_inst_far}
    stats["tess_products"] = sum(1 for r in recs if r.src == 'kernel' and r.frag is not None)
    stats["tess_sec"] = round(time.time() - t_k, 2)
    if os.environ.get('V6_FAR_VERIFY') == '1' and not FAR_VERIFY:
        stats['far_verify'] = 'ignored (V6_FAR_VERIFY is a no-op since 6.1.6)'
    stats["kernel_memory_exceeded_total"] = len(kmem)
    stats["kernel_memory_exceeded"] = [[r.gid, r.cls, r.name] for r in kmem[:50]]
    stats["excluded_absurd_coordinates_total"] = len(absurd)
    stats["excluded_absurd_coordinates"] = [[r.gid, r.cls, r.name] for r in absurd[:50]]
    ab_ids = set(id(r) for r in absurd) | set(id(r) for r in kmem)
    missing = [r for r in recs if r.frag is None and id(r) not in ab_ids]
    stats["parts_without_geometry"] = len(missing)
    stats["parts_without_geometry_examples"] = [[r.gid, r.cls, r.name] for r in missing[:20]]
    recs = [r for r in recs if r.frag is not None]
    # ---- verification + fallback chain
    ver = None
    vstats = collections.Counter()
    if not a.no_verify:
        vp = a.verify_procs or int(os.environ.get('V6_VERIFY_PROCS', '0') or 0) or max(2, threads, min(8, (os.cpu_count() or 4) // 4))
        ver = Verifier(spool, tmpdir, vp, gents, shared)
        if not ver.available():
            log('verification unavailable (no pythonocc found)')
            ver = None
    PHASE[0] = 'verify'
    if ver is None:
        for r in recs:
            r.tags.add('unverified')
        stats['verify'] = 'unavailable' if not a.no_verify else 'disabled'
    else:
        verify_and_fallback(f, recs, spool, ver, repair, tc, threads, a, stats, vstats)
        recs = [r for r in recs if r.frag is not None]
        nfar = sum(1 for r in recs if 'far-origin' in r.tags)
        if nfar:
            stats['far_origin'] = {'parts': nfar, 'threshold_mm': FAR_MM,
                                   'note': 'exact L0 solid kept: invalid in place only through OCC precision far from the origin, valid on a copy translated by whole km; STEP keeps the source coordinates'}
    # ---- assemble
    spool.close()
    if spool.degenerate_skipped:
        stats['faces_zero_area_skipped_at_write'] = spool.degenerate_skipped
    PHASE[0] = 'assemble'
    t_a = time.time()
    n_parts = 0
    n_faces = 0
    with open(a.out, 'wb') as out, open(spool.path, 'rb') as sp:
        out.write(hdr.encode()); out.write(gents.encode())
        # shared representations first (each part block then references only the header block and one shared block)
        need = []
        seen_k = set()
        for r in recs:
            k = r.frag.needs
            if k is not None and k not in seen_k:
                seen_k.add(k); need.append(k)
        for k in need:
            sh = shared[k]
            sp.seek(sh.off)
            out.write(sp.read(sh.size))
        for r in recs:
            sp.seek(r.frag.off)
            data = sp.read(r.frag.size)
            out.write(data)
            n_parts += 1
            n_faces += r.frag.nfaces
        out.write(TAIL.encode())
    stats["assemble_sec"] = round(time.time() - t_a, 2)
    stats["out_bytes"] = os.path.getsize(a.out)
    stats["parts"] = n_parts
    stats["faces"] = n_faces
    stats["solids_written"] = sum(r.frag.nsol for r in recs)
    stats["surface_models_written"] = sum(1 for r in recs if r.frag.nsurf)
    stats["entities"] = spool.n - FIRST_ID
    stats["total_sec"] = round(time.time() - T0, 2)
    stats["peak_rss_mb"] = rss()
    bb = spool.bb
    stats["bbox"] = [round(v, 3) for v in bb] if bb[0] <= bb[3] else None
    stats["degenerate_faces_dropped"] = repair.stats.get('faces_degenerate_dropped', 0) + repair.stats.get('faces_zero_area_dropped', 0)
    stats["bytes_per_face"] = round(stats["out_bytes"] / max(1, n_faces), 1)
    stats["expansion"] = round(stats["out_bytes"] / max(1, stats["in_bytes"]), 2)
    stats["repair"] = dict(repair.stats)
    lv = collections.Counter('L%d' % r.level for r in recs)
    stats["levels"] = dict(lv)
    tg = collections.Counter(DESC_TAGS.get(t, t) for r in recs for t in r.tags)
    stats["tags"] = dict(tg)            # fallback levels under their description names (L4-surface, ...)
    stats["exact_parts"] = sum(1 for r in recs if not (r.tags & {'approx-curved', 'L1', 'L2', 'L3', 'L4', 'open-surface', 'unverified'}))
    stats["approx_parts"] = len(recs) - stats["exact_parts"]
    stats["surface_fallback_parts"] = sum(1 for r in recs if r.tags & {'L3', 'L4', 'open-surface'})
    nonexact = [[r.gid, r.cls, r.name, r.src, r.level, sorted(DESC_TAGS.get(t, t) for t in r.tags)] for r in recs
                if r.tags & {'L1', 'L2', 'L3', 'L4', 'open-surface', 'unverified'}]
    stats["tagged_parts"] = nonexact[:5000]
    stats["tagged_parts_total"] = len(nonexact)
    if a.gzip:
        t = time.time()
        os.system("gzip -1 -k -f '%s'" % a.out)
        stats["gz_sec"] = round(time.time() - t, 2)
        stats["gz_bytes"] = os.path.getsize(a.out + ".gz")
        stats["gz_ratio"] = round(stats["out_bytes"] / max(1, stats["gz_bytes"]), 1)
        os.remove(a.out + ".gz")
    sw = [r for r in recs if r.sew]
    if sw:
        # seam sewing (Repair.sew, boundary vertices merged up to tol_sew = 0.1 mm at prec 2): largest move per part
        stats['sewn_parts'] = {'parts': len(sw), 'sew_max_mm': max(r.sew for r in sw),
                               'sew_max_mm_hist': dict(collections.Counter(sew_bucket(r.sew) for r in sw))}
    gp = [r for r in recs if r.gap]
    if gp:
        stats['open_source_shells'] = {
            'parts_open_in_source': sum(1 for r in recs if 'open_in_source' in r.tags),
            'parts_closed_within_tol': sum(1 for r in gp if r.gap.get('closed_within_mm') is not None),
            'close_tol_mm': GAP_CLOSE_MM,
            'gap_max_mm_hist': dict(collections.Counter(gap_bucket(r.gap) for r in gp if 'open_in_source' in r.tags)),
            'parts_nonmanifold': sum(1 for r in gp if r.gap.get('nonmanifold_edges'))}
    side = a.sidecar or (a.out + '.parts.json')
    try:
        with open(side, 'w') as sf:
            json.dump({'converter': VERSION, 'input': a.ifc, 'schema': stats['schema'], 'parts': [
                {'gid': r.gid, 'name': r.name, 'cls': r.cls, 'src': r.src, 'level': r.level, 'tags': sorted(DESC_TAGS.get(t, t) for t in r.tags),
                 'exact': not (r.tags & {'approx-curved', 'L1', 'L2', 'L3', 'L4', 'open-surface', 'unverified'}),
                 'solids': r.frag.nsol, 'surface_models': r.frag.nsurf, 'faces': r.frag.nfaces,
                 'volume_mm3': round(r.frag.vol, 3), 'why': r.hist,
                 **({'gap_max_mm': r.gap.get('gap_max_mm'), 'open_shell': r.gap} if r.gap else {}),
                 **({'sew_max_mm': r.sew} if r.sew else {})} for r in recs]}, sf)
        stats['sidecar'] = os.path.basename(side)
    except Exception as e:
        stats['sidecar_error'] = str(e)[:200]
    if ver is not None:
        # per-part read-back of the written representation, in step_check's --parts format (pid = GlobalId, solids,
        # BRepCheck-valid solids, volume): every part was read back from its own STEP block by verify_worker (same OCC
        # checks as step_check), so a STEP too large for a whole-file read-back still has per-part data for the join
        try:
            vp = a.out + '.verify_parts.jsonl.gz'
            tot = collections.Counter()
            with gzip.open(vp, 'wt') as g:
                for i, r in enumerate(recs, 1):
                    v = r.vres or {}
                    rec = {'i': i, 'pid': r.gid, 'name': r.name, 'desc': describe(r)}
                    if not v and 'verify_partial' in r.tags:
                        rec.update(verify_partial=True)
                        tot['verify_partial'] += 1
                    elif not v or v.get('empty') or v.get('crash') is not None or v.get('read_fail') or v.get('error'):
                        rec.update(solids=0, empty=True)
                        tot['empty_roots'] += 1
                    else:
                        vals = v.get('valid') or []
                        vols = [x for x in (v.get('vols') or []) if x is not None]
                        rec.update(solids=v.get('solids') or 0, faces=v.get('faces') or 0)
                        if not rec['solids']:
                            rec['shells'] = v.get('shells')
                        else:
                            rec.update(valid=sum(1 for x in vals if x), volume=round(sum(vols), 3))
                        tot['transferred'] += 1; tot['solids'] += rec['solids']; tot['faces'] += rec['faces']
                        tot['valid'] += sum(1 for x in vals if x); tot['invalid'] += sum(1 for x in vals if not x)
                        tot['nonpos_vol'] += sum(1 for x in (v.get('vols') or []) if x is None or not (x > 0))
                        if v.get('finite') is False:
                            tot['nonfinite'] += 1
                    g.write(json.dumps(rec) + '\n')
            stats['readback_parts'] = dict(tot, roots=len(recs), file=os.path.basename(vp),
                                           how='converter read-back of every written part (own STEP block, step_check checks)')
        except Exception as e:
            stats['readback_parts_error'] = str(e)[:200]
    with open(a.out + ".stats.json", "w") as sf:
        json.dump(stats, sf, indent=1)
    print(json.dumps({k: v for k, v in stats.items() if k not in ('tagged_parts',)}))
    return 0


def kernel_pieces(f, V, faces, iids):
    """kernel output of one product -> one Piece per representation item (bodies of different items that touch
    share edges; analysed together they would look non-manifold)"""
    if not iids or len(set(iids)) < 2:
        return [Piece(V, faces, kernel_role(f, faces, iids), 1)]
    by = collections.defaultdict(list)
    for fc, i in zip(faces, iids):
        by[i].append(fc)
    out = []
    for g, (i, fl) in enumerate(sorted(by.items())):
        out.append(Piece(V, fl, kernel_role(f, fl, [i] * len(fl)), g + 1))
    return out


def kernel_role(f, faces, iids):
    """kernel output of surface-type items stays a surface; everything else is offered as a solid"""
    if not iids:
        return 'solid'
    roles = set()
    for i in set(iids):
        try:
            e = f.by_id(int(i))
        except Exception:
            roles.add('solid'); continue
        if e is not None and any(e.is_a(t) for t in SURFACE_ITEM_TYPES):
            if e.is_a('IfcTessellatedFaceSet') and getattr(e, 'Closed', None) is not False:
                roles.add('solid')
            else:
                roles.add('surface')
        else:
            roles.add('solid')
    return 'surface' if roles == {'surface'} else 'solid'


# ====================================================================================================== exact half-space clipping

# ifcopenshell 0.9.0 evaluates some IfcBooleanClippingResult chains (one solid minus several plane half-spaces) as a split:
# the pieces that earlier half-spaces cut away come back as extra solids touching the kept piece (Camellia 4bbcc615, Tekla
# "DUMMY" HSS4X2X1/4: 7 solids summing to the uncut tube's 2,150,817 mm3; the same operands cut in OCC give 1 valid solid
# of 1,801,486 mm3). The converter then sees touching shells (edges used 4x), removes the contact faces and is left with
# open shells -> surfaces / L2 / no solid. For such products the clipping is computed exactly from the same IFC operands
# (base solid from the kernel, BRepAlgoAPI_Cut with BRepPrimAPI_MakeHalfSpace per IfcHalfSpaceSolid, IFC AgreementFlag
# semantics) and its BRepMesh triangles (kernel deflection; build_part merges coplanar triangles back into the exact planar
# polygons) replace the kernel output. Only when the kernel mesh is not a clean 2-manifold AND the kernel's own B-rep
# differs from the exact clip (volume or solid count) AND the exact clip is a BRepCheck-valid solid set of positive
# volume not above the base solid's. Opt-out V6_NO_EXACT_CLIP=1.
CLIP_ITEMS = {}     # product id -> its single body item (a plane half-space DIFFERENCE chain on one solid)
CLIP_EXACT = {}     # product id -> (V mm, faces, iids): exact clip mesh used instead of the kernel output
_CLIP_OCC = []


def halfspace_chain(item):
    """IfcBooleanClippingResult / IfcBooleanResult DIFFERENCE chain whose second operands are all plane half-spaces
    (IfcHalfSpaceSolid / IfcBoxedHalfSpace on an IfcPlane; not IfcPolygonalBoundedHalfSpace) cut from one solid
    -> (base solid item, half-spaces in application order) or None"""
    hs = []
    node = item
    while node is not None and node.is_a('IfcBooleanResult'):
        so = node.SecondOperand
        if node.Operator != 'DIFFERENCE' or so is None or not so.is_a('IfcHalfSpaceSolid') or \
                so.is_a('IfcPolygonalBoundedHalfSpace') or so.BaseSurface is None or not so.BaseSurface.is_a('IfcPlane'):
            return None
        hs.append(so)
        node = node.FirstOperand
    if not hs or node is None or not node.is_a('IfcSolidModel'):
        return None
    return node, hs[::-1]


def _clip_occ():
    if not _CLIP_OCC:
        try:
            from OCC.Core.BRep import BRep_Builder, BRep_Tool
            from OCC.Core.BRepTools import breptools
            from OCC.Core.TopoDS import TopoDS_Shape, topods
            from OCC.Core.gp import gp_Pln, gp_Pnt, gp_Dir
            from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_MakeFace
            from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeHalfSpace
            from OCC.Core.BRepAlgoAPI import BRepAlgoAPI_Cut
            from OCC.Core.BRepCheck import BRepCheck_Analyzer
            from OCC.Core.BRepGProp import brepgprop
            from OCC.Core.GProp import GProp_GProps
            from OCC.Core.TopExp import TopExp_Explorer
            from OCC.Core.TopAbs import TopAbs_SOLID, TopAbs_FACE, TopAbs_REVERSED
            from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
            from OCC.Core.TopLoc import TopLoc_Location
            _CLIP_OCC.append(dict(locals()))
        except Exception:
            _CLIP_OCC.append(None)
    return _CLIP_OCC[0]


def _edges_2manifold(faces):
    """every edge of the (welded, indexed) kernel mesh used by exactly two faces"""
    ec = collections.Counter()
    for fc in faces:
        for lp in fc:
            n = len(lp)
            for i in range(n):
                a_, b_ = lp[i], lp[(i + 1) % n]
                if a_ != b_:
                    ec[(a_, b_) if a_ < b_ else (b_, a_)] += 1
    return bool(ec) and all(v == 2 for v in ec.values())


def exact_clip(pr, item, us):
    """exact clip of the product's half-space chain -> ((V mm world, faces, iids), info) or (None, info)"""
    O = _clip_occ()
    if not O:
        return None, {'why': 'no_pythonocc'}
    import tempfile
    import ifcopenshell.geom
    import ifcopenshell.ifcopenshell_wrapper as W
    base, hss = halfspace_chain(item)

    def rd(txt):
        fn = tempfile.mktemp(suffix='.brep')
        with open(fn, 'w') as fh:
            fh.write(txt)
        sh = O['TopoDS_Shape'](); O['breptools'].Read(sh, fn, O['BRep_Builder']()); os.remove(fn)
        return sh

    def solids(sh):
        out = []
        e = O['TopExp_Explorer'](sh, O['TopAbs_SOLID'])
        while e.More():
            out.append(e.Current()); e.Next()
        return out

    def vol(sh):
        gp = O['GProp_GProps'](); O['brepgprop'].VolumeProperties(sh, gp)
        return gp.Mass()
    sl = ifcopenshell.geom.settings()
    sl.set('iterator-output', W.SERIALIZED)
    g = ifcopenshell.geom.create_shape(sl, pr)                 # the kernel's own B-rep (product frame) + its placement
    kb = rd(g.geometry.brep_data)
    m = [float(x) for x in g.transformation.matrix]
    if len(m) == 16:
        M = np.array(m).reshape(4, 4).T
    else:
        M = np.eye(4); M[:3, :] = np.array(m).reshape(4, 3).T
    bg = ifcopenshell.geom.create_shape(sl, base)
    sh = rd(bg.brep_data if hasattr(bg, 'brep_data') else bg.geometry.brep_data)
    v_base = vol(sh)
    for hs in hss:
        pos = hs.BaseSurface.Position
        c = [float(x) for x in pos.Location.Coordinates] + [0.0] * (3 - len(pos.Location.Coordinates))
        p = np.array(c) * us
        n = np.array([float(x) for x in pos.Axis.DirectionRatios]) if pos.Axis is not None else np.array([0.0, 0.0, 1.0])
        n = n / np.linalg.norm(n)
        face = O['BRepBuilderAPI_MakeFace'](O['gp_Pln'](O['gp_Pnt'](*p), O['gp_Dir'](*n))).Face()
        ref = p - n if hs.AgreementFlag else p + n           # AgreementFlag TRUE: the normal points away from the material
        op = O['BRepAlgoAPI_Cut'](sh, O['BRepPrimAPI_MakeHalfSpace'](face, O['gp_Pnt'](*ref)).Solid())
        op.Build()
        if not op.IsDone() or op.HasErrors():
            return None, {'why': 'occ_cut_failed'}
        sh = op.Shape()
    sols = solids(sh)
    vs = [vol(s_) for s_ in sols]
    ev, kv, kn = sum(vs), vol(kb), len(solids(kb))
    info = {'base_mm3': round(v_base * 1e9, 1), 'kernel_mm3': round(kv * 1e9, 1), 'kernel_solids': kn,
            'exact_mm3': round(ev * 1e9, 1), 'exact_solids': len(sols)}
    if not sols or not O['BRepCheck_Analyzer'](sh).IsValid() or any(not (v > 0) for v in vs) or ev > v_base * (1 + 1e-6):
        return None, dict(info, why='exact_not_valid_solid')
    if kn == len(sols) and abs(kv - ev) <= 1e-6 * v_base:
        return None, dict(info, why='kernel_agrees')
    s0, _, _ = kernel_settings('poly')
    try:
        lin = float(s0.get('mesher-linear-deflection')); ang = float(s0.get('mesher-angular-deflection'))
    except Exception:
        lin, ang = 0.001, 0.5
    O['BRepMesh_IncrementalMesh'](sh, lin, False, ang, True)
    P = []; F = []
    e = O['TopExp_Explorer'](sh, O['TopAbs_FACE'])
    while e.More():
        fc = O['topods'].Face(e.Current()); loc = O['TopLoc_Location']()
        tri = O['BRep_Tool'].Triangulation(fc, loc)
        if tri is None:
            return None, dict(info, why='mesh_failed')
        tr = loc.Transformation()
        b0 = len(P)
        for i in range(1, tri.NbNodes() + 1):
            q = tri.Node(i).Transformed(tr); P.append((q.X(), q.Y(), q.Z()))
        rev = fc.Orientation() == O['TopAbs_REVERSED']
        for i in range(1, tri.NbTriangles() + 1):
            a_, b_, c_ = tri.Triangle(i).Get()
            F.append([[b0 + a_ - 1, b0 + c_ - 1, b0 + b_ - 1]] if rev else [[b0 + a_ - 1, b0 + b_ - 1, b0 + c_ - 1]])
        e.Next()
    P = np.array(P, np.float64)
    # nodes the faces share (edge polygons) as one point each, then the kernel's frame -> world, metres -> mm
    P = np.round(P, 10)
    u, inv = np.unique(P, axis=0, return_inverse=True)
    inv = inv.ravel()
    F = [[[int(inv[i]) for i in lp] for lp in fc] for fc in F]
    Vw = (np.hstack([u, np.ones((len(u), 1))]) @ M.T)[:, :3] * 1000.0
    return (Vw, F, [item.id()] * len(F)), dict(info, why='replaced')


def clip_fix(f, eid, V, faces, iids, stats, us):
    """kernel output of a half-space clipping product -> the exact clip mesh where the kernel's split is wrong"""
    hit = CLIP_EXACT.get(eid)
    if hit is not None:
        return hit
    st = stats.setdefault('exact_clip', {})
    if _edges_2manifold(faces):
        st['kernel_manifold_kept'] = st.get('kernel_manifold_kept', 0) + 1
        return V, faces, iids
    try:
        res, info = exact_clip(f.by_id(eid), CLIP_ITEMS[eid], us)
    except Exception as e:
        res, info = None, {'why': 'error_%s' % type(e).__name__}
    k = info['why'] if res is None else 'replaced'
    st[k] = st.get(k, 0) + 1
    ex = st.setdefault('examples', [])
    if len(ex) < 50:
        ex.append([getattr(f.by_id(eid), 'GlobalId', None), eid, info])
    if res is None:
        return V, faces, iids
    CLIP_EXACT[eid] = res
    return res


KEEP_TAGS = {'reoriented', 'components', 'void', 'tjunction', 'open_in_source', 'open-surface', 'sewn', 'double-sided', 'stray-faces',
             'coplanar_overlap_merged'}
ABSURD_MM = 1e10        # the grader's absurd-bbox limit: geometry this far out is corrupt source data


def _opening_shells(item, depth=0):
    """closed shells of the faceted solids an opening body draws (through mapped items and boolean operands)"""
    if depth > 16 or item is None:
        return
    if item.is_a('IfcMappedItem'):
        for si in item.MappingSource.MappedRepresentation.Items or []:
            yield from _opening_shells(si, depth + 1)
    elif item.is_a('IfcFacetedBrep'):             # incl. IfcFacetedBrepWithVoids (its Outer)
        yield item.Outer
    elif item.is_a('IfcBooleanResult'):
        yield from _opening_shells(item.FirstOperand, depth + 1)
        yield from _opening_shells(item.SecondOperand, depth + 1)


def _shell_loops(shell):
    """per face of an IfcClosedShell: its single polygon as rounded coordinates in traversal order (None if the face has
    holes or is not a poly loop), and the edge-use counter of the whole shell"""
    loops = []
    use = collections.Counter()
    for fc in shell.CfsFaces or []:
        pts_all = []
        for b in fc.Bounds or []:
            lp = b.Bound
            if not lp.is_a('IfcPolyLoop'):
                pts_all = None
                break
            pts = [tuple(round(float(x), 9) for x in p.Coordinates) for p in lp.Polygon]
            if getattr(b, 'Orientation', True) is False:
                pts = pts[::-1]
            pts_all.append(pts)
        if pts_all is None:
            return None, None
        for pts in pts_all:
            for i in range(len(pts)):
                a_, b_ = pts[i], pts[(i + 1) % len(pts)]
                if a_ != b_:
                    use[(a_, b_) if a_ < b_ else (b_, a_)] += 1
        loops.append(pts_all[0] if len(pts_all) == 1 else None)
    return loops, use


def contact_wall_pairs(shell):
    """pairs of faces of one closed shell covering the same polygon with opposite winding: two bodies touching face to
    face exported as one shell (the shared face once per body). -> ([(i, j)], non-2-manifold edges before, after)"""
    loops, use = _shell_loops(shell)
    if not loops:
        return [], 0, 0
    by = collections.defaultdict(list)
    for k, lp in enumerate(loops):
        if lp is not None and len(lp) >= 3 and len(set(lp)) == len(lp):
            by[frozenset(lp)].append(k)
    pairs = []
    for ks in by.values():
        if len(ks) != 2:
            continue
        a_, b_ = loops[ks[0]], loops[ks[1]]
        if len(a_) != len(b_):
            continue
        i = b_.index(a_[0])
        if b_[i::-1] + b_[:i:-1] == a_:             # same cycle, walked the other way round
            pairs.append(tuple(ks))
    bad0 = sum(1 for n in use.values() if n != 2)
    if not pairs:
        return [], bad0, bad0
    use2 = collections.Counter(use)
    for ks in pairs:
        for k in ks:
            lp = loops[k]
            for i in range(len(lp)):
                a_, b_ = lp[i], lp[(i + 1) % len(lp)]
                use2[(a_, b_) if a_ < b_ else (b_, a_)] -= 1
    bad1 = sum(1 for n in use2.values() if n not in (0, 2))
    return pairs, bad0, bad1


def repair_opening_shells(prods):
    """The kernel subtracts IfcOpeningElement bodies with OpenCASCADE booleans, which need 2-manifold closed tools. SDS/2
    exports countersunk / stepped bolt holes as ONE IfcFacetedBrep holding two bodies (cone + cylinder) that touch face
    to face, the shared face given once per body with opposite winding: 16 edges used 4 times. The boolean then returns
    nothing and the whole product was lost (6.1.0-dev3: 28 plates of one model, 1 of another; 6.0.1 the same). Like the
    transcoder's contact-wall repair, both copies of such a face pair are removed from the opening's shell in memory
    (the two bodies become their exact union; no face added, no vertex moved; the source file is not touched), only
    when that makes the shell 2-manifold where it was not. Products' own bodies are not changed here."""
    seen = set()
    undo = []
    n_sh = n_pairs = n_ops = n_err = 0
    for pr in prods:
        for rel in getattr(pr, 'HasOpenings', None) or []:
            n_ops += 1
            try:
                items, _ = body_items(rel.RelatedOpeningElement)
                shells = [sh for it in (items or []) for sh in _opening_shells(it)]
            except Exception:
                n_err += 1
                continue
            for sh in shells:
                if sh is None or sh.id() in seen:
                    continue
                seen.add(sh.id())
                try:
                    pairs, bad0, bad1 = contact_wall_pairs(sh)
                    if pairs and bad1 < bad0:
                        drop = {k for ks in pairs for k in ks}
                        undo.append((sh, list(sh.CfsFaces)))
                        sh.CfsFaces = [fc for k, fc in enumerate(sh.CfsFaces) if k not in drop]
                        n_sh += 1
                        n_pairs += len(pairs)
                except Exception:
                    n_err += 1
    return {'openings': n_ops, 'shells_checked': len(seen), 'shells_repaired': n_sh, 'face_pairs_removed': n_pairs,
            'errors': n_err}, undo


def absurd_part(bp, rec, absurd):
    """a part whose coordinates reach 1e10 mm (10,000 km; e.g. two Tekla 2022 bolt assemblies placed at -1.7e17 mm) is
    left out of the STEP and listed - written, it would make the whole model's bbox absurd"""
    X = bp[0]
    if len(X) and float(np.abs(X).max()) >= ABSURD_MM:
        rec.tags.add('excluded-corrupt-coordinates')
        absurd.append(rec)
        return True
    return False


def inst_key(pr):
    """instancing key of a product: its body is exactly one IfcMappedItem and it has no openings"""
    if getattr(pr, 'HasOpenings', None):
        return None
    items, rid = body_items(pr)
    if not items or len(items) != 1 or not items[0].is_a('IfcMappedItem'):
        return None
    return items[0].MappingSource.id()


def inst_transform(tc, pr, item):
    """rigid placement (R, t mm) of the mapped item's representation map in world, or None (scaled / mirrored /
    placement not evaluable -> the part is written as its own copy)"""
    try:
        P = m44(tc.up.get_local_placement(pr.ObjectPlacement)) if pr.ObjectPlacement is not None else np.eye(4)
        T = m44(tc.up.get_mappeditem_transformation(item))
    except Exception:
        return None
    W = P @ T
    R = W[:3, :3]
    if not np.allclose(R.T @ R, np.eye(3), atol=1e-7) or np.linalg.det(R) < 0.999999 or not np.isfinite(W).all():
        return None
    t = W[:3, 3] * tc.sc
    if np.abs(t).max() >= ABSURD_MM:
        return None
    return R.tolist(), t.tolist()


def gap_of(shells):
    """part-level measure of its open source shells (Shell.gap records) -> dict or None (no open source shell)"""
    gs = [s.gap for s in shells if getattr(s, 'gap', None)]
    if not gs:
        return None
    op = [g for g in gs if 'closed_within_mm' not in g]
    out = {'open_shells': len(op), 'closed_within_tol_shells': len(gs) - len(op),
           'free_edges': sum(g['free_edges'] for g in gs), 'nonmanifold_edges': sum(g['nonmanifold_edges'] for g in gs)}
    vals = [g.get('gap_max_mm') for g in gs]
    out['gap_max_mm'] = None if any(v is None for v in vals) else max(vals)
    if not op:
        out['closed_within_mm'] = GAP_CLOSE_MM
    return out


def sew_of(shells):
    """largest seam-sewing vertex move (mm) over the shells written for a part (and their voids)"""
    m = 0.0
    for s_ in shells:
        m = max(m, getattr(s_, 'sew', 0.0) or 0.0)
        for v in getattr(s_, 'voids', ()):
            m = max(m, getattr(v, 'sew', 0.0) or 0.0)
    return round(m, 4)


def sew_bucket(v):
    for lim, name in ((0.01, '<=0.01'), (0.02, '0.01-0.02'), (0.05, '0.02-0.05'), (0.1, '0.05-0.1')):
        if v <= lim:
            return name
    return '>0.1'


def gap_bucket(g):
    if g is None:
        return 'none'
    v = g.get('gap_max_mm')
    if v is None:
        return 'unmatched'
    for lim, name in ((0.0, '0'), (0.01, '<=0.01'), (0.1, '<=0.1'), (1.0, '<=1'), (10.0, '<=10')):
        if v <= lim:
            return name
    return '>10'


def emit_instance_rec(spool, rec, sh):
    rec.src = sh.src
    rec.gap = sh.gap
    rec.merged = sh.merged
    rec.sew = sh.sew
    rec.tags |= sh.tags
    rec.tags.add('instanced')
    if sh.curved or rec.curved:
        rec.tags.add('approx-curved')
    k, R, t = rec.inst
    rec.frag = spool.emit_instance(rec.name, rec.gid, describe(rec), sh, R, t)
    rec.level = 0
    return rec.frag


def emit_rec(spool, rec, bp, level, surface_all=False, per_solid_ok=None):
    X, solids, surfaces, tags = bp
    if surface_all:
        surfaces = list(surfaces) + solids + [v for s in solids for v in s.voids]
        solids = []
    elif per_solid_ok is not None:
        keep, bad = [], []
        for k, s in enumerate(solids):
            (keep if per_solid_ok.get(k) else bad).append(s)
        surfaces = list(surfaces) + bad + [v for s in bad for v in s.voids]
        solids = keep
    for s in solids:
        if s.voids and not all(v.closed for v in s.voids):
            pass
    # representation tags describe the representation written now (6.1.8: an L1 shell that closes no longer keeps the
    # L0 attempt's open_in_source); a failed attempt restores the previous set
    rec.tags -= KEEP_TAGS
    rec.tags |= {t for t in tags if t in KEEP_TAGS}
    rec.gap = gap_of(list(solids) + list(surfaces))
    rec.merged = 'merged' in tags
    rec.sew = sew_of(list(solids) + list(surfaces))
    fr = spool.emit(rec.name, rec.gid, describe(rec), solids, surfaces, X)
    if fr is not None:
        rec.frag = fr
        rec.level = level
    return fr


def regen(f, recs, src, tc, repair, threads, stats, key, tri=False, mode='poly'):
    """geometry again for a list of parts from a given source -> dict eid -> bp"""
    out = {}
    if src == 'tc':
        for r in recs:
            pr = f.by_id(r.eid)
            items, _ = body_items(pr)
            pieces = tc.product(pr, items) if items else None
            if pieces is None:
                continue
            bp = build_part(pieces, repair, tri=tri)
            if bp is not None and bp != 'corrupt':
                out[r.eid] = bp
    else:
        prods = [f.by_id(r.eid) for r in recs]

        def on_shape(eid, V, faces, iids):
            if eid in CLIP_EXACT:
                V, faces, iids = CLIP_EXACT[eid]
            bp = build_part(kernel_pieces(f, V, faces, iids), repair, tri=tri)
            if bp is not None and bp != 'corrupt':
                out[eid] = bp
        kernel_run_isolated(f, prods, threads, mode, key, stats, on_shape)
    return out


def verify_and_fallback(f, recs, spool, ver, repair, tc, threads, a, stats, vstats):
    t0 = time.time()
    # verify time budget (6.1.7): the per-part read-back of the largest models (1.1-1.2 GB IFC) ran past the worker's
    # 6 h limit, which then restarted the whole conversion on the 0.8.4 kernel. When the budget is used up the read-back
    # stops: parts read back so far keep their verdicts / fallbacks, the rest are written as converted (tag verify_partial,
    # stats verify_partial) and the grader's own read-back (step_verify_big) decides. Default 2 h (V6_VERIFY_BUDGET_S).
    budget = float(os.environ.get('V6_VERIFY_BUDGET_S', '7200') or 0)
    ver.deadline = (t0 + budget) if budget > 0 else None
    # and never past 85% of the job's total wall budget (V6_TOTAL_BUDGET_S, else the fleet worker's IFC_TIMEOUT_S when set),
    # so assembly finishes before the worker's timeout
    tot = float(os.environ.get('V6_TOTAL_BUDGET_S') or os.environ.get('IFC_TIMEOUT_S') or 0)
    if tot > 0:
        cap = T_START[0] + 0.85 * tot
        ver.deadline = cap if ver.deadline is None else min(ver.deadline, cap)
    stats['verify_budget'] = {'budget_s': budget, 'total_budget_s': tot or None,
                              'deadline_in_s': round(ver.deadline - t0, 1) if ver.deadline else None}
    ver.exhausted = False
    res = ver.run([(i, r.frag) for i, r in enumerate(recs)])
    fails = []
    partial = []
    for i, r in enumerate(recs):
        ok, why = judge(res.get(i), r.frag)
        if why == 'budget':
            r.ok = None
            r.tags.add('verify_partial')
            partial.append(r)
            continue
        r.ok = ok
        r.vres = res.get(i)
        if not ok:
            r.why = why
            r.hist.append('L0:%s' % why)
            vstats['L0_fail_' + why] += 1
            fails.append(r)
    stats['verify_L0'] = {'checked': len(recs) - len(partial), 'failed': len(fails), 'reasons': dict(collections.Counter(r.why for r in fails))}
    if partial:
        stats['verify_partial'] = {'parts': len(partial), 'budget_s': budget,
                                   'note': 'verify time budget used up: these parts are written as converted (L0), not read back by the converter'}
    log('verify L0: %d parts, %d failed %s (%.0fs)' % (len(recs), len(fails), stats['verify_L0']['reasons'], time.time() - t0))
    best_bp = {}

    def attempt(cands, level, tag, bps):
        nonlocal fails
        trial = []
        for r in cands:
            bp = bps.get(r.eid)
            if bp is None:
                continue
            old = (r.frag, r.level, set(r.tags), r.gap, r.sew, r.merged)
            if tag:
                r.tags.add(tag)
            else:
                r.tags.discard('instanced')
            fr = emit_rec(spool, r, bp, level)
            if fr is None:
                r.frag, r.level, r.tags, r.gap, r.sew, r.merged = old
                continue
            trial.append((r, old))
        if not trial:
            return
        rr = ver.run([(k, r.frag) for k, (r, _) in enumerate(trial)])
        for k, (r, old) in enumerate(trial):
            ok, why = judge(rr.get(k), r.frag)
            if ok:
                r.ok = True; r.why = None; r.vres = rr.get(k)
            else:
                r.hist.append('L%d:%s' % (level, why))
                r.frag, r.level, r.tags, r.gap, r.sew, r.merged = old
                if why == 'budget':
                    r.tags.add('verify_partial')
        fails = [r for r in fails if not r.ok]

    def left():
        # fallback stages need read-back time: none is started once the verify budget is used up (failing parts then
        # keep their L0 representation, tagged unverified)
        return not getattr(ver, 'exhausted', False) and (ver.deadline is None or time.time() < ver.deadline - 60)

    # L0b: a part placing shared geometry (MAPPED_ITEM) that fails is first written as its own copy in world
    # coordinates - same geometry, same faces, no tag (OCC 8.0.1 BRepCheck can fail a located copy of a solid that is
    # valid in place)
    if fails and left():
        g_inst = [r for r in fails if r.frag is not None and r.frag.needs is not None]
        for src in ('tc', 'kernel'):
            group = [r for r in g_inst if r.src == src]
            if group:
                attempt(group, 0, None, regen(f, group, src, tc, repair, threads, stats, 'kernel_L0b'))
        stats['instances_written_as_copies'] = sum(1 for r in g_inst if r.ok)
    # L0c (6.1.8): a part whose L0 has coplanar triangles merged into polygons (Repair.merge_coplanar) is rebuilt with
    # its faces as they come - the source's own faces, exact, no tag (merged polygons failed OCC's check where the
    # unmerged faces pass, e.g. 700b4c5c / 944bc6d8 plates)
    if fails and left() and repair.merge and os.environ.get('V6_NO_L0C') != '1':
        g_m = [r for r in fails if r.merged and r.frag is not None]
        if g_m:
            repair.merge = False
            try:
                for src in ('tc', 'kernel'):
                    group = [r for r in g_m if r.src == src]
                    if group:
                        attempt(group, 0, None, regen(f, group, src, tc, repair, threads, stats, 'kernel_L0c'))
            finally:
                repair.merge = True
            stats['L0c_unmerged'] = {'tried': len(g_m), 'passed': sum(1 for r in g_m if r.ok)}
    # L1: every face triangulated (same source). 6.1.8: also for open source shells the reader lost (6.1.7 skipped
    # them): the triangulated shell can close where the polygons do not (410b3c2d beam 7071G1: closed after
    # triangulation, no tolerance used)
    if fails and left():
        for src in ('tc', 'kernel'):
            group = [r for r in fails if r.src == src]
            if group:
                attempt(group, 1, 'L1', regen(f, group, src, tc, repair, threads, stats, 'kernel_L1', tri=True))
    # L2: the other source (transcoded -> kernel polyhedral; kernel polyhedral -> kernel triangle mesh)
    if fails and left():
        g_tc = [r for r in fails if r.src == 'tc']
        g_k = [r for r in fails if r.src == 'kernel']
        if g_tc and a.mode != 'transcode':
            # triangle mesh (polyhedral output of odd faceted bodies can run away in ifcopenshell 0.9.0); coplanar
            # triangles are merged back into exact polygons
            attempt(g_tc, 2, 'L2', regen(f, g_tc, 'kernel', tc, repair, threads, stats, 'kernel_L2a', mode='tri'))
        if g_k:
            attempt(g_k, 2, 'L2', regen(f, g_k, 'kernel', tc, repair, threads, stats, 'kernel_L2b', mode='tri'))
    # far from the origin (opt-in, see FAR_MM): the exact L0 solid of a part that failed every in-place level is verified
    # on a copy of its own block translated by whole km; valid there -> kept as the exact L0 solid, tagged far-origin
    if fails and FAR_VERIFY and left():
        far = [r for r in fails if r.frag is not None and r.frag.far is not None and r.level == 0 and r.frag.nsol and r.frag.needs is None]
        if far:
            ver.far_shift = True
            try:
                rr = ver.run([(k, r.frag) for k, r in enumerate(far)])
            finally:
                ver.far_shift = False
            for k, r in enumerate(far):
                ok, why = judge(rr.get(k), r.frag)
                if ok:
                    r.ok = True; r.why = None; r.vres = rr.get(k)
                    r.tags.add('far-origin')
                    r.tags -= {'L1', 'L2', 'L3', 'L4', 'unverified'}
                    r.hist.append('LF:far-origin-valid')
                else:
                    r.hist.append('LF:%s' % why)
            fails = [r for r in fails if not r.ok]
            stats['far_origin_round'] = {'checked': len(far), 'kept_exact': sum(1 for r in far if r.ok)}
    # L3: per solid (valid solids kept, failing solids as open shells); L4: whole part as surface model
    if fails and not a.no_surface_fallback and left():
        bps = {}
        for src in ('tc', 'kernel'):
            group = [r for r in fails if r.src == src]
            if group:
                bps.update(regen(f, group, src, tc, repair, threads, stats, 'kernel_L3'))
        # per-solid verification: each solid as its own pseudo part
        probe = []
        for r in fails:
            bp = bps.get(r.eid)
            if bp is None:
                continue
            X, solids, surfaces, tags = bp
            if len(solids) < 2:
                continue
            for k, s in enumerate(solids):
                fr = spool.emit('%s#%d' % (r.name, k), '%s#%d' % (r.gid, k), 'probe', [s], [], X)
                if fr is not None:
                    probe.append(((r.eid, k), fr))
        okmap = collections.defaultdict(dict)
        if probe:
            pr_ = ver.run(probe)
            for key, fr in probe:
                ok, why = judge(pr_.get(key), fr)
                okmap[key[0]][key[1]] = ok
        l3 = []
        for r in fails:
            m = okmap.get(r.eid)
            if m and any(m.values()):
                l3.append(r)
        if l3:
            trial = []
            for r in l3:
                old = (r.frag, r.level, set(r.tags), r.gap, r.sew, r.merged)
                r.tags.add('L3')
                fr = emit_rec(spool, r, bps[r.eid], 3, per_solid_ok=okmap[r.eid])
                if fr is None:
                    r.frag, r.level, r.tags, r.gap, r.sew, r.merged = old
                    continue
                trial.append((r, old))
            rr = ver.run([(k, r.frag) for k, (r, _) in enumerate(trial)])
            for k, (r, old) in enumerate(trial):
                ok, why = judge(rr.get(k), r.frag)
                if ok:
                    r.ok = True; r.vres = rr.get(k)
                else:
                    r.hist.append('L3:%s' % why)
                    r.frag, r.level, r.tags, r.gap, r.sew, r.merged = old
            fails = [r for r in fails if not r.ok]
        if fails:
            trial = []
            for r in fails:
                bp = bps.get(r.eid)
                if bp is None:
                    continue
                old = (r.frag, r.level, set(r.tags), r.gap, r.sew, r.merged)
                r.tags.add('L4')
                fr = emit_rec(spool, r, bp, 4, surface_all=True)
                if fr is None:
                    r.frag, r.level, r.tags, r.gap, r.sew, r.merged = old
                    continue
                trial.append((r, old))
            rr = ver.run([(k, r.frag) for k, (r, _) in enumerate(trial)])
            for k, (r, old) in enumerate(trial):
                ok, why = judge(rr.get(k), r.frag)
                r.vres = rr.get(k)
                if ok:
                    r.ok = True
                else:
                    r.hist.append('L4:%s' % why)
                    # keep the surface version anyway (no solid claimed); flagged
                    r.tags.add('unverified')
            fails = [r for r in fails if not r.ok]
    # a part whose every representation crashes the STEP reader is left out: written, it could crash the read-back of
    # the whole file (listed; coverage shows it as missing)
    crashers = [r for r in fails if r.hist and (r.hist[-1].endswith('reader_crash') or
                                                all(h.endswith('no_result') for h in r.hist))]
    if getattr(ver, 'exhausted', False):
        stats['verify_budget_exhausted'] = True
    for r in crashers:
        r.frag = None
    stats['dropped_reader_crash'] = [[r.gid, r.cls, r.name, r.hist] for r in crashers[:50]]
    stats['dropped_reader_crash_total'] = len(crashers)
    stats['verify'] = {'rounds': ver.rounds, 'sec': round(ver.sec, 1), 'procs': ver.procs, 'python': ver.py,
                       'reader_crash_chunks': getattr(ver, 'crashes', 0), 'identical_parts_not_reverified': getattr(ver, 'deduped', 0),
                       'far_parts_verified_translated': getattr(ver, 'far_parts', 0),
                       'final_failed': len(fails), 'final_failed_examples': [[r.gid, r.cls, r.name, r.hist] for r in fails[:20]]}
    for r in fails:
        r.tags.add('unverified')


def length_unit_name(f):
    try:
        for u in f.by_type("IfcUnitAssignment")[0].Units:
            if getattr(u, "UnitType", None) == "LENGTHUNIT":
                if u.is_a("IfcSIUnit"):
                    return "SI:%s%s" % (u.Prefix or "", u.Name)
                if u.is_a("IfcConversionBasedUnit"):
                    return "CONV:%s" % u.Name
    except Exception:
        pass
    return "unknown"


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == VERIFY_CODE_MARK:
        sys.exit(verify_worker(sys.argv[2], sys.argv[3]))
    sys.exit(main())
