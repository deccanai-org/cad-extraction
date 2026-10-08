import ifcopenshell, collections, json, os, sys
sys.path.insert(0, os.path.dirname(__file__)); from census import open_ifc
SP = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + '/'
from concurrent.futures import ProcessPoolExecutor
def leaf_types(it, acc):
    if it.is_a('IfcMappedItem'):
        for i in it.MappingSource.MappedRepresentation.Items: leaf_types(i, acc)
    elif it.is_a('IfcBooleanResult'):
        acc.add('bool'); leaf_types(it.FirstOperand, acc)
    else: acc.add(it.is_a())
def one(m):
    f = open_ifc(SP + m['ifc_local']); mat = collections.Counter(); ex = {}
    for p in f.by_type('IfcProduct'):
        if not p.Representation or p.is_a('IfcOpeningElement') or p.is_a('IfcSpatialStructureElement') or p.is_a('IfcGrid') or p.is_a('IfcAnnotation') or p.is_a('IfcSpace'): continue
        acc = set()
        for r in p.Representation.Representations:
            if r.RepresentationIdentifier in ('Body', 'Facetation', None, ''):
                for it in r.Items: leaf_types(it, acc)
        key = (p.is_a(), '+'.join(sorted(acc)))
        mat[key] += 1
        if 'IfcFacetedBrep' in acc and key not in ex: ex[key] = (p.Name, p.ObjectType, p.Description)
    return m['stem'], {f'{a}|{b}': v for (a, b), v in mat.items()}, {f'{a}|{b}': v for (a, b), v in ex.items()}
if __name__ == '__main__':
    M = json.load(open(SP + 'models.json'))
    with ProcessPoolExecutor(8) as exr: R = list(exr.map(one, M))
    tot = collections.Counter(); exs = {}
    for stem, mat, ex in R:
        for k, v in mat.items(): tot[k] += v
        for k, v in ex.items(): exs.setdefault(k, (stem, v))
    for k, v in tot.most_common(): print(v, k, exs.get(k, ''))
    json.dump(R, open(SP + 'census2.json', 'w'), indent=1)
