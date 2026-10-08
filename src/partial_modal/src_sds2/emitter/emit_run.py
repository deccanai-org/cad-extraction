#!/usr/bin/env python3
"""Run one SDS/2 conversion exactly as the conversion fleet did (decode/sds2_to_step.py JOB -o OUT --stage 2 --verify)
with two sets of hooks installed, neither of which changes what the converter computes or writes (proof: the STEP
written is compared byte for byte with the shipped STEP by the caller):

  sds2ifc.install      the published IFC emitter 1.1 (unchanged file): writes OUT.ifc from the XCAF document the final
                       STEP was written from, plus OUT_ifc_emit.json / OUT_ifc_products.jsonl
  facts_hooks.install  side tables for the issue maker: OUT_facts_instances.jsonl (every top-level instance of the
                       STEP: GlobalId, label, world placement, bounding box, cut hole tools), OUT_facts_convert.json
                       (the converter's stats, decoded holes per piece, skipped pieces with the geometry the SDS/2 job
                       records for them, every member with its work line)

Adapted from nonifc/sds2_emitter/emit_run.py (same argument handling); the converter's exit status is kept.
usage: emit_run.py CONVERTER_ROOT JOB -o OUT --stage 2 --verify --model-id ID --shipped-sha256 SHA --converter 'LABEL ZIP SHA'"""
import os, sys, runpy
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
conv = os.path.abspath(sys.argv[1])
args = sys.argv[2:]


def take(flag):
    i = args.index(flag)
    v = args[i + 1]
    del args[i:i + 2]
    return v


meta = dict(model_id=take('--model-id'), shipped_sha256=take('--shipped-sha256'), converter=take('--converter'))
out = args[args.index('-o') + 1]
meta['job'] = os.path.abspath(args[0])
import sds2ifc  # noqa: E402
sds2ifc.install(conv, out, meta)
import facts_hooks  # noqa: E402
facts_hooks.install(conv, out, meta)
sys.argv = [os.path.join(conv, 'decode', 'sds2_to_step.py')] + args
rc = 0
try:
    runpy.run_path(sys.argv[0], run_name='__main__')
except SystemExit as e:
    rc = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    if not isinstance(e.code, int) and e.code is not None:
        print('converter exit:', e.code)
sys.stdout.flush()
sys.exit(rc)
