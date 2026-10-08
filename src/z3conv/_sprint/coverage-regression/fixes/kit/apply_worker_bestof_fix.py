#!/usr/bin/env python3
"""coverage-regression fix for the DB1 kit worker.py best-of wrapper (anchor-checked, idempotent).

Bug: process() compares the new run with the stored result only when the stored result's code differs from CODE. When a run of
CODE keeps the earlier STEP, the fleet stamps CODE on the kept record; a duplicate run of the same CODE (two hosts claimed the job
15 s apart) then saw prev.code == CODE and returned its own failure, overwriting the kept STEP:
  7c68f0c9874e  23:17:30 code h ok (101-129) -> 23:18:09 code i crash, h kept (101-187) -> 23:18:24 duplicate code i crash written (102-229)
  -> index row class 3 'source_corrupt_or_decoder_error' although the h STEP (and the f STEP) exist and graded class 2.
Fix: compare whenever the stored result is ok (same-code re-runs included): a better or equal new result still wins (est <=), a
worse one (crash, memory kill -> empty_output) keeps the stored STEP.

usage: apply_worker_bestof_fix.py WORKER.py [OUT.py]
"""
import sys
p = sys.argv[1]; out = sys.argv[2] if len(sys.argv) > 2 else p
s = open(p).read()
old = "    if not prev or prev.get('code') == CODE or prev.get('status') != 'ok':\n        return new\n"
new = ("    # [coverage-regression fix] compare with every ok stored result, also one already stamped with this CODE (a kept earlier\n"
       "    # STEP carries the running code; a duplicate same-code run must not overwrite it with its own failure)\n"
       "    if not prev or prev.get('status') != 'ok':\n        return new\n")
if new in s:
    print('already patched'); open(out, 'w').write(s); sys.exit(0)
assert s.count(old) == 1, 'anchor not found exactly once'
s = s.replace(old, new)
compile(s, out, 'exec')
open(out, 'w').write(s)
print('patched ->', out)
