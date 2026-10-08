#!/usr/bin/env python3
"""ifcxml2spf.py - ifcXML (ISO 10303-28) / .ifcZIP holding ifcXML  ->  IFC STEP-21 physical file (SPF).

    ifcxml2spf.py IN OUT.ifc [--report OUT.json] [--schema IFC2X3|IFC4|IFC4X3_ADD2] [--member NAME]
                             [--nonfinite null|fail] [--keep-ids|--renumber]

IN may be  .ifcXML / .xml (plain or gzip), or .ifcZIP / .zip whose member is ifcXML (largest .ifcxml/.xml member, or
--member). Nothing is invented: every SPF instance and every attribute value comes from one XML instance / value;
attributes absent from the XML are written as $ (unset), derived attributes as *.

Supported encodings (both read by the same schema-driven decoder, attribute order / types from ifcopenshell's EXPRESS
schema wrapper):
  * IFC2x3 ifcXML, ISO 10303-28 ed.2 configuration 'i-ifc2x3' (root iso_10303_28 / uos; EDM 'exp:' and Tekla 'ex:'
    flavours): one element per instance <IfcX id="i1">, attribute elements <Name>..</Name>, entity values as
    <Attr><IfcY ref="i2" xsi:nil="true"/></Attr> or nested <Attr><IfcY id=..>..</IfcY></Attr>, aggregates with
    ex:cType / ex:pos items, select values as <IfcLabel>..</IfcLabel> or <IfcLabel-wrapper>, simple-type list items
    as <ex:double-wrapper> etc.
  * IFC4 / IFC4X3 ifcXML (root ifcXML, header element): simple attribute values as XML attributes (lists space
    separated), entity values as attribute elements carrying the instance itself (xsi:type for subtypes) or
    href/ref references, select values as <IfcX-wrapper>, nested aggregates, and instances nested under INVERSE
    attributes (e.g. IsDecomposedBy/IfcRelAggregates): the forward attribute of the nested instance (RelatingObject,
    RelatedObjects ...) is set to / extended with the enclosing instance, as ISO 10303-28 prescribes.
Ids: when every XML id is i<digits> (all exporters seen) the SPF instance number is that number (#1538 = i1538), so
XML and SPF can be compared instance by instance; anonymous nested instances get numbers above the largest id.

Output: SPF with FILE_SCHEMA from the ifcXML namespace / configuration (IFC2X3, IFC4, IFC4X3_ADD2); HEADER fields from
the ISO 10303-28 header. A JSON report (per-type instance counts, references, dangling references, unknown XML
names, value normalisations) goes to --report and stdout.
Exit codes: 0 converted, 2 input is not ifcXML (e.g. Tekla 'NewDataSet' level XML), 3 XML parse error,
4 converted but with dangling references, 5 unsupported schema.
"""
import sys, os, re, io, json, time, gzip, zipfile, mmap, hashlib, tempfile, argparse, collections
import xml.etree.ElementTree as ET

VERSION = 'ifcxml2spf 1.1.1'
XSI = '{http://www.w3.org/2001/XMLSchema-instance}'
XSI_TYPE = XSI + 'type'
XSI_NIL = XSI + 'nil'
SIMPLE_WRAPPERS = {  # ISO 10303-28 simple-type wrappers (aggregate items of simple types)
    'double-wrapper', 'long-wrapper', 'string-wrapper', 'boolean-wrapper', 'logical-wrapper', 'hexBinary-wrapper',
    'decimal-wrapper', 'integer-wrapper', 'float-wrapper', 'base64Binary-wrapper', 'number-wrapper', 'real-wrapper'}


def local(tag):
    return tag.rsplit('}', 1)[-1] if tag[:1] == '{' else tag.rsplit(':', 1)[-1]


def strip_prefix(v):
    return v.rsplit(':', 1)[-1] if v else v


def ref_of(el):
    r = el.get('ref')
    if r is None:
        r = el.get('href')
    if r is None:
        r = el.get('{http://www.w3.org/1999/xlink}href')
    if r is not None:
        r = r.strip()
        if r[:1] == '#':
            r = r[1:]
    return r


def pos_of(el):
    for k, v in el.attrib.items():
        if k == 'pos' or k.endswith('}pos'):
            try:
                return int(v)
            except ValueError:
                return None
    return None


# ------------------------------------------------------------------------------------------------ value lexing
_RE_REAL = re.compile(r'([+-]?)(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$')
_RE_INT = re.compile(r'[+-]?\d+$')
_RE_COMMA = re.compile(r'[+-]?\d+,\d+(?:[eE][+-]?\d+)?$')
_RE_NONFIN = re.compile(r'(?i)[+-]?(?:\d\.?#?)?(?:nan|inf|infinity|ind|qnan|snan)(?:\(.*\))?$')
NONFINITE = {'nan', '-nan', '+nan', 'inf', '-inf', '+inf', 'infinity', '-infinity', '+infinity', '1.#inf', '-1.#inf',
             '-1.#ind', '1.#ind', '1.#qnan', '-1.#qnan', '1.#snan', '-1.#snan'}


class ValueError_(Exception):
    pass


def spf_string(s):
    """ISO 10303-21 string literal: ' doubled, \\ doubled, printable ASCII as is, everything else \\X2\\..\\X0\\
    (UTF-16 code units, consecutive characters in one run) or \\X4\\ for characters beyond the BMP."""
    out = ["'"]
    run = []

    def flush():
        if run:
            if any(c > 0xFFFF for c in run):
                out.append('\\X4\\' + ''.join('%08X' % c for c in run) + '\\X0\\')
            else:
                out.append('\\X2\\' + ''.join('%04X' % c for c in run) + '\\X0\\')
            run.clear()
    for ch in s:
        o = ord(ch)
        if 32 <= o < 127:
            flush()
            if ch == "'":
                out.append("''")
            elif ch == '\\':
                out.append('\\\\')
            else:
                out.append(ch)
        else:
            if run and ((o > 0xFFFF) != (run[-1] > 0xFFFF)):
                flush()
            run.append(o)
    flush()
    out.append("'")
    return ''.join(out)


# ------------------------------------------------------------------------------------------------ schema access
class Schema:
    def __init__(self, name):
        import ifcopenshell.ifcopenshell_wrapper as W
        self.W = W
        self.name = name
        self.S = W.schema_by_name(name)
        self.by_lower = {d.name().lower(): d for d in self.S.declarations()}
        self._ent = {}
        self._kind = {}

    def decl(self, name):
        return self.by_lower.get(name.lower()) if name else None

    def entity_decl(self, name):
        d = self.decl(name)
        if d is not None and d.as_entity() is not None:
            return d.as_entity()
        return None

    def ent(self, e):
        """per entity: (name_uc, attrs[(name, type, optional)], derived flags, name->index, inverse name->inverse)"""
        key = e.name()
        r = self._ent.get(key)
        if r is None:
            attrs = [(a.name(), a.type_of_attribute(), a.optional()) for a in e.all_attributes()]
            der = list(e.derived())
            idx = {a[0]: i for i, a in enumerate(attrs)}
            idx_l = {a[0].lower(): i for i, a in enumerate(attrs)}
            inv = {i.name(): i for i in e.all_inverse_attributes()}
            inv_l = {k.lower(): v for k, v in inv.items()}
            kinds = [self.kind(a[1]) for a in attrs]
            r = (e.name().upper(), attrs, der, idx, idx_l, inv, inv_l, e.is_abstract(), kinds)
            self._ent[key] = r
        return r

    def kind(self, t):
        """parameter type -> ('entity', decl) | ('select', decl) | ('enum', decl, items_upper) | ('simple', name)
        | ('agg', aggregation_type, elem_type); defined types are resolved to their underlying type."""
        key = str(t)
        r = self._kind.get(key)
        if r is not None:
            return r
        r = self._resolve(t)
        self._kind[key] = r
        return r

    def _resolve(self, t):
        nt = t.as_named_type()
        if nt is not None:
            return self.kind_of_decl(nt.declared_type())
        st = t.as_simple_type()
        if st is not None:
            return ('simple', st.declared_type())
        at = t.as_aggregation_type()
        if at is not None:
            return ('agg', at, at.type_of_element(), self.kind(at.type_of_element()))
        raise ValueError_('unknown parameter type %s' % t)

    def kind_of_decl(self, d):
        if d.as_entity() is not None:
            return ('entity', d.as_entity())
        if d.as_select_type() is not None:
            return ('select', d)
        if d.as_enumeration_type() is not None:
            items = tuple(d.as_enumeration_type().enumeration_items())
            return ('enum', d, {x.upper(): x.upper() for x in items})
        if d.as_type_declaration() is not None:
            return self.kind(d.as_type_declaration().declared_type())
        raise ValueError_('unknown declaration %s' % d)

    def select_contains(self, sel, d):
        """is declaration d (entity/type/enum) a member of select sel (nested selects flattened, subtypes allowed)?"""
        names = self._select_members(sel)
        n = d.name()
        if n in names:
            return True
        e = d.as_entity() if hasattr(d, 'as_entity') else None
        while e is not None:
            if e.name() in names:
                return True
            e = e.supertype()
        return False

    def _select_members(self, sel):
        key = 'sel:' + sel.name()
        r = self._kind.get(key)
        if r is None:
            r = set()
            stack = [sel]
            while stack:
                s = stack.pop()
                for m in s.as_select_type().select_list():
                    if m.as_select_type() is not None:
                        stack.append(m)
                    else:
                        r.add(m.name())
            self._kind[key] = r
        return r


# ------------------------------------------------------------------------------------------------ format detection
def classify_schema(s):
    s = (s or '').lower()
    if 'ifc4x3' in s or 'ifc4_3' in s:
        return 'IFC4X3_ADD2'
    if re.search(r'ifc4(?!\d)', s) and 'ifc2x' not in s:
        return 'IFC4'
    if 'ifc2x3' in s:
        return 'IFC2X3'
    if 'ifc2x2' in s:
        return 'IFC2X2'
    return None


def decode_head(head):
    """first bytes of an XML file -> text (UTF-8 with/without BOM, UTF-16 LE/BE with or without BOM)"""
    if head[:2] in (b'\xff\xfe', b'\xfe\xff'):
        return head.decode('utf-16', 'replace')
    if head[:3] == b'\xef\xbb\xbf':
        head = head[3:]
    if b'\x00' in head[:200]:
        return head.decode('utf-16-le' if head[1:2] == b'\x00' else 'utf-16-be', 'replace')
    return head.decode('utf-8', 'replace')


def detect(head):
    """-> (container, schema or None, root); container 'p28' (iso_10303_28 / uos) or 'ifcxml' (IFC4 root);
    container None if this is not ifcXML. Schema from the uos configuration, then the IFC namespaces."""
    h = decode_head(head)
    body = re.sub(r'<\?.*?\?>|<!--.*?-->|<!DOCTYPE[^>]*>', '', h, flags=re.S)
    m = re.search(r'<([A-Za-z_][\w.\-]*:)?([A-Za-z_][\w.\-]*)[\s>/]', body)
    root = m.group(2) if m else None
    cand = re.findall(r'configuration\s*=\s*"([^"]*)"', h)
    cand += [n for n in re.findall(r'xmlns(?::[\w.\-]+)?\s*=\s*"([^"]*)"', h) if 'ifc' in n.lower()]
    cand += re.findall(r'schemaLocation\s*=\s*"([^"]*)"', h)
    schema = None
    for c in cand:
        schema = classify_schema(c)
        if schema:
            break
    if root == 'iso_10303_28' or root == 'uos':
        return 'p28', schema, root
    if root and root.lower() == 'ifcxml':
        return 'ifcxml', schema or 'IFC4', root
    return None, schema, root


# ------------------------------------------------------------------------------------------------ converter
class Converter:
    def __init__(self, schema, out, ids_numeric, next_free, nonfinite='null'):
        self.sc = schema
        self.out = out
        self.buf = []
        self.buflen = 0
        self.ids_numeric = ids_numeric
        self.idmap = {}
        self.next = next_free
        self.first_free = next_free
        self.nonfinite = nonfinite
        self.defined = set()          # SPF ids written
        self.referenced = set()       # SPF ids referenced
        self.defined_xml = {}         # (only when not numeric) xml id -> spf id handled by idmap
        self.by_type = collections.Counter()
        self.c = collections.Counter()
        self.unknown = collections.Counter()
        self.notes = collections.defaultdict(list)

    # ---- ids
    def sid(self, xid):
        if xid is None:
            n = self.next
            self.next += 1
            return n
        if self.ids_numeric:
            t = xid[1:] if xid[:1] in ('i', 'I') else xid
            if t.isdigit() and int(t) < self.first_free:
                return int(t)
        n = self.idmap.get(xid)
        if n is None:
            n = self.next
            self.next += 1
            self.idmap[xid] = n
        return n

    def ref(self, xid):
        n = self.sid(xid)
        self.referenced.add(n)
        self.c['references'] += 1
        return '#%d' % n

    def note(self, key, msg):
        self.c[key] += 1
        if len(self.notes[key]) < 5:
            self.notes[key].append(msg)

    def w(self, s):
        self.buf.append(s)
        self.buflen += len(s)
        if self.buflen > (4 << 20):
            self.flush()

    def flush(self):
        if self.buf:
            self.out.write(''.join(self.buf))
            self.buf = []
            self.buflen = 0

    # ---- simple values
    def real(self, s, where):
        t = s.strip()
        m = _RE_REAL.match(t)
        if m and (m.group(2) or m.group(3)):
            sign, ip, fp, ex = m.groups()
            r = sign + (ip or '0') + '.' + (fp or '')
            if ex is not None:
                r += 'E' + ex
            return r
        if t.lower() in NONFINITE or _RE_NONFIN.match(t):
            self.note('nonfinite_real', '%s=%r' % (where, t))
            if self.nonfinite == 'fail':
                raise ValueError_('non-finite real %r at %s' % (t, where))
            return '$'
        if _RE_COMMA.match(t):
            self.note('decimal_comma_real', '%s=%r' % (where, t))
            return self.real(t.replace(',', '.'), where)
        raise ValueError_('bad real %r at %s' % (t, where))

    def integer(self, s, where):
        t = s.strip()
        if _RE_INT.match(t):
            return str(int(t))
        try:
            f = float(t)
            if f == int(f):
                self.note('integer_written_as_real', '%s=%r' % (where, t))
                return str(int(f))
        except ValueError:
            pass
        raise ValueError_('bad integer %r at %s' % (t, where))

    def simple(self, name, text, where):
        if name == 'string':
            return spf_string(text or '')
        if name in ('real', 'number'):
            return self.real(text or '', where)
        if name == 'integer':
            return self.integer(text or '', where)
        if name in ('boolean', 'logical'):
            t = (text or '').strip().lower()
            if t in ('true', '1', 't', '.t.'):
                return '.T.'
            if t in ('false', '0', 'f', '.f.'):
                return '.F.'
            if name == 'logical' and t in ('unknown', 'u', '.u.'):
                return '.U.'
            raise ValueError_('bad %s %r at %s' % (name, text, where))
        if name == 'binary':
            t = (text or '').strip()
            if re.match(r'[0-9A-Fa-f]*$', t):
                return '"0%s"' % t.upper()
            raise ValueError_('bad binary %r at %s' % (t[:40], where))
        raise ValueError_('unknown simple type %s at %s' % (name, where))

    def enum(self, k, text, where):
        t = (text or '').strip().strip('.').upper()
        if t in k[2]:
            return '.%s.' % t
        self.note('enum_value_not_in_schema', '%s=%r (%s)' % (where, text, k[1].name()))
        return '.%s.' % re.sub(r'[^A-Z0-9_]', '_', t) if t else '$'

    def from_text(self, k, text, where):
        """value of kind k from a text (element text or XML attribute)"""
        kk = k[0]
        if kk == 'simple':
            return self.simple(k[1], text, where)
        if kk == 'enum':
            return self.enum(k, text, where)
        if kk == 'agg':
            ek = k[3]
            toks = (text or '').split()
            if ek[0] == 'agg':        # nested aggregate in one text: only with a fixed inner size
                inner = ek[1]
                b1, b2 = inner.bound1(), inner.bound2()
                if b1 == b2 and b1 > 0 and len(toks) % b1 == 0:
                    ik = ek[3]
                    return [[self.from_text(ik, x, where) for x in toks[i:i + b1]] for i in range(0, len(toks), b1)]
                raise ValueError_('nested list as flat text without fixed inner size at %s' % where)
            if ek[0] == 'simple' and ek[1] == 'string':
                return [spf_string(x) for x in toks]
            return [self.from_text(ek, x, where) for x in toks]
        if kk == 'select':
            raise ValueError_('select value without type at %s' % where)
        if kk == 'entity':
            raise ValueError_('entity value as text at %s' % where)
        raise ValueError_('kind %s at %s' % (kk, where))

    # ---- element values
    def typed(self, d, el, where):
        """select member given by declaration d (defined type / enumeration) with value element el -> IFCX(v)"""
        k = self.sc.kind_of_decl(d)
        if k[0] == 'agg':
            v = self.agg(k, el, where)
        elif k[0] in ('simple', 'enum'):
            v = self.from_text(k, el.text, where)
        else:
            raise ValueError_('typed value of %s at %s' % (k[0], where))
        return '%s(%s)' % (d.name().upper(), fmt(v))

    def select_item(self, sel, el, where):
        """el is the typed member element: <IfcX ref/id..>, <IfcLabel>v</IfcLabel>, <IfcLabel-wrapper>v</..>"""
        r = ref_of(el)
        tag = local(el.tag)
        xt = strip_prefix(el.get(XSI_TYPE))
        name = xt or tag
        if name.endswith('-wrapper'):
            name = name[:-8]
        d = self.sc.decl(name)
        if r is not None:
            if el.find('*') is not None:
                self.note('ref_with_content_ignored', '%s ref=%s' % (where, r))
            return self.ref(r)
        if d is None:
            raise ValueError_('unknown select member <%s> at %s' % (tag, where))
        if d.as_entity() is not None:
            return '#%d' % self.entity(el, d.as_entity())
        if sel is not None and not self.sc.select_contains(sel, d):
            self.note('select_member_not_in_select', '%s: %s not in %s' % (where, d.name(), sel.name()))
        return self.typed(d, el, where)

    def item(self, ek, el, where):
        """aggregate item element of element kind ek"""
        r = ref_of(el)
        if r is not None:
            if el.find('*') is not None:
                self.note('ref_with_content_ignored', '%s ref=%s' % (where, r))
            return self.ref(r)
        kk = ek[0]
        if kk == 'entity':
            tag = strip_prefix(el.get(XSI_TYPE)) or local(el.tag)
            d = self.sc.entity_decl(tag)
            if d is None:
                kids = list(el)       # <wrapper><IfcX ../></wrapper>
                if len(kids) == 1:
                    return self.item(ek, kids[0], where)
                raise ValueError_('aggregate item <%s> is not an entity at %s' % (local(el.tag), where))
            return '#%d' % self.entity(el, d)
        if kk == 'select':
            return self.select_item(ek[1], el, where)
        if kk == 'agg':
            return self.agg(ek, el, where)
        return self.from_text(ek, el.text, where)

    def agg(self, k, el, where):
        """aggregate value held by element el (attribute element or nested list element)"""
        ek = k[3]
        kids = list(el)
        xt = strip_prefix(el.get(XSI_TYPE))
        if ek[0] in ('entity', 'select') and ((xt and self.sc.entity_decl(xt) is not None) or el.get('id') is not None):
            # single instance written on the aggregate attribute element itself (<RelatedObjects xsi:type="IfcSite"
            # id=..>..</RelatedObjects>, seen in IFC4 ifcXML): that element is the one item
            self.c['aggregate_single_item_on_attribute_element'] += 1
            d = self.sc.entity_decl(xt) if xt else (ek[1] if ek[0] == 'entity' else None)
            if d is None:
                raise ValueError_('cannot type single aggregate item at %s' % where)
            return ['#%d' % self.entity(el, d)]
        if not kids:
            return self.from_text(k, el.text, where)
        ps = [pos_of(c) for c in kids]
        if all(p is not None for p in ps) and ps != sorted(ps):
            kids = [c for _, c in sorted(zip(ps, kids), key=lambda x: x[0])]
            self.c['aggregate_reordered_by_pos'] += 1
        return [self.item(ek, c, where) for c in kids]

    def value(self, k, el, where):
        """value of an attribute held by the attribute element el"""
        r = ref_of(el)
        kk = k[0]
        if r is not None and kk != 'agg':
            if el.find('*') is not None:
                self.note('ref_with_content_ignored', '%s ref=%s' % (where, r))
            return self.ref(r)
        if el.get(XSI_NIL) == 'true' and r is None and not list(el) and not (el.text or '').strip():
            return None
        xt = strip_prefix(el.get(XSI_TYPE))
        if kk == 'entity':
            kids = list(el)
            if xt is None and len(kids) == 1 and self.sc.entity_decl(local(kids[0].tag)) is not None \
                    and not any(a[:1].isupper() for a in el.attrib):
                c = kids[0]                                  # IFC2x3: <Attr><IfcX id|ref ...></Attr>
                rc = ref_of(c)
                if rc is not None:
                    if c.find('*') is not None:
                        self.note('ref_with_content_ignored', '%s ref=%s' % (where, rc))
                    return self.ref(rc)
                return '#%d' % self.entity(c, self.sc.entity_decl(local(c.tag)))
            if xt is None and not kids and not any(a[:1].isupper() for a in el.attrib) and not (el.text or '').strip():
                self.note('empty_entity_attribute_element', where)
                return None
            d = self.sc.entity_decl(xt) if xt else k[1]     # IFC4: the attribute element is the instance
            if d is None:
                raise ValueError_('unknown xsi:type %s at %s' % (xt, where))
            return '#%d' % self.entity(el, d)
        if kk == 'select':
            if xt:
                d = self.sc.decl(xt[:-8] if xt.endswith('-wrapper') else xt)
                if d is not None and d.as_entity() is not None:
                    return '#%d' % self.entity(el, d.as_entity())
                if d is not None:
                    return self.typed(d, el, where)
            kids = list(el)
            if len(kids) == 1:
                return self.select_item(k[1], kids[0], where)
            if not kids and not (el.text or '').strip():
                return None
            raise ValueError_('select attribute with %d children at %s' % (len(kids), where))
        if kk == 'agg':
            if r is not None:
                return [self.ref(r)]
            return self.agg(k, el, where)
        kids = list(el)
        if kids and len(kids) == 1 and not (el.text or '').strip():
            self.note('simple_value_wrapped_in_element', '%s <%s>' % (where, local(kids[0].tag)))
            return self.from_text(k, kids[0].text, where)
        return self.from_text(k, el.text, where)

    # ---- instances
    def entity(self, el, d, implied=None):
        """el is the element carrying instance d (by its own tag, xsi:type or the declared attribute type)
        -> SPF instance number. implied = (forward attribute name, enclosing instance number) for nesting under an
        INVERSE attribute."""
        xid = el.get('id')
        n = self.sid(xid)
        if n in self.defined:
            self.note('duplicate_definition_skipped', 'id=%s %s' % (xid, d.name()))
            return n
        self.defined.add(n)
        name_uc, attrs, der, idx, idx_l, inv, inv_l, abstract, kinds = self.sc.ent(d)
        if abstract:
            self.note('abstract_entity_instance', '%s id=%s' % (d.name(), xid))
        vals = [None] * len(attrs)
        where0 = '%s#%d' % (d.name(), n)
        for a, v in el.attrib.items():                       # IFC4: simple values as XML attributes
            if a[:1] == '{' or not a[:1].isupper():
                continue
            i = idx.get(a)
            if i is None:
                i = idx_l.get(a.lower())
            if i is None:
                self.unknown['xmlattr:%s.%s' % (d.name(), a)] += 1
                continue
            vals[i] = self.from_text(kinds[i], v, '%s.%s' % (where0, attrs[i][0]))
        for ch in el:
            nm = local(ch.tag)
            i = idx.get(nm)
            if i is None:
                i = idx_l.get(nm.lower())
            if i is not None:
                if der[i]:
                    self.c['derived_attribute_value_ignored'] += 1
                    continue
                vals[i] = self.value(kinds[i], ch, '%s.%s' % (where0, attrs[i][0]))
                continue
            iv = inv.get(nm) or inv_l.get(nm.lower())
            if iv is not None:
                self.inverse(n, iv, ch, where0)
                continue
            self.unknown['element:%s.%s' % (d.name(), nm)] += 1
        for i, v in enumerate(vals):
            if v == [] and kinds[i][0] == 'agg':
                if attrs[i][2] and kinds[i][1].bound1() >= 1:
                    vals[i] = None              # '' / <X/> for an optional [1:?] list: no value (an empty list is invalid)
                    self.note('empty_list_for_optional_attribute_unset', '%s.%s' % (where0, attrs[i][0]))
                elif kinds[i][1].bound1() >= 1:
                    self.note('empty_list_for_required_attribute_kept', '%s.%s' % (where0, attrs[i][0]))
        if implied is not None:
            fname, pid = implied
            i = idx.get(fname)
            if i is None:
                self.note('inverse_forward_attribute_missing', '%s.%s' % (d.name(), fname))
            else:
                pref = '#%d' % pid
                k = kinds[i]
                if k[0] == 'agg':
                    cur = vals[i] if isinstance(vals[i], list) else []
                    if pref not in cur:
                        cur.append(pref)
                        self.c['inverse_nesting_forward_set'] += 1
                    vals[i] = cur
                elif vals[i] is None:
                    vals[i] = pref
                    self.c['inverse_nesting_forward_set'] += 1
                elif vals[i] != pref:
                    self.note('inverse_nesting_conflict', '%s.%s=%s nested under #%d' % (d.name(), fname, vals[i], pid))
        parts = []
        for i, v in enumerate(vals):
            if der[i]:
                parts.append('*')
            elif v is None:
                parts.append('$')
            else:
                parts.append(fmt(v))
        self.w('#%d=%s(%s);\n' % (n, name_uc, ','.join(parts)))
        self.by_type[d.name()] += 1
        return n

    def inverse(self, pid, iv, el, where):
        """instances nested under an INVERSE attribute element of instance #pid. Two encodings:
        <IsDecomposedBy><IfcRelAggregates ..>..</IfcRelAggregates></IsDecomposedBy>   (children are instances) and
        <HasOpenings GlobalId=..><OwnerHistory ../>..</HasOpenings>                   (the inverse element is the
        instance, type = xsi:type or the inverse's entity). The forward attribute of each nested instance
        (RelatingObject, RelatingBuildingElement, RelatedObjects ...) is set to / extended with #pid."""
        fwd = iv.attribute_reference().name()
        target = iv.entity_reference()
        xt = strip_prefix(el.get(XSI_TYPE))
        if ref_of(el) is not None:
            self.c['inverse_reference_skipped'] += 1
            return
        kids = list(el)
        d_self = self.sc.entity_decl(xt) if xt else target
        if d_self is not None:
            ent = self.sc.ent(d_self)
            own = set(ent[4]) | set(ent[6])        # lower-case explicit + inverse attribute names
            if xt or any(a[:1].isupper() for a in el.attrib if a[:1] != '{') or \
                    any(local(c.tag).lower() in own for c in kids):
                self.entity(el, d_self, implied=(fwd, pid))
                self.c['inverse_nested_instances'] += 1
                return
        for c in kids:
            if ref_of(c) is not None:
                self.c['inverse_reference_skipped'] += 1          # forward attribute is on the referenced instance
                continue
            d = self.sc.entity_decl(strip_prefix(c.get(XSI_TYPE)) or local(c.tag))
            if d is None:
                self.unknown['inverse_item:%s' % local(c.tag)] += 1
                continue
            self.entity(c, d, implied=(fwd, pid))
            self.c['inverse_nested_instances'] += 1


def fmt(v):
    if isinstance(v, list):
        return '(' + ','.join(fmt(x) for x in v) + ')'
    return '$' if v is None else v


# ------------------------------------------------------------------------------------------------ input handling
def open_input(path, member=None, tmpdir=None, rec=None):
    """-> path of a plain XML file to parse (zip member / gunzip extracted into tmpdir when needed)"""
    with open(path, 'rb') as f:
        head = f.read(8)
    if head[:4] == b'PK\x03\x04':
        with zipfile.ZipFile(path) as z:
            infos = [i for i in z.infolist() if not i.is_dir()]
            rec['zip_members'] = [[i.filename, i.file_size] for i in infos][:50]
            if member:
                cand = [i for i in infos if i.filename == member]
            else:
                cand = [i for i in infos if i.filename.lower().endswith(('.ifcxml', '.xml'))] or \
                       [i for i in infos if not i.filename.lower().endswith('.ifc')]
            if not cand:
                spf = [i.filename for i in infos if i.filename.lower().endswith('.ifc')]
                raise NotIfcXml('zip_without_xml_member' + (' (holds SPF %s)' % spf[:3] if spf else ''))
            m = max(cand, key=lambda i: i.file_size)
            rec['member'] = m.filename
            out = os.path.join(tmpdir, 'member.xml')
            with z.open(m) as a, open(out, 'wb') as b:
                while True:
                    blk = a.read(1 << 24)
                    if not blk:
                        break
                    b.write(blk)
            return open_input(out, None, tmpdir, rec)
    if head[:2] == b'\x1f\x8b':
        out = os.path.join(tmpdir, 'gunzip.xml')
        with gzip.open(path) as a, open(out, 'wb') as b:
            while True:
                blk = a.read(1 << 24)
                if not blk:
                    break
                b.write(blk)
        rec['gunzipped'] = True
        return out
    return path


class NotIfcXml(Exception):
    pass


def prescan_ids(path):
    """ids of all elements -> (numeric i<digits> / <digits> ids unique -> keep them, max number, count). Non-numeric ids
    (p1, exp_1, uos_1 ...) do not prevent keeping the numeric ones: they are numbered above the largest id (map in the
    report)."""
    rx = re.compile(rb'\sid\s*=\s*(?:"([^"]*)"|\'([^\']*)\')')
    nums = []
    other = 0
    with open(path, 'rb') as f:
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            for m in rx.finditer(mm):
                v = m.group(1) if m.group(1) is not None else m.group(2)
                if v[:1] in (b'i', b'I') and v[1:].isdigit():
                    nums.append(int(v[1:]))
                elif v.isdigit():
                    nums.append(int(v))
                elif v in (b'uos_1',) or v.startswith(b'uos') or v.lower() == b'ifcxml4':
                    continue
                else:
                    other += 1
        finally:
            mm.close()
    uniq = len(set(nums)) == len(nums) and (not nums or min(nums) >= 1)     # SPF instance names start at #1
    return uniq, (max(nums) if nums else 0), len(nums) + other


def header_fields(hdr_el):
    h = {}
    for c in hdr_el:
        n = local(c.tag)
        h[n] = (c.text or '').strip()
    return h


def write_header(out, hdr, uos_attr, schema, src_name, src_sha):
    desc = hdr.get('documentation') or (uos_attr or {}).get('description') or ''     # as given; nothing invented
    out.write('ISO-10303-21;\nHEADER;\n')
    out.write('/* converted from ifcXML (ISO 10303-28) by %s; source %s sha256 %s */\n' %
              (VERSION, src_name.replace('*/', '* /'), src_sha))
    out.write("FILE_DESCRIPTION((%s),'2;1');\n" % spf_string(desc))
    out.write('FILE_NAME(%s,%s,(%s),(%s),%s,%s,%s);\n' % (
        spf_string(hdr.get('name', '')), spf_string(hdr.get('time_stamp', '')), spf_string(hdr.get('author', '')),
        spf_string(hdr.get('organization', '')), spf_string(hdr.get('preprocessor_version', '')),
        spf_string(hdr.get('originating_system', '')), spf_string(hdr.get('authorization', ''))))
    out.write("FILE_SCHEMA(('%s'));\nENDSEC;\nDATA;\n" % schema)


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for blk in iter(lambda: f.read(1 << 22), b''):
            h.update(blk)
    return h.hexdigest()


def convert(src, dst, schema_override=None, member=None, nonfinite='null', renumber=False):
    t0 = time.time()
    rep = {'version': VERSION, 'input': src, 'input_bytes': os.path.getsize(src), 'input_sha256': sha256_file(src),
           'output': dst}
    tmpdir = tempfile.mkdtemp(prefix='ifcxml2spf_', dir=os.path.dirname(os.path.abspath(dst)) or '.')
    try:
        try:
            xml = open_input(src, member, tmpdir, rep)
        except NotIfcXml as e:
            rep.update(status='not_ifcxml', reason=str(e))
            return rep, 2
        rep['xml_bytes'] = os.path.getsize(xml)
        with open(xml, 'rb') as f:
            head = f.read(1 << 16)
        container, schema, root = detect(head)
        rep['xml_root'] = root
        if container is None:
            # what is it? (evidence for non-IFC XML such as Tekla 'NewDataSet' level tables)
            kids = re.findall(r'<([A-Za-z_][\w.\-:]*)[\s>/]', decode_head(head))
            rep.update(status='not_ifcxml', reason='xml root <%s> is not iso_10303_28 / ifcXML' % root,
                       first_elements=list(dict.fromkeys(kids))[:12])
            return rep, 2
        schema = schema_override or schema
        if schema == 'IFC2X2':
            rep['schema_note'] = 'IFC2x2 ifcXML read with the IFC2X3 schema (no IFC2X2 schema in ifcopenshell)'
            schema = 'IFC2X3'
        if schema is None:
            rep.update(status='unsupported_schema', reason='schema not identified from namespace/configuration')
            return rep, 5
        rep['schema'] = schema
        rep['container'] = container
        sc = Schema(schema)
        numeric, mx, nid = prescan_ids(xml)
        if renumber:
            numeric = False
        rep['ids'] = {'xml_ids': nid, 'numeric_kept': numeric, 'max_id': mx}
        tmp_out = dst + '.part'
        fo = open(tmp_out, 'w', encoding='ascii', newline='\n', buffering=1 << 20)
        conv = Converter(sc, fo, numeric, (mx + 1) if numeric else 1, nonfinite)
        hdr = {}
        uos_attr = {}
        header_written = False
        depth = 0
        cont_el = None           # element whose children are the instances
        cont_depth = None
        hdr_depth = None
        xml_top = collections.Counter()
        xml_top_with_id = 0
        errors = []
        try:
            for ev, el in ET.iterparse(xml, events=('start', 'end')):
                if ev == 'start':
                    depth += 1
                    nm = local(el.tag)
                    if cont_el is None:
                        if container == 'p28' and nm == 'uos':
                            cont_el, cont_depth = el, depth
                            uos_attr = {local(k): v for k, v in el.attrib.items()}
                            if not schema_override:
                                cfg = (el.get('configuration') or '').lower()
                                if 'ifc4' in cfg and schema == 'IFC2X3':
                                    errors.append('uos configuration %s disagrees with namespace' % cfg)
                        elif container == 'ifcxml' and depth == 1:
                            cont_el, cont_depth = el, depth
                    if nm in ('iso_10303_28_header', 'header') and depth <= 2:
                        hdr_depth = depth
                    continue
                # end
                depth -= 1
                if hdr_depth is not None and depth + 1 == hdr_depth and local(el.tag) in ('iso_10303_28_header', 'header'):
                    hdr = header_fields(el)
                    hdr_depth = None
                    continue
                if cont_el is not None and depth == cont_depth and el is not cont_el:
                    # one top-level element (an instance) is complete
                    nm = local(el.tag)
                    if nm in ('header', 'iso_10303_28_header'):
                        continue
                    if not header_written:
                        write_header(fo, hdr, uos_attr, schema, os.path.basename(src), rep['input_sha256'])
                        header_written = True
                    d = sc.entity_decl(strip_prefix(el.get(XSI_TYPE)) or nm)
                    xml_top[nm] += 1
                    if el.get('id') is not None:
                        xml_top_with_id += 1
                    if d is None:
                        conv.unknown['top:%s' % nm] += 1
                    elif ref_of(el) is not None:
                        conv.c['top_level_reference_skipped'] += 1
                    else:
                        try:
                            conv.entity(el, d)
                        except ValueError_ as e:
                            errors.append(str(e))
                            if len(errors) > 50:
                                raise
                    cont_el.remove(el)
        except ET.ParseError as e:
            conv.flush()
            fo.close()
            rep.update(status='xml_parse_error', reason=str(e), instances_before_error=sum(conv.by_type.values()))
            os.remove(tmp_out)
            return rep, 3
        if not header_written:
            write_header(fo, hdr, uos_attr, schema, os.path.basename(src), rep['input_sha256'])
        conv.flush()
        fo.write('ENDSEC;\nEND-ISO-10303-21;\n')
        fo.close()
        os.replace(tmp_out, dst)
        dangling = sorted(conv.referenced - conv.defined)
        rep.update({
            'status': 'converted' if not errors else 'converted_with_value_errors',
            'header': hdr,
            'uos': uos_attr,
            'instances': sum(conv.by_type.values()),
            'instances_by_type': dict(sorted(conv.by_type.items())),
            'xml_top_level_elements': sum(xml_top.values()),
            'xml_top_level_with_id': xml_top_with_id,
            'nested_instances': sum(conv.by_type.values()) - (sum(xml_top.values()) - sum(v for k, v in conv.unknown.items() if k.startswith('top:'))),
            'references': conv.c['references'],
            'dangling_references': len(dangling),
            'dangling_sample': dangling[:20],
            'counters': dict(conv.c),
            'notes': {k: v for k, v in conv.notes.items()},
            'unknown_xml_names': dict(conv.unknown.most_common(50)),
            'idmap': conv.idmap if len(conv.idmap) <= 2000000 else None,
            'idmap_size': len(conv.idmap),
            'value_errors': errors[:50],
            'output_bytes': os.path.getsize(dst),
            'output_sha256': sha256_file(dst),
            'sec': round(time.time() - t0, 2),
        })
        rc = 0 if not dangling and not errors else 4
        return rep, rc
    finally:
        for fn in os.listdir(tmpdir):
            try:
                os.remove(os.path.join(tmpdir, fn))
            except OSError:
                pass
        try:
            os.rmdir(tmpdir)
        except OSError:
            pass


def main():
    sys.setrecursionlimit(20000)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('src')
    ap.add_argument('dst')
    ap.add_argument('--report')
    ap.add_argument('--schema', help='override the schema read from the ifcXML namespace')
    ap.add_argument('--member', help='zip member to convert (default: largest .ifcxml/.xml member)')
    ap.add_argument('--nonfinite', choices=('null', 'fail'), default='null',
                    help='NaN/INF reals: write $ and list them in the report (default) or fail')
    ap.add_argument('--renumber', action='store_true', help='number instances 1..n instead of keeping XML i<n> ids')
    a = ap.parse_args()
    rep, rc = convert(a.src, a.dst, a.schema, a.member, a.nonfinite, a.renumber)
    rep['exit_code'] = rc
    s = json.dumps(rep, indent=1, default=str)
    if a.report:
        with open(a.report, 'w') as f:
            f.write(s)
    short = {k: rep.get(k) for k in ('status', 'reason', 'schema', 'instances', 'references', 'dangling_references',
                                     'unknown_xml_names', 'value_errors', 'sec', 'output_bytes') if k in rep}
    print(json.dumps(short, default=str))
    sys.exit(rc)


if __name__ == '__main__':
    main()
