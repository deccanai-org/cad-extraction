import sys, os, traceback
sys.path.insert(0, sys.argv[1])
import numpy as np, brep
W = '/work/agentwork/sds2-pieces-not-built/jobs/'
jn, sid = sys.argv[2].split(':')
V, F = brep.parse(open(os.path.join(W + jn, 'subm', sid), 'rb').read())
out = [brep._solid(V, p) for p in brep.bodies(F)]
src = open(os.path.join(sys.argv[1], 'brep.py')).read()
a = src.index('def _nest_voids'); b = src.index('def _solid(V, faces')
body = src[a:b].replace('    except Exception:\n        return out\n', '    except Exception:\n        traceback.print_exc(); return out\n')
ns = dict(np=np, traceback=traceback)
exec(body, ns)
r = ns['_nest_voids'](out)
print('result', len(r))
