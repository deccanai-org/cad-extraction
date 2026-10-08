#!/usr/bin/env python3
"""dwg_validate.py DXF... - load with ezdxf (recover mode), audit, entity counts per layout -> JSON on stdout"""
import sys, json, time, collections
import ezdxf
from ezdxf import recover
out = {}
for f in sys.argv[1:]:
    t = time.time()
    r = {}
    try:
        doc, auditor = recover.readfile(f)
        r['dxfversion'] = doc.dxfversion
        r['acadver'] = doc.header.get('$ACADVER')
        r['insunits'] = doc.header.get('$INSUNITS')
        r['recover_errors'] = len(auditor.errors)
        r['recover_fixes'] = len(auditor.fixes)
        a = doc.audit()
        r['audit_errors'] = len(a.errors)
        r['layouts'] = {}
        for lay in doc.layouts:
            c = collections.Counter(e.dxftype() for e in lay)
            r['layouts'][lay.name] = {'entities': sum(c.values()), 'types': dict(c.most_common(12))}
        r['blocks'] = len(doc.blocks)
        r['layers'] = len(doc.layers)
        r['objects_3dsolid'] = sum(1 for e in doc.entitydb.values() if e.dxftype() == '3DSOLID')
        r['status'] = 'ok'
    except Exception as e:
        r['status'] = 'error'
        r['error'] = '%s: %s' % (type(e).__name__, str(e)[:200])
    r['seconds'] = round(time.time() - t, 1)
    out[f] = r
print(json.dumps(out, indent=1))
