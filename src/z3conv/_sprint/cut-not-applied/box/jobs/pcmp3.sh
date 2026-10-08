#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/*.py tools/
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
export PIPE_A=pipes2/kit2 PIPE_B=pipes2/kitp2
IDS=$(for d in pipes2/kitp2/*; do i=$(basename $d); [ -f pipes2/kit2/$i/pipe.json ] && [ -f $d/pipe.json ] && echo $i; done)
/opt/conv/env/bin/python tools/pipe_cmp.py $IDS > res/pipe_cmp2.txt 2>&1; cp res/pipe_cmp.json res/pipe_cmp2.json
export PIPE_B=pipes2/kitp3
/opt/conv/env/bin/python tools/pipe_cmp.py e151a8faacbce446 575da79b6096c760 > res/pipe_cmp3.txt 2>&1; cp res/pipe_cmp.json res/pipe_cmp3.json
/opt/conv/env/bin/python tools/convall_sum.py > res/convall_sum.txt 2>&1
for f in pipe_cmp2.txt pipe_cmp2.json pipe_cmp3.txt pipe_cmp3.json; do aws s3 cp --quiet res/$f $OUT/pipes2/$f; done; aws s3 cp --quiet res/convall_sum.txt $OUT/convall/convall_sum.txt
python3 - <<'P'
import json
for f in ('res/pipe_cmp2.json', 'res/pipe_cmp3.json'):
    d = json.load(open(f))
    for i, r in d.items():
        rep = r.get('report') or {}
        print(f[-6:-5], i[:16], r['engine'], 'written', r['written'], 'applied', r['cuts_applied'], 'unbuilt', r['cut_body_unbuilt'], 'solids', r['solids'], 'invalid', r['invalid'], 'nonpos', r['nonpos'],
              'cov', r['join_cov'], 'phantoms', r['phantom_parts_no_longer_steel'], r['phantom_kg'], 'kg | recovered', r['recovered_parts'], r['recovered_kg'], 'kg | removed', r['removed_kg'], 'kg on', r['parents_material_removed'],
              'noeff', r['parents_cut_no_effect'], 'grew', r['parents_volume_grew'], '| report kg err', rep.get('abs_kg_err_report_buckets'), 'count err', rep.get('abs_count_err_all'))
P
grep -A12 "PER ENGINE" res/convall_sum.txt
