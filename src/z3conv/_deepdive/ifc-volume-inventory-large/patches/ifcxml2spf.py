#!/usr/bin/env python3
"""ifcXML -> IFC-SPF (STEP physical file) so the normal IFC pipeline can convert it. Both ifcopenshell builds of the kit
refuse ifcXML (0.8.4.post1: 'IFC-XML import temporarily disabled'; 0.9.0: 'Reading .ifcXML files is not currently
supported'). Pure Python (xml.etree + the ifcopenshell schema), following the conventions of IfcOpenShell's own
(disabled) parser src/ifcparse/parse_ifcxml.cpp:
  IFC4 / IFC4X3 dialect (root <ifcXML>): simple attributes are XML attributes (aggregates of simple values
    whitespace-separated, enums lower-case); entity attributes are child elements named after the attribute, the element
    itself being the instance (xsi:type or the declared entity type; id= / ref= / href=); select attributes wrap their
    value (<IfcLabel-wrapper>text</IfcLabel-wrapper> or an entity element); aggregates list their members as children;
    inverse attributes may contain the related instances (their forward attribute is set to the container)
  IFC2X3 dialect (root <ex:iso_10303_28>, <uos>): every attribute is a child element; values in text nodes; aggregates
    (ex:cType="list"/"set") list typed children; references are elements with ref= (xsi:nil="true")
usage: ifcxml2spf.py IN.ifcXML OUT.ifc       prints one JSON line {schema, dialect, instances, unresolved_refs, warnings}"""
import sys, json, re
import xml.etree.ElementTree as ET
import ifcopenshell
import ifcopenshell.ifcopenshell_wrapper as W

XSI_TYPE = '{http://www.w3.org/2001/XMLSchema-instance}type'


def local(tag):
    return tag.rsplit('}', 1)[-1].split(':')[-1]


class Ref:
    __slots__ = ('id',)

    def __init__(self, i):
        self.id = i


class Conv:
    def __init__(self, root):
        self.root = root
        self.warn = []
        self.dialect, self.schema_name = self.detect()
        self.S = W.schema_by_name(self.schema_name)
        self.f = ifcopenshell.file(schema=self.schema_name)
        self.ids = {}                     # xml id -> instance
        self.pending = []                 # (instance, attribute name, value with Ref)
        self.inverse_links = []           # (instance, forward attribute name, Ref | instance of the container)

    # ---------------------------------------------------------------- schema helpers
    def detect(self):
        tag = local(self.root.tag)
        loc = ' '.join(v for k, v in self.root.attrib.items() if k.endswith('schemaLocation')) + ' ' + self.root.tag
        if tag == 'iso_10303_28' or 'IFC2x3' in loc or 'IFC2X3' in loc:
            return 'ifc2x3', 'IFC2X3'
        if re.search(r'IFC4[_x]?3|IFC4X3', loc, re.I):
            return 'ifc4', 'IFC4X3_ADD2'
        return 'ifc4', 'IFC4'

    def decl(self, name):
        try:
            return self.S.declaration_by_name(name)
        except Exception:
            return None

    def attrs(self, ent):
        return {a.name(): a for a in ent.all_attributes()}

    def invs(self, ent):
        return {i.name(): i for i in ent.all_inverse_attributes()}

    @staticmethod
    def resolve(pt):
        """follow named defined types down to the underlying parameter type"""
        while pt.as_named_type() is not None:
            d = pt.as_named_type().declared_type()
            if d.as_type_declaration() is not None:
                pt = d.as_type_declaration().declared_type()
            else:
                break
        return pt

    def simple(self, pt, text):
        pt = self.resolve(pt)
        if pt.as_named_type() is not None:
            d = pt.as_named_type().declared_type()
            if d.as_enumeration_type() is not None:
                return text.strip().upper()
            return None
        if pt.as_simple_type() is not None:
            k = pt.as_simple_type().declared_type()
            t = text.strip()
            if k in ('real', 'number'):
                return float(t)
            if k == 'integer':
                return int(float(t))
            if k == 'boolean':
                return t.lower() in ('true', '1', '.t.')
            if k == 'logical':
                return {'true': True, 'false': False}.get(t.lower(), 'UNKNOWN')
            return text                                       # string / binary
        if pt.as_aggregation_type() is not None:
            el = pt.as_aggregation_type().type_of_element()
            inner = self.resolve(el)
            toks = text.split()
            if inner.as_aggregation_type() is not None:        # list of lists flattened (CoordList, CoordIndex)
                n = inner.as_aggregation_type().bound2()
                if n and n > 0:
                    vals = [self.simple(inner.as_aggregation_type().type_of_element(), t) for t in toks]
                    return tuple(tuple(vals[i:i + n]) for i in range(0, len(vals), n))
                return None
            return tuple(self.simple(el, t) for t in toks)
        return None

    # ---------------------------------------------------------------- instances
    def instance(self, el, declared=None):
        """element -> instance (or Ref for ref=/href=)"""
        for k in ('ref', 'href'):
            if k in el.attrib:
                return Ref(el.attrib[k])
        name = el.attrib.get(XSI_TYPE) or local(el.tag)
        name = name.split(':')[-1]
        d = self.decl(name)
        if d is None or d.as_entity() is None:
            d = declared
        if d is None or d.as_entity() is None or d.as_entity().is_abstract():
            self.warn.append(f'no concrete entity for <{local(el.tag)}>')
            return None
        ent = d.as_entity()
        inst = self.f.create_entity(ent.name())
        if 'id' in el.attrib:
            self.ids[el.attrib['id']] = inst
        A = self.attrs(ent); I = self.invs(ent)
        for k, v in el.attrib.items():                         # IFC4: simple attributes as XML attributes
            k = local(k)
            if k in A:
                try:
                    val = self.simple(A[k].type_of_attribute(), v)
                    if val is not None:
                        self.pending.append((inst, k, val))
                except Exception as e:
                    self.warn.append(f'{ent.name()}.{k}: {e}')
        for ch in el:
            k = local(ch.tag)
            if k in A:
                try:
                    val = self.value(A[k].type_of_attribute(), ch)
                    if val is not None:
                        self.pending.append((inst, k, val))
                except Exception as e:
                    self.warn.append(f'{ent.name()}.{k}: {type(e).__name__} {e}')
            elif k in I:
                inv = I[k]
                fwd = inv.attribute_reference().name()
                tgt = inv.entity_reference()
                for m in (list(ch) if len(ch) else []):
                    r = self.instance(m, tgt)
                    if r is not None:
                        self.inverse_links.append((r, fwd, inst))
                if not len(ch) and (ch.attrib or (ch.text or '').strip()):   # single-valued inverse written as the element
                    r = self.instance(ch, tgt)
                    if r is not None:
                        self.inverse_links.append((r, fwd, inst))
        return inst

    def wrapped(self, el):
        """<IfcLabel-wrapper>text</...> or <IfcLabel>text</IfcLabel> (typed value) or an entity element"""
        nm = local(el.tag).replace('-wrapper', '')
        d = self.decl(nm)
        if d is not None and d.as_type_declaration() is not None:
            pt = d.as_type_declaration().declared_type()
            v = self.simple(pt, el.text or '')
            return self.f.create_entity(nm, v) if v is not None else None
        return self.instance(el)

    def value(self, pt, el):
        """attribute element -> value"""
        for k in ('ref', 'href'):
            if k in el.attrib:
                return Ref(el.attrib[k])
        rp = self.resolve(pt)
        kids = list(el)
        if rp.as_aggregation_type() is not None:
            et = rp.as_aggregation_type().type_of_element()
            if not kids:
                return self.simple(rp, el.text or '') if (el.text or '').strip() else None
            out = []
            for m in kids:
                ert = self.resolve(et)
                if ert.as_simple_type() is not None or (ert.as_named_type() is not None and ert.as_named_type().declared_type().as_enumeration_type() is not None):
                    out.append(self.simple(et, m.text or ''))
                elif ert.as_aggregation_type() is not None:
                    out.append(self.value(et, m))
                elif ert.as_named_type() is not None and ert.as_named_type().declared_type().as_select_type() is not None:
                    out.append(self.wrapped(m))
                else:
                    out.append(self.instance(m, ert.as_named_type().declared_type() if ert.as_named_type() else None))
            return tuple(x for x in out if x is not None)
        if rp.as_named_type() is not None:
            d = rp.as_named_type().declared_type()
            if d.as_entity() is not None:
                if kids and (self.decl(local(kids[0].tag)) is not None and self.decl(local(kids[0].tag)).as_entity() is not None) \
                        and XSI_TYPE not in el.attrib and not any(local(k) in self.attrs(d.as_entity()) for k in el.attrib):
                    return self.instance(kids[0], d)           # 2x3 style: attribute element wraps the instance
                return self.instance(el, d)                    # IFC4 style: the attribute element is the instance
            if d.as_select_type() is not None:
                if XSI_TYPE in el.attrib:                      # IFC4: <RelativePlacement xsi:type="IfcAxis2Placement3D">
                    return self.instance(el)
                if kids:
                    return self.wrapped(kids[0])
                return None
            if d.as_enumeration_type() is not None:
                return self.simple(rp, el.text or '')
        return self.simple(rp, el.text or '')

    # ---------------------------------------------------------------- driver
    def fix(self, v):
        if isinstance(v, Ref):
            r = self.ids.get(v.id)
            if r is None:
                self.unresolved += 1
            return r
        if isinstance(v, tuple):
            return tuple(x for x in (self.fix(y) for y in v) if x is not None)
        return v

    def run(self):
        body = self.root
        for el in list(self.root.iter()):
            if local(el.tag) == 'uos':
                body = el
                break
        for el in body:
            t = local(el.tag)
            if t in ('header', 'iso_10303_28_header') or el.tag.endswith('header'):
                continue
            self.instance(el)
        self.unresolved = 0
        for inst, k, v in self.pending:
            try:
                setattr(inst, k, self.fix(v))
            except Exception as e:
                self.warn.append(f'set {inst.is_a()}.{k}: {str(e)[:80]}')
        for r, fwd, cont in self.inverse_links:
            r = self.fix(r)
            if r is None:
                continue
            try:
                cur = getattr(r, fwd)
                ft = self.resolve(self.attrs(self.decl(r.is_a()).as_entity())[fwd].type_of_attribute())
                if ft.as_aggregation_type() is not None:
                    setattr(r, fwd, tuple(cur or ()) + (cont,))
                else:
                    setattr(r, fwd, cont)
            except Exception as e:
                self.warn.append(f'inverse {r.is_a()}.{fwd}: {str(e)[:80]}')
        return self.f


def main():
    root = ET.parse(sys.argv[1]).getroot()
    c = Conv(root)
    f = c.run()
    f.write(sys.argv[2])
    rep = {'schema': c.schema_name, 'dialect': c.dialect, 'instances': len(list(f)), 'unresolved_refs': c.unresolved,
           'warnings': len(c.warn), 'warning_examples': c.warn[:8]}
    print(json.dumps(rep))


if __name__ == '__main__':
    main()
