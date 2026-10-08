#!/usr/bin/env python3
"""post.py (box, in /work/agentwork/step-verify-big): collect the final-pass readback records of every streamed flagged model into
final/results/<jid>.json + final/detail/<jid>.step_parts.jsonl.gz (the layout of _state/conv/final/), a per-model table
(final/models.json) and the run statistics (final/runs.json: bytes, wall, cpu, peak memory per streamed run)."""
import os, sys, json, glob, shutil, gzip

W = os.getcwd()
os.makedirs('final/results', exist_ok=True); os.makedirs('final/detail', exist_ok=True)
targets = json.load(open('pkg/targets.json'))
tags = dict(targets['flagged'])
for x in targets['phase3']:
    tags[x['tag']] = x['id']
rows = []; runs = []
for tag, mid in sorted(tags.items()):
    rec_p = f'out/{tag}/final_readback_x24.json'
    sj = f'out/{tag}/s_x24.json'; sp = f'out/{tag}/s_x24.parts.jsonl.gz'
    ru = f'logs/s_{tag}_x24.rusage.json'
    row = {'tag': tag, 'id': mid}
    if os.path.exists(ru):
        r = json.load(open(ru)); row.update(state=r.get('state'), rc=r.get('rc'), wall_sec=r.get('wall_sec'), cpu_sec=r.get('cpu_sec'))
    if os.path.exists(sj):
        v = json.load(open(sj)); s = v.get('streamed') or {}
        row.update({k: v.get(k) for k in ('bytes', 'read_status', 'roots', 'transferred', 'empty_roots', 'solids', 'shells', 'faces',
                                           'invalid', 'nonpos_vol', 'nonfinite', 'sampled')})
        row.update(complete=s.get('complete'), chunks=s.get('chunks_run'), resplit=s.get('chunks_resplit'), crashed_roots=s.get('crashed_roots'),
                   peak_tree_mb=round((s.get('peak_tree_rss_bytes') or 0) / 2**20), peak_worker_mb=round((s.get('peak_worker_rss_bytes') or 0) / 2**20),
                   tol_gt_0p1mm=s.get('parts_tol_gt_0p1mm'), sec=v.get('sec'), text_sec=v.get('text_sec'))
        runs.append({k: row.get(k) for k in ('tag', 'bytes', 'wall_sec', 'cpu_sec', 'chunks', 'peak_tree_mb', 'peak_worker_mb', 'text_sec')})
    if os.path.exists(rec_p) and os.path.exists(sp):
        rec = json.load(open(rec_p))
        shutil.copy(rec_p, f'final/results/{rec["id"]}.json')
        shutil.copy(sp, f'final/detail/{rec["id"]}.step_parts.jsonl.gz')
        j = rec.get('join') or {}
        row.update(final_id=rec['id'], join_mode=j.get('mode'), coverage_all=(j.get('coverage') or {}).get('all'),
                   surface_parts=j.get('surface_parts'), step_parts_unmatched=j.get('step_parts_unmatched'),
                   volume={k: (j.get('volume') or {}).get(k) for k in ('checked', 'within_5pct', 'outside_5pct', 'outside_curved', 'outside_curved_gross')})
    rows.append(row)
json.dump(rows, open('final/models.json', 'w'), indent=1)
json.dump(runs, open('final/runs.json', 'w'), indent=1)
tb = sum(r.get('bytes') or 0 for r in runs); tc = sum(r.get('cpu_sec') or 0 for r in runs); tw = sum(r.get('wall_sec') or 0 for r in runs)
print(json.dumps({'models': len(rows), 'with_record': sum(1 for r in rows if r.get('final_id')), 'read_ok': sum(1 for r in rows if r.get('read_status') == 'ok'),
                  'complete': sum(1 for r in rows if r.get('complete')), 'bytes_gb': round(tb / 2**30, 2), 'cpu_sec': round(tc), 'cpu_sec_per_mb': round(tc / max(1, tb / 2**20), 3),
                  'wall_sec_sum': round(tw), 'max_peak_tree_mb': max((r.get('peak_tree_mb') or 0 for r in rows), default=0)}))
