import sys, os
DEC = sys.argv[1]; sys.path.insert(0, DEC)
from sds2job import read_shapes
for job, names in [(sys.argv[2], ["HSS1.5x13GA", "HSS1 1/2x1/8", "PIPE 1 1/4 STD", "HSS6x4x1/2", "W16x100", "HSS1.900x0.145", "W18x35"]), (sys.argv[3], ["HSS6x4x1/2"])]:
    S = read_shapes(job)
    for k, s in S.items():
        if s.name in names or any(s.name.startswith(n) for n in names):
            print(os.path.basename(job)[:20], k, s)
