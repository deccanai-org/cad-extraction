#!/usr/bin/env python3
"""fetch a few jobs (via diag.fetch) and run misc_probe.py on each; outputs to agentwork/audit-sds2-pipeline/diag/misc/"""
import os, sys, json, shutil, subprocess
sys.argv = [sys.argv[0]]
import diag
out = f'{diag.D}/misc'; os.makedirs(out, exist_ok=True)
for jid in ('b244541c34043e8c7783bd42', 'c48a9d620b77c3b582dfe2e6', 'ade4790fed14255c6f3dab7a'):
    try:
        jd, fs = diag.fetch(jid, 'job_' + jid[:6])
        rc, sec = diag.run([diag.PY, f'{diag.W}/misc_probe.py', diag.PIPE, jd, f'{out}/{jid}.json'], f'{out}/{jid}.log', 2400)
        diag.log('misc', jid[:12], fs, rc, sec)
        for f in (f'{jid}.json', f'{jid}.log'):
            if os.path.exists(f'{out}/{f}'):
                diag.put(f'{out}/{f}', f'misc/{f}')
    finally:
        shutil.rmtree(f'{diag.D}/jobs/{jid}', ignore_errors=True)
