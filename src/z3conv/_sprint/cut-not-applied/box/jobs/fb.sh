#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W
for d in pipes/kitp/e151a8faacbce446 pipes/kit/e151a8faacbce446 pipes/kitp/6a44b409f977d7c2; do echo "== $d"; [ -f $d/step_parts.jsonl.gz ] && /opt/conv/env/bin/python tools/fb_bbox.py $d/step_parts.jsonl.gz; done
