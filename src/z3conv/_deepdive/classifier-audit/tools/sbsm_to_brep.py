#!/usr/bin/env python3
"""Experiment only: rewrite a STEP whose parts are SHELL_BASED_SURFACE_MODEL(OPEN_SHELL) (ifc2step5 transcode of
IfcShellBasedSurfaceModel) into FACETED_BREP(CLOSED_SHELL), to test whether the source closed shells make valid solids.
usage: sbsm_to_brep.py IN.stp OUT.stp"""
import re, sys
src, dst = sys.argv[1:3]
sb = re.compile(r"^(#\d+)\s*=\s*SHELL_BASED_SURFACE_MODEL\('([^']*)',\((#\d+)\)\);")
n = {'sbsm': 0, 'multi': 0, 'open': 0, 'rep': 0}
with open(src, encoding='latin-1') as f, open(dst, 'w', encoding='latin-1') as g:
    for line in f:
        m = sb.match(line)
        if m:
            line = f"{m.group(1)}=FACETED_BREP('{m.group(2)}',{m.group(3)});\n"; n['sbsm'] += 1
        elif 'SHELL_BASED_SURFACE_MODEL(' in line:
            n['multi'] += 1
        if 'OPEN_SHELL(' in line:
            line = line.replace('OPEN_SHELL(', 'CLOSED_SHELL('); n['open'] += 1
        if 'MANIFOLD_SURFACE_SHAPE_REPRESENTATION(' in line:
            line = line.replace('MANIFOLD_SURFACE_SHAPE_REPRESENTATION(', 'FACETED_BREP_SHAPE_REPRESENTATION('); n['rep'] += 1
        g.write(line)
print(n)
