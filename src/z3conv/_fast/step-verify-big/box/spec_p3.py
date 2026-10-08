#!/usr/bin/env python3
"""spec_p3.py OUT_SPEC.json: equivalence spec for the phase-3 models (box cwd): the streamed parts vs the grader's stored per-part
read-back (ref/<tag>.ec2.step_parts.jsonl.gz: the full step_check run of the IFC worker that completed its OCC loop before it
was memory-killed), for every model that has both."""
import os, sys, json

t = json.load(open('pkg/targets.json'))
spec = {}
for x in t['phase3']:
    tag = x['tag']
    ref = f'ref/{tag}.ec2.step_parts.jsonl.gz'; sp = f'out/{tag}/s_x24.parts.jsonl.gz'
    if os.path.exists(ref) and os.path.getsize(ref) > 0 and os.path.exists(sp):
        spec[tag] = {'full': [['-', ref, 'grader_ec2_parts']], 'stream': [[f'out/{tag}/s_x24.json', sp, 's_x24']]}
json.dump(spec, open(sys.argv[1], 'w'), indent=1)
print(len(spec), 'models with a stored grader read-back')
