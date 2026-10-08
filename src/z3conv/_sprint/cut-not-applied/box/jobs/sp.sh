#!/bin/bash
cd /work/agentwork/cut-not-applied; python3 -c "
import gzip, json
for i, l in enumerate(gzip.open('pipes5/kitnp7/0762effe61de88c0/step_parts.jsonl.gz', 'rt')):
    print(l[:400])
    if i > 1: break"
