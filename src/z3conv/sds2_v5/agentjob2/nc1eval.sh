#!/bin/bash
W=/work/agentwork/sds2v54; cd $W; export AWS_DEFAULT_REGION=ap-south-1 PYTHONUNBUFFERED=1
C=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2v54
R=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2v54/nc1
aws s3 cp --quiet $C/nc1eval.py $W/nc1eval.py
IDS="${IDS:-fcf299e7ec29c9e7855f6f21 47623a2db739778a1c12e4e8 7295a33071b1b76a8b170f45 5c14d28b72279c81a73598d9 d8ef5d5e4fed5236833c68a4 2906268b27dbda74a63a44c9 b510500759d5f020ed770ee9 1b0ba8c2de7aaa501434f768 296c9ee970562e0d9b112681 79c7150a6ce51974b15efd16 11a5ca94a63e022fe56ed5c4 c378495add3301e90f474ae8 682950444dce54947baadc42 5eb03132f13a55070a3a2a0f 425c2f6c4282287cc9ffdc30 14e9abeada53532312d44d0c 22cd96c43571afda7a2716a9 7b40c0c5683f62cc2f382c90 6e9e3214c04ce23fdda24038 155c96b42bc64cdfe9dbb3f9 24d639fb069456e1ed2194a1 ce12e46e1fd05535b1e0c109 0f2459445bf1c3abc26909c3 85d4cbd8176222b0900afdf8}"
$W/env/bin/python - $IDS <<'P'
import json, sys
d = json.load(open('/work/agentwork/sds2-recall-nc1/inv/pairs.json'))
json.dump({i: [e for e in d[i]['nc1_files'] if e.get('key')] for i in sys.argv[1:] if i in d}, open('/work/agentwork/sds2v54/nc1/eval_pairs.json', 'w'))
P
mkdir -p $W/jobs_nc1; rm -f $W/nc1/nc1eval2.jsonl
echo $IDS | tr ' ' '\n' | xargs -P 4 -n 1 timeout 3600 $W/env/bin/python $W/nc1eval.py $W/v553b/sds2-step-pipeline/decode $W/nc1/nc1eval2.jsonl > $W/nc1/nc1eval2.out 2>&1
aws s3 cp --quiet $W/nc1/nc1eval2.jsonl $R/nc1eval2.jsonl
date -u +%FT%TZ > $W/NC1EVAL2_DONE; aws s3 cp --quiet $W/NC1EVAL2_DONE $R/NC1EVAL2_DONE
