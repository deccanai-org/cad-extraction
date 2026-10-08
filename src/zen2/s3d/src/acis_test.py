import sys, collections
import acis
import ezdxf.acis.sab as S
print([t.name + '=' + hex(t.value) for t in S.Tags])
sab = open(sys.argv[1], 'rb').read()
b = S.parse_sab(sab)
names = collections.Counter(e.name for e in b.entities)
print('header', b.header.version, 'entities', len(b.entities)); print(names.most_common(40))
try:
    ms = acis.meshes(sab)
    for v, f in ms: print('mesh', len(v), 'verts', len(f), 'faces', v[:3])
except Exception as e:
    import traceback; traceback.print_exc()
