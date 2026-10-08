#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
for id in 0762effe61de88c0 e151a8faacbce446 6304887153755ea3 575da79b6096c760 1d8972fb557e3371 truth_iron truth_gsk 6eabb07e71459be6 a94442572f225f50 4518a79a995bdee0; do
  [ -f pipes5/kitn/$id/pipe.json ] && [ -f pipes5/kitnp9/$id/pipe.json ] || continue
  PIPE_A=pipes5/kitn PIPE_B=pipes5/kitnp9 /opt/conv/env/bin/python tools/pipe_cmp.py $id 2>&1 | grep "^{"
done > res/pipecmp_partial.jsonl
python3 - <<'P'
import json
for l in open('res/pipecmp_partial.jsonl'):
    r = json.loads(l); rep = r.get('report') or {}
    print(r['id'][:16], r['engine'], 'written', r['written'], 'applied', r['cuts_applied'], 'unbuilt', r['cut_body_unbuilt'], 'solids', r['solids'], 'invalid', r['invalid'], 'nonpos', r['nonpos'],
          'step_rc', r['step_rc'], 'join_cov', r['join_cov'], 'vol>5%', r['vol_outside_5pct'], 'phantom', r['phantom_parts_no_longer_steel'], r['phantom_kg'], 'kg recovered', r['recovered_parts'], r['recovered_kg'], 'kg',
          'removed_kg', r['removed_kg'], 'grew', r['parents_volume_grew'], '| report err', rep.get('abs_kg_err_report_buckets'))
P
aws s3 cp --quiet res/pipecmp_partial.jsonl $OUT/final/pipecmp_partial.jsonl
