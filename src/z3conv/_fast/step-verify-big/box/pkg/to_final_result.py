#!/usr/bin/env python3
"""Package a step_verify_big.py result as a final-pass readback result (format of grade/worker.py final_job, kind 'readback'),
so that coord/build_index.py apply_final() overlays it: validate (+ join against the model's source inventory when given).
usage: to_final_result.py OUT.json PARTS.jsonl.gz --pipeline ifc --model-id ID --step-key KEY [--src-parts SRC.jsonl.gz]
                          [--grade-join PATH/grade_join.py] -o RESULT.json
The record is written locally only; uploading it to the bim bucket is for whoever owns _state/conv/final/."""
import sys, os, json, argparse, importlib.util, time

ROOT = 'cad-disk-extract/zenitude-data-3'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out'); ap.add_argument('parts')
    ap.add_argument('--pipeline', required=True); ap.add_argument('--model-id', required=True); ap.add_argument('--step-key', required=True)
    ap.add_argument('--src-parts'); ap.add_argument('--grade-join', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ref', 'grade_join.common.py'))
    ap.add_argument('-o', required=True)
    a = ap.parse_args()
    v = json.load(open(a.out))
    jid = f'f-{a.pipeline}-{a.model_id[:40]}-readback'
    rec = {'pipeline': a.pipeline, 'model_id': a.model_id, 'final_kind': 'readback', 'step_key': a.step_key,
           'validate': {k: x for k, x in v.items() if k != 'invalid_examples'}, 'id': jid}
    rec['validate']['invalid_examples'] = (v.get('invalid_examples') or [])[:10]
    rec['validate']['step_bytes'] = v.get('bytes')
    rec['step_parts_key'] = f'{ROOT}/_state/conv/final/detail/{jid}.step_parts.jsonl.gz'
    if a.src_parts:
        spec = importlib.util.spec_from_file_location('grade_join', a.grade_join)
        gj = importlib.util.module_from_spec(spec); spec.loader.exec_module(gj)
        rec['join'] = gj.join(gj.load(a.src_parts), gj.load(a.parts))
    rec['status'] = 'ok'
    rec['by'] = (v.get('streamed') or {}).get('version')
    rec['finished'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    json.dump(rec, open(a.o, 'w'), indent=1)
    j = rec.get('join') or {}
    print(json.dumps({'id': jid, 'read_status': v.get('read_status'), 'solids': v.get('solids'), 'invalid': v.get('invalid'),
                      'nonpos_vol': v.get('nonpos_vol'), 'join_mode': j.get('mode'), 'coverage': j.get('coverage'),
                      'volume': {k: (j.get('volume') or {}).get(k) for k in ('checked', 'within_5pct', 'outside_5pct', 'outside_curved')}}))


if __name__ == '__main__':
    sys.exit(main())
