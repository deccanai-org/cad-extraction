import ifcopenshell, collections, json, sys, os, zipfile, tempfile
from concurrent.futures import ProcessPoolExecutor
SP = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + '/'
def open_ifc(path):
    if path.lower().endswith('zip'):
        z = zipfile.ZipFile(path); n = [x for x in z.namelist() if x.lower().endswith('.ifc')][0]
        d = tempfile.mkdtemp(); z.extract(n, d); return ifcopenshell.open(os.path.join(d, n))
    return ifcopenshell.open(path)
def census(m):
    f = open_ifc(SP + m['ifc_local'])
    out = {'stem': m['stem'], 'schema': f.schema, 'origin': str(f.header.file_name.originating_system)[:80], 'pre': str(f.header.file_name.preprocessor_version)[:60]}
    ua = f.by_type('IfcUnitAssignment')
    units = []
    for u in (ua[0].Units if ua else []):
        if u.is_a('IfcSIUnit'): units.append((u.UnitType, u.Prefix, u.Name))
        elif u.is_a('IfcConversionBasedUnit'): units.append((u.UnitType, u.Name, u.ConversionFactor.ValueComponent.wrappedValue if u.ConversionFactor else None))
    out['units'] = [x for x in units if x[0] in ('LENGTHUNIT', 'PLANEANGLEUNIT')]
    prods = [p for p in f.by_type('IfcProduct') if p.Representation and not p.is_a('IfcOpeningElement') and not p.is_a('IfcSpatialStructureElement') and not p.is_a('IfcGrid') and not p.is_a('IfcAnnotation') and not p.is_a('IfcSpace')]
    out['products'] = dict(collections.Counter(p.is_a() for p in prods).most_common())
    items = collections.Counter(); prof = collections.Counter(); curves = collections.Counter(); ops = collections.Counter(); reps = collections.Counter()
    seen = set()
    def walk(it):
        if it.id() in seen and not it.is_a('IfcMappedItem'): return
        seen.add(it.id())
        items[it.is_a()] += 1
        if it.is_a('IfcMappedItem'):
            for i in it.MappingSource.MappedRepresentation.Items: walk(i)
        elif it.is_a('IfcBooleanResult'):
            ops[(it.Operator, it.SecondOperand.is_a())] += 1; walk(it.FirstOperand); walk(it.SecondOperand)
        elif it.is_a('IfcSweptAreaSolid'):
            sa = it.SweptArea; prof[sa.is_a()] += 1
            if sa.is_a('IfcArbitraryClosedProfileDef'):
                curves[sa.OuterCurve.is_a()] += 1
                if sa.OuterCurve.is_a('IfcCompositeCurve'):
                    for s in sa.OuterCurve.Segments: curves['seg:' + s.ParentCurve.is_a()] += 1
                if sa.is_a('IfcArbitraryProfileDefWithVoids'):
                    for ic in sa.InnerCurves: curves['inner:' + ic.is_a()] += 1
            if sa.is_a('IfcDerivedProfileDef'): prof['parent:' + sa.ParentProfile.is_a()] += 1
        elif it.is_a('IfcPolygonalBoundedHalfSpace'):
            curves['pbhs:' + it.PolygonalBoundary.is_a()] += 1
        elif it.is_a('IfcCsgSolid'):
            items['csg:' + it.TreeRootExpression.is_a()] += 1
    for p in prods:
        for r in p.Representation.Representations:
            reps[(r.RepresentationIdentifier, r.RepresentationType)] += 1
            if r.RepresentationIdentifier in ('Body', 'Facetation', None, ''):
                for it in r.Items: walk(it)
    openings = f.by_type('IfcRelVoidsElement')
    oi = collections.Counter()
    for rv in openings:
        o = rv.RelatedOpeningElement
        if o.Representation:
            for r in o.Representation.Representations:
                for it in r.Items: oi[it.is_a()] += 1
    psets = collections.Counter()
    for rel in f.by_type('IfcRelDefinesByProperties'):
        pd = rel.RelatingPropertyDefinition
        if pd.is_a('IfcPropertySet'):
            for pr in pd.HasProperties:
                if any(k in pr.Name.upper() for k in ('POS', 'MARK', 'PROFILE', 'MATERIAL', 'GRADE', 'NAME', 'REFERENCE', 'LENGTH', 'WEIGHT')): psets[pd.Name + '.' + pr.Name] += 1
    out.update(reps=dict((f'{a}/{b}', v) for (a, b), v in reps.most_common()), items=dict(items.most_common()), profiles=dict(prof.most_common()),
               curves=dict(curves.most_common()), bool_ops=dict((f'{a}:{b}', v) for (a, b), v in ops.most_common()), openings=len(openings),
               opening_items=dict(oi.most_common()), psets=dict(psets.most_common(25)), n_products=len(prods),
               assemblies=len(f.by_type('IfcElementAssembly')), fasteners=len(f.by_type('IfcMechanicalFastener')) + len(f.by_type('IfcFastener')),
               materials=len(f.by_type('IfcMaterial')))
    return out
if __name__ == '__main__':
    M = json.load(open(SP + 'models.json'))
    with ProcessPoolExecutor(8) as ex: R = list(ex.map(census, M))
    json.dump(R, open(SP + 'census.json', 'w'), indent=1)
    tot = collections.Counter(); prof = collections.Counter(); items = collections.Counter(); ops = collections.Counter(); curves = collections.Counter(); oi = collections.Counter(); prods = collections.Counter()
    for r in R:
        print(r['stem'][:55].ljust(55), r['schema'], r['n_products'], r['origin'][:40], '|', r['pre'][:40], r['units'])
        for k, v in r['items'].items(): items[k] += v
        for k, v in r['profiles'].items(): prof[k] += v
        for k, v in r['bool_ops'].items(): ops[k] += v
        for k, v in r['curves'].items(): curves[k] += v
        for k, v in r['opening_items'].items(): oi[k] += v
        for k, v in r['products'].items(): prods[k] += v
        tot['openings'] += r['openings']; tot['assemblies'] += r['assemblies']; tot['fasteners'] += r['fasteners']; tot['products'] += r['n_products']
    print('TOTAL', dict(tot)); print('PRODUCTS', dict(prods.most_common())); print('ITEMS', dict(items.most_common())); print('PROFILES', dict(prof.most_common()))
    print('BOOL', dict(ops.most_common())); print('CURVES', dict(curves.most_common())); print('OPENING ITEMS', dict(oi.most_common()))
