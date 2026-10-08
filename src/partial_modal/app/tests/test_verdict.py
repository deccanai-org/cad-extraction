#!/usr/bin/env python3
"""unit test (local, reads small JSON files only): the pipeline stage's verdict reproduces job.py's summary for the
bench output folders of the 5 partial samples (every verdict key: steps, parts, status, levels, e2e, reasons, perfect...).

usage: python app/tests/test_verdict.py BENCH_OUT_DIR [BENCH_OUT_DIR ...]
  BENCH_OUT_DIR = a run_local.py output folder holding summary.json + the verification JSON files
"""
import json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from pmpstages.pipeline import make_verdict  # noqa: E402

# keys job.py adds after the verdict (environment / timing) - not part of the verdict
ENV_KEYS = {'id', 'gen', 'stem', 'pid', 'step', 'ifc', 'bytes', 'cls', 'tool', 'J', 'code', 'host', 'iid', 'region', 'itype',
            'seconds', 'finished', 'peak_rss_gb', 'uploaded', 'upload_errors'}

bad = 0
for d in sys.argv[1:]:
    ref = json.load(open(os.path.join(d, 'summary.json')))
    got = make_verdict(d)(ref['steps'])
    want = {k: v for k, v in ref.items() if k not in ENV_KEYS}
    diff = sorted(k for k in set(want) | set(got) if json.dumps(want.get(k), sort_keys=True) != json.dumps(got.get(k), sort_keys=True))
    order_ok = [k for k in ref if k not in ENV_KEYS] == list(got)
    ok = not diff and order_ok
    bad += not ok
    print(f"{'OK ' if ok else 'BAD'} {ref['id'][:16]} perfect={got['perfect']} reasons={got['reasons']} keys={len(got)}"
          + (f' DIFF {diff}' if diff else '') + ('' if order_ok else ' KEY-ORDER differs'))
sys.exit(1 if bad else 0)
