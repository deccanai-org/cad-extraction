W=/work/agentwork/ifc-volume-residue
/opt/conv/env/bin/python - <<'PY'
import re, glob, os
pat = re.compile(rb'IFCCOMPOSITECURVESEGMENT\s*\([^;]*?,\s*\$\s*\)\s*;', re.I)
tot = 0
for p in sorted(glob.glob('/work/agentwork/ifc-volume-residue/in/*.bin')):
    b = open(p, 'rb').read()
    n = len(pat.findall(b)); tot += n
    if n: print(os.path.basename(p), n)
print('total', tot, 'files', len(glob.glob('/work/agentwork/ifc-volume-residue/in/*.bin')))
PY
