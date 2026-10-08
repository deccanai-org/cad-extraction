import sys
import acis
import ezdxf.acis.sab as S
sab = open(sys.argv[1], 'rb').read()
b = S.parse_sab(sab)
seen = set()
idx = {id(e): i for i, e in enumerate(b.entities)}
for i, e in enumerate(b.entities):
    if e.name in seen or 'attrib' in e.name:
        continue
    seen.add(e.name)
    toks = []
    for t in e.data:
        v = t.value
        if t.tag == S.Tags.POINTER:
            v = '->%s#%s' % (getattr(v, 'name', '?'), idx.get(id(v), '-'))
        elif isinstance(v, float):
            v = round(v, 4)
        elif isinstance(v, (list, tuple)):
            v = tuple(round(x, 4) for x in v)
        toks.append('%x:%s' % (t.tag, v))
    print('#%d %s | %s' % (i, e.name, ' '.join(toks))[:420])
