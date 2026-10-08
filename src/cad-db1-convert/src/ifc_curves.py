import sys, collections, ifcopenshell
f=ifcopenshell.open(sys.argv[1]); c=collections.Counter(); ex=None
for p in f.by_type('IfcArbitraryClosedProfileDef'):
    c[p.OuterCurve.is_a()]+=1
    if p.OuterCurve.is_a()!='IfcPolyline' and ex is None: ex=p.OuterCurve
print(c)
if ex is not None:
    print(ex)
    for s in list(getattr(ex,'Segments',[]))[:6]: print('  ',s, s.ParentCurve)
