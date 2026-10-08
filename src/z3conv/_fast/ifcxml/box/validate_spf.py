#!/usr/bin/env python3
"""validate_spf.py - independent checks of an SPF written by ifcxml2spf.py against its ifcXML source.

    validate_spf.py SRC.ifcXML|SRC.ifcZIP OUT.ifc [--report R.json] [--sibling OTHER.ifc] [--no-schema-validate]
                    [--member NAME]

1. the SPF opens in ifcopenshell; instance count and per-type counts (exact type);
2. independent XML census (separate expat pass, no schema): every element carrying an id attribute (excluding the
   uos / ifcXML containers) counted by its tag (or xsi:type) -> must equal the SPF per-type counts of those ids
   (ids are kept: SPF #N = XML iN); plus total instances incl. anonymous nested ones (IFC4 nesting);
3. round trip, instance by instance: for every XML element with id iN the SPF instance #N exists, has the same type,
   and every attribute given in the XML (child element or XML attribute) reads back from ifcopenshell with the same
   value: references by id, strings exactly, reals/integers numerically identical, enumerations, booleans, lists item
   by item (ex:pos order), typed select values (type + wrapped value);
4. ifcopenshell.validate schema check (types, cardinalities, required attributes) - issue counts by kind;
5. unit scale (metres per file length unit), IfcProduct census (with representation, by class);
6. optional: same census on a sibling SPF export of the same model (GlobalId overlap of products).
"""
import sys, os, re, json, time, math, argparse, collections, zipfile, tempfile, logging
import xml.etree.ElementTree as ET

XSI_TYPE = '{http://www.w3.org/2001/XMLSchema-instance}type'


def local(tag):
    return tag.rsplit('}', 1)[-1] if tag[:1] == '{' else tag.rsplit(':', 1)[-1]


def strip_prefix(v):
    return v.rsplit(':', 1)[-1] if v else v


def ref_of(el):
    r = el.get('ref') or el.get('href') or el.get('{http://www.w3.org/1999/xlink}href')
    return r.lstrip('#') if r else None


def pos_of(el):
    for k, v in el.attrib.items():
        if k == 'pos' or k.endswith('}pos'):
            try:
                return int(v)
            except ValueError:
                return None
    return None


IDMAP = {}
RX_NONFIN = re.compile(r'(?i)^\s*[+-]?(?:\d\.?#?)?(?:nan|inf|infinity|ind|qnan|snan)(?:\(.*\))?\s*$')


def nonfinite(t):
    return bool(RX_NONFIN.match(t or ''))


def num(xid):
    if xid in IDMAP:
        return IDMAP[xid]
    t = xid[1:] if xid[:1] in ('i', 'I') else xid
    return int(t) if t.isdigit() else None


def xml_path(src, member, tmpdir):
    with open(src, 'rb') as f:
        h = f.read(4)
    if h == b'PK\x03\x04':
        z = zipfile.ZipFile(src)
        infos = [i for i in z.infolist() if not i.is_dir()]
        cand = [i for i in infos if (member and i.filename == member) or (not member and i.filename.lower().endswith(('.ifcxml', '.xml')))]
        m = max(cand, key=lambda i: i.file_size)
        out = os.path.join(tmpdir, 'member.xml')
        with z.open(m) as a, open(out, 'wb') as b:
            for blk in iter(lambda: a.read(1 << 24), b''):
                b.write(blk)
        return out
    return src


class RT:
    """round-trip comparison of XML values against ifcopenshell values"""

    def __init__(self, f):
        self.f = f
        import ifcopenshell.ifcopenshell_wrapper as W
        S = W.schema_by_name(f.schema)
        self.entities = {d.name().lower() for d in S.declarations() if d.as_entity() is not None}
        self.is_entity = lambda t: t.lower() in self.entities
        self.c = collections.Counter()
        self.bad = collections.Counter()
        self.samples = []
        self.decl_names = None
        self._inv = {}
        self.S = S
        self.dangling = []

    def defined(self, r):
        n = num(r)
        if n is None:
            return False
        try:
            self.f.by_id(n)
            return True
        except RuntimeError:
            return False

    def inverse_names(self, e):
        t = e.is_a()
        r = self._inv.get(t)
        if r is None:
            r = self._inv[t] = {x.name() for x in self.S.declaration_by_name(t).all_inverse_attributes()}
        return r

    def fail(self, kind, msg):
        self.bad[kind] += 1
        if len(self.samples) < 40:
            self.samples.append('%s: %s' % (kind, msg))

    def cmp_text(self, text, v, where):
        """scalar compare: XML text vs python value from ifcopenshell"""
        t = (text or '')
        if isinstance(v, bool):
            ok = t.strip().lower() in (('true', '1') if v else ('false', '0'))
        elif isinstance(v, int):
            try:
                ok = int(float(t.strip())) == v
            except ValueError:
                ok = False
        elif isinstance(v, float):
            s = t.strip().replace(',', '.') if re.match(r'^\s*[+-]?\d+,\d+', t) else t.strip()
            try:
                x = float(s)
                ok = (x == v) or (math.isnan(x) and v is None)
            except ValueError:
                ok = False
        elif isinstance(v, str):
            if v.isupper() and t.strip().upper() == v and t.strip() != v:   # enumeration value
                ok = True
            else:
                ok = (t == v) or (t.strip().upper().strip('.') == v)            # string / enumeration / logical
                if not ok and v in ('UNKNOWN',) and t.strip().lower() == 'unknown':
                    ok = True
        elif v is None:
            ok = nonfinite(t)                       # non-finite reals are written as $ (listed in the converter report)
        else:
            ok = False
        self.c['scalar_compared'] += 1
        if not ok:
            self.fail('scalar_mismatch', '%s xml=%r spf=%r' % (where, t[:60], v if not isinstance(v, str) else v[:60]))

    def cmp_el(self, el, v, where, item=False):
        """compare the XML element el (attribute element or aggregate item element) with ifcopenshell value v"""
        import ifcopenshell
        r = ref_of(el)
        kids = list(el)
        if r is not None:
            self.c['refs_compared'] += 1
            if isinstance(v, tuple) and len(v) == 1:
                v = v[0]
            if not isinstance(v, ifcopenshell.entity_instance) or num(r) != v.id():
                self.fail('ref_mismatch', '%s xml ref=%s spf=%s' % (where, r, v))
            return
        if isinstance(v, ifcopenshell.entity_instance) and v.id() == 0:
            # typed select value IFCX(v)
            tag = strip_prefix(el.get(XSI_TYPE)) or local(el.tag)
            if not item and len(kids) == 1 and not strip_prefix(el.get(XSI_TYPE)):
                el = kids[0]
                tag = local(el.tag)
                kids = list(el)
            tag = tag[:-8] if tag.endswith('-wrapper') else tag
            self.c['typed_compared'] += 1
            if tag.lower() != v.is_a().lower():
                self.fail('typed_type_mismatch', '%s xml=%s spf=%s' % (where, tag, v.is_a()))
                return
            wv = v.wrappedValue
            if isinstance(wv, tuple):
                return self.cmp_list(el, wv, where)
            return self.cmp_text(el.text, wv, where)
        own_content = bool(strip_prefix(el.get(XSI_TYPE))) or any(a[:1].isupper() for a in el.attrib if a[:1] != '{')
        if not item and len(kids) == 1 and ref_of(kids[0]) is not None and not own_content and not isinstance(v, tuple) \
                and self.is_entity(local(kids[0].tag)):
            # (the child's TAG names an entity: IFC2x3 value element. An IFC4 child named after an attribute, e.g.
            # <Position><Location href="i3"/></Position>, is an attribute of the anonymous instance Position instead)
            # IFC2x3: single reference wrapped in the attribute element <Attr><IfcX ref="i5" xsi:nil="true"/></Attr>
            c = kids[0]
            rr = ref_of(c)
            ctag = strip_prefix(c.get(XSI_TYPE)) or local(c.tag)
            self.c['refs_compared'] += 1
            self.c['wrapped_single_refs_compared'] += 1
            if not isinstance(v, ifcopenshell.entity_instance) or num(rr) != v.id():
                self.fail('ref_mismatch', '%s xml ref=%s spf=%s' % (where, rr, v))
            elif self.is_entity(ctag) and not v.is_a(ctag):
                self.fail('ref_type_mismatch', '%s xml <%s ref=%s> spf=%s' % (where, ctag, rr, v.is_a()))
            return
        if isinstance(v, ifcopenshell.entity_instance):
            # inline instance: the attribute element holds <IfcX id=..>..</IfcX> (IFC2x3) or is the instance (IFC4)
            if not item and len(kids) == 1 and not own_content and ref_of(kids[0]) is None and self.is_entity(local(kids[0].tag)):
                el = kids[0]
            xid = el.get('id')
            tag = strip_prefix(el.get(XSI_TYPE)) or local(el.tag)
            self.c['inline_compared'] += 1
            if xid is not None and num(xid) is not None and num(xid) != v.id():
                self.fail('inline_id_mismatch', '%s xml id=%s spf #%d' % (where, xid, v.id()))
            if tag.lower().startswith('ifc') and not v.is_a(tag):
                self.fail('inline_type_mismatch', '%s xml=%s spf=%s' % (where, tag, v.is_a()))
                return
            if xid is None and self.decl_names is not None:
                # anonymous nested instance (IFC4 ifcXML): no id of its own, so it is compared here, attribute by attribute
                self.c['anonymous_instances_compared'] += 1
                self.compare_attrs(el, v, '%s>%s' % (where, v.is_a()))
            return
        if isinstance(v, tuple):
            xt = strip_prefix(el.get(XSI_TYPE))
            if not item and (el.get('id') is not None or (xt and self.is_entity(xt))):
                # single instance written on the aggregate attribute element itself (<RelatedObjects xsi:type="IfcSite"
                # id="s1" ...>): that element is the one item
                self.c['single_item_on_attribute_element'] += 1
                if len(v) != 1:
                    self.fail('list_len_mismatch', '%s xml=1 (on attribute element) spf=%d' % (where, len(v)))
                    return
                return self.cmp_el(el, v[0], where, item=True)
            return self.cmp_list(el, v, where)
        if not kids:
            return self.cmp_text(el.text, v, where)
        if len(kids) == 1:          # select of a defined type read back as a plain value, or a wrapped simple value
            return self.cmp_el(kids[0], v, where, item=True)
        self.fail('shape_mismatch', '%s xml has %d children, spf=%r' % (where, len(kids), v))

    def cmp_list(self, el, v, where):
        kids = list(el)
        if not kids:
            toks = (el.text or '').split()
            if v and isinstance(v[0], tuple):           # nested list in one text
                flat = [x for row in v for x in row]
            else:
                flat = list(v)
            if len(toks) != len(flat):
                self.fail('list_len_mismatch', '%s xml=%d spf=%d' % (where, len(toks), len(flat)))
                return
            for t, x in zip(toks, flat):
                self.cmp_text(t, x, where)
            return
        ps = [pos_of(c) for c in kids]
        if all(p is not None for p in ps):
            kids = [c for _, c in sorted(zip(ps, kids), key=lambda x: x[0])]
        if len(kids) == 1 and len(v) != 1 and not ref_of(kids[0]) and kids[0].get('id') is None and list(kids[0]):
            kids = list(kids[0])
        if len(kids) != len(v):
            self.fail('list_len_mismatch', '%s xml=%d spf=%d' % (where, len(kids), len(v)))
            return
        self.c['lists_compared'] += 1
        for c, x in zip(kids, v):
            self.cmp_el(c, x, where, item=True)

    def instance(self, el, decl_names=None):
        xid = el.get('id')
        n = num(xid) if xid else None
        if n is None:
            return
        try:
            e = self.f.by_id(n)
        except RuntimeError:
            self.fail('missing_instance', 'xml id %s' % xid)
            return
        tag = strip_prefix(el.get(XSI_TYPE)) or local(el.tag)
        self.c['instances_compared'] += 1
        if not self.is_entity(tag):
            # IFC4 ifcXML: the attribute element (<OwnerHistory id=..>) is the instance, its type is the attribute's
            # declared type - checked by ifcopenshell.validate; here: it exists and its attributes read back
            self.c['instances_via_attribute_element'] += 1
        elif e.is_a().lower() != tag.lower():
            self.fail('type_mismatch', 'id %s xml=%s spf=%s' % (xid, tag, e.is_a()))
            return
        self.compare_attrs(el, e, xid)

    def compare_attrs(self, el, e, xid):
        names = self.decl_names(e)
        inv = self.inverse_names(e)
        for a, val in el.attrib.items():
            if a[:1] == '{' or not a[:1].isupper():
                continue
            if a not in names:
                continue
            self.c['attributes_compared'] += 1
            v = getattr(e, a)
            if v is None and not val.strip():
                self.c['empty_value_unset_compared'] += 1          # X="" for an optional list: written as $
                continue
            if v is None and nonfinite(val):
                self.c['nonfinite_compared'] += 1
                continue
            if isinstance(v, tuple):
                fake = ET.Element('x')
                fake.text = val
                self.cmp_list(fake, v, '%s.%s' % (xid, a))
            else:
                self.cmp_text(val, v, '%s.%s' % (xid, a))
        for ch in el:
            a = local(ch.tag)
            if a not in names:
                if a in inv and ch.get('id') is None and ref_of(ch) is None:
                    self.c['inverse_nested_elements_not_compared_here'] += 1
                continue
            self.c['attributes_compared'] += 1
            try:
                v = getattr(e, a)
            except Exception as ex:
                self.fail('getattr_error', '%s.%s %s' % (xid, a, ex))
                continue
            if v is None:
                if ref_of(ch) is None and not list(ch) and ch.get('{http://www.w3.org/2001/XMLSchema-instance}nil') == 'true':
                    continue
                if nonfinite(ch.text):
                    self.c['nonfinite_compared'] += 1
                    continue
                if not list(ch) and not (ch.text or '').strip() and ref_of(ch) is None:
                    self.c['empty_value_unset_compared'] += 1      # <X/> for an optional list: written as $
                    continue
                refs = [ref_of(x) for x in ch.iter() if ref_of(x) is not None]
                if refs and all(not self.defined(r) for r in refs):
                    self.c['dangling_reference_in_source'] += 1     # the XML references an id it never defines
                    if len(self.dangling) < 20:
                        self.dangling.append('%s.%s -> %s' % (xid, a, refs[:3]))
                    continue
                self.fail('value_missing', '%s.%s xml=%r' % (xid, a, (ch.text or '')[:40]))
                continue
            self.cmp_el(ch, v, '%s.%s' % (xid, a))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('spf')
    ap.add_argument('--report')
    ap.add_argument('--sibling')
    ap.add_argument('--member')
    ap.add_argument('--conv-report', help='ifcxml2spf report of this conversion (per-type counts cross-checked)')
    ap.add_argument('--no-schema-validate', action='store_true')
    ap.add_argument('--validate-max', type=int, default=400000, help='skip ifcopenshell.validate above this many instances')
    a = ap.parse_args()
    if a.conv_report:
        IDMAP.update((json.load(open(a.conv_report)).get('idmap') or {}))
    import ifcopenshell, ifcopenshell.util.unit
    t0 = time.time()
    rep = {'src': a.src, 'spf': a.spf}
    f = ifcopenshell.open(a.spf)
    rep['open_sec'] = round(time.time() - t0, 2)
    rep['schema'] = f.schema
    cnt = collections.Counter(e.is_a() for e in f)
    rep['spf_instances'] = sum(cnt.values())
    tmp = tempfile.mkdtemp(prefix='valspf_', dir=os.path.dirname(os.path.abspath(a.spf)))
    xp = xml_path(a.src, a.member, tmp)
    # ---- 2+3: independent XML census + round trip (one expat pass)
    xml_ids = collections.Counter()
    xml_elems = 0
    rt = RT(f)
    S = ifcopenshell.ifcopenshell_wrapper.schema_by_name(f.schema)
    names_cache = {}

    def decl_names(e):
        t = e.is_a()
        r = names_cache.get(t)
        if r is None:
            d = S.declaration_by_name(t)
            r = names_cache[t] = {x.name() for x in d.all_attributes()}
        return r
    rt.decl_names = decl_names
    depth = 0
    stack = []
    xml_inst_elems = 0
    ents_l = {d.name().lower(): d.as_entity() for d in S.declarations() if d.as_entity() is not None}
    CONTAINERS = ('uos', 'ifcXML', 'iso_10303_28', 'iso_10303_28_header', 'header', 'express', 'schema_population')
    REF = 'REF'                                        # marker: element is a reference (or inside one): no instance
    akind = {}

    def attr_kind(t, nm):
        """explicit attribute nm of entity t with an entity type -> that entity; inverse attribute nm -> its entity"""
        key = (t.name(), nm)
        if key not in akind:
            r = None
            for at in t.all_attributes():
                if at.name() == nm:
                    nt = at.type_of_attribute().as_named_type()
                    if nt is not None and nt.declared_type().as_entity() is not None:
                        r = nt.declared_type().as_entity()
                    break
            else:
                for iv in t.all_inverse_attributes():
                    if iv.name() == nm:
                        r = iv.entity_reference()
                        break
            akind[key] = r
        return akind[key]

    def ptype(el, parent_t):
        """independent of the converter: the entity an XML element would carry (from its xsi:type, its tag, or the
        entity-typed explicit / inverse attribute of the enclosing instance it is named after); None for references"""
        nm = local(el.tag)
        if parent_t is REF or ref_of(el) is not None:
            return REF
        if nm in CONTAINERS:
            return None
        xt = strip_prefix(el.get(XSI_TYPE))
        if xt:
            d = ents_l.get((xt[:-8] if xt.endswith('-wrapper') else xt).lower())
            if d is not None:
                return d
        d = ents_l.get(nm.lower())
        if d is not None:
            return d
        return attr_kind(parent_t, nm) if parent_t is not None else None

    def is_instance(el, nm, pt):
        if pt is REF or pt is None:
            return False
        return _is_instance(el, nm, pt)

    def _is_instance(el, nm, pt):
        """an element denotes an instance if it carries an id, or names an entity by tag / xsi:type, or it is an
        entity-typed attribute (or inverse) element that holds instance content itself (uppercase XML attributes or
        attribute child elements) - IFC4 ifcXML writes the instance on the attribute element"""
        if nm in CONTAINERS:
            return False
        if el.get('id') is not None:
            return True
        if pt is None:
            return False
        xt = strip_prefix(el.get(XSI_TYPE))
        if ents_l.get(nm.lower()) is not None or (xt and ents_l.get(xt.lower()) is not None):
            return True
        return any(a[:1].isupper() for a in el.attrib if a[:1] != '{') or \
            any(local(c.tag)[:1].isupper() and local(c.tag).lower() not in ents_l for c in el)
    tstack = []
    xml_ids_not_instance = collections.Counter()
    t1 = time.time()
    for ev, el in ET.iterparse(xp, events=('start', 'end')):
        if ev == 'start':
            depth += 1
            stack.append(el)
            tstack.append(ptype(el, tstack[-1] if tstack else None))
            continue
        depth -= 1
        stack.pop()
        pt = tstack.pop()
        xml_elems += 1
        nm = local(el.tag)
        inst = is_instance(el, nm, pt)
        if inst:
            xml_inst_elems += 1
        elif el.get('id') is not None and nm not in CONTAINERS:
            xml_ids_not_instance[nm] += 1
        if inst and el.get('id') is not None:
            t = strip_prefix(el.get(XSI_TYPE)) or nm
            if not rt.is_entity(t):
                n_ = num(el.get('id'))
                try:
                    t = f.by_id(n_).is_a() if n_ is not None else t
                except RuntimeError:
                    pass
            xml_ids[t] += 1
            rt.instance(el, decl_names)
        if stack and (depth == 1 or (depth == 2 and local(stack[-1].tag) == 'uos')):
            # top-level element done: free memory (round trip already compared nested elements on their own end)
            stack[-1].remove(el)
    rep['roundtrip_sec'] = round(time.time() - t1, 2)
    for fn in os.listdir(tmp):
        os.remove(os.path.join(tmp, fn))
    os.rmdir(tmp)
    # SPF per-type counts restricted to instances that carry an XML id are what xml_ids counts; anonymous nested
    # instances (IFC4) exist only in the SPF
    lower_cnt = collections.Counter({k.lower(): v for k, v in cnt.items()})
    diff = {}
    for t, n in xml_ids.items():
        if lower_cnt.get(t.lower(), 0) < n:
            diff[t] = {'xml_with_id': n, 'spf': lower_cnt.get(t.lower(), 0)}
    rep['xml_elements'] = xml_elems
    rep['xml_instance_elements'] = xml_inst_elems
    rep['xml_id_elements_not_instances'] = dict(xml_ids_not_instance)
    rep['instance_count_equal'] = xml_inst_elems == rep['spf_instances']
    gids = collections.Counter(e.GlobalId for e in f.by_type('IfcRoot') if e.GlobalId is not None)
    dup = {g: n for g, n in gids.items() if n > 1}
    rep['globalid_unset'] = sum(1 for e in f.by_type('IfcRoot') if e.GlobalId is None)
    rep['duplicate_globalids'] = {'globalids': len(dup), 'instances': sum(dup.values()),
                                  'by_class': dict(collections.Counter(e.is_a() for e in f.by_type('IfcRoot') if e.GlobalId in dup)),
                                  'sample': sorted(dup)[:5]}
    rep['xml_instances_with_id'] = sum(xml_ids.values())
    rep['xml_types_with_id'] = len(xml_ids)
    rep['spf_types'] = len(cnt)
    rep['spf_minus_xml_with_id'] = rep['spf_instances'] - rep['xml_instances_with_id']
    rep['count_mismatch_types'] = diff
    rep['per_type_equal'] = (not diff) and all(lower_cnt.get(t.lower(), 0) == n for t, n in xml_ids.items()) and \
        rep['spf_instances'] == rep['xml_instances_with_id']
    rep['per_type_covered'] = not diff          # every XML instance with an id is in the SPF with its type
    if a.conv_report:
        cr = json.load(open(a.conv_report))
        rep['converter_instances'] = cr.get('instances')
        rep['converter_instances_by_type_equal_spf'] = cr.get('instances_by_type') == dict(cnt)
        rep['anonymous_nested_instances'] = rep['spf_instances'] - rep['xml_instances_with_id']
    rep['roundtrip'] = {'counts': dict(rt.c), 'failures': dict(rt.bad), 'samples': rt.samples,
                        'dangling_references_in_source': rt.dangling}
    # ---- 4: schema validation
    if not a.no_schema_validate and rep['spf_instances'] <= a.validate_max:
        import ifcopenshell.validate
        t2 = time.time()
        log = ifcopenshell.validate.json_logger()
        try:
            ifcopenshell.validate.validate(f, log, express_rules=False)
            kinds = collections.Counter()
            samp = []
            for s in log.statements:
                m = str(s.get('message', ''))
                one = m.replace('\n', ' ')
                mr = re.search(r'Rule (\S+)', one)
                key = mr.group(1) if mr else (str(s.get('attribute') or '') + ' ' + one[:80]).strip()
                key = (str(s.get('type', '')) + ' ' + key).strip()[:120]
                kinds[key] += 1
                if len(samp) < 12:
                    samp.append(m[:300])
            rep['schema_validate'] = {'issues': len(log.statements), 'by_kind': dict(kinds.most_common(25)), 'samples': samp,
                                      'sec': round(time.time() - t2, 1)}
        except Exception as e:
            rep['schema_validate'] = {'error': '%s: %s' % (type(e).__name__, str(e)[:300])}
    else:
        rep['schema_validate'] = {'skipped': True}
    # ---- 5: units + products
    try:
        rep['unit_scale_m'] = ifcopenshell.util.unit.calculate_unit_scale(f)
    except Exception as e:
        rep['unit_scale_m'] = 'error %s' % e

    def products(ff):
        pc = collections.Counter()
        gids = set()
        n_rep = 0
        for p in ff.by_type('IfcProduct'):
            if p.Representation is not None:
                n_rep += 1
                pc[p.is_a()] += 1
            gids.add(p.GlobalId)
        return n_rep, pc, gids
    n_rep, pc, gids = products(f)
    rep['products'] = len(f.by_type('IfcProduct'))
    rep['products_with_representation'] = n_rep
    rep['products_with_representation_by_class'] = dict(pc.most_common())
    if a.sibling:
        g = ifcopenshell.open(a.sibling)
        n2, pc2, gids2 = products(g)
        cnt2 = collections.Counter(e.is_a() for e in g)
        rep['sibling'] = {'path': a.sibling, 'schema': g.schema, 'instances': sum(cnt2.values()), 'products': len(g.by_type('IfcProduct')),
                          'products_with_representation': n2, 'by_class': dict(pc2.most_common()),
                          'product_globalids_common': len(gids & gids2), 'only_xml': len(gids - gids2), 'only_sibling': len(gids2 - gids),
                          'type_count_diffs': {t: [cnt.get(t, 0), cnt2.get(t, 0)] for t in sorted(set(cnt) | set(cnt2)) if cnt.get(t, 0) != cnt2.get(t, 0)}}
    rep['sec'] = round(time.time() - t0, 1)
    ok = rep['per_type_covered'] and rep['instance_count_equal'] and not rt.bad and \
        (not a.conv_report or rep.get('converter_instances_by_type_equal_spf'))
    rep['verdict'] = 'pass' if ok else 'fail'
    s = json.dumps(rep, indent=1, default=str)
    if a.report:
        open(a.report, 'w').write(s)
    print(json.dumps({k: rep[k] for k in ('verdict', 'spf_instances', 'xml_instances_with_id', 'xml_instance_elements',
                                          'instance_count_equal', 'per_type_equal', 'per_type_covered', 'duplicate_globalids',
                                          'converter_instances_by_type_equal_spf', 'roundtrip',
                                          'products_with_representation', 'unit_scale_m') if k in rep}, default=str)[:3000])
    if isinstance(rep.get('schema_validate'), dict):
        print(json.dumps(rep['schema_validate'], default=str)[:1500])


if __name__ == '__main__':
    main()
