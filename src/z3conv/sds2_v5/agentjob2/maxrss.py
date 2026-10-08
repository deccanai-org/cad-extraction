"""Run a command, report its peak RSS (GB) and wall time: python maxrss.py LABEL OUTJSON cmd args..."""
import sys, subprocess, resource, time, json
label, out = sys.argv[1], sys.argv[2]
t = time.time()
rc = subprocess.call(sys.argv[3:])
ru = resource.getrusage(resource.RUSAGE_CHILDREN)
rec = dict(label=label, rc=rc, wall_s=round(time.time() - t, 1), peak_rss_gb=round(ru.ru_maxrss / 1048576, 2), cmd=sys.argv[3:])
open(out, "a").write(json.dumps(rec) + "\n")
print(json.dumps(rec))
