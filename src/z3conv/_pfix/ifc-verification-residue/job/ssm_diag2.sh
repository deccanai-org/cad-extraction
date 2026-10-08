#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue/diag_far.py $W/job/diag_far.py
cd $W
P=/opt/conv/env/bin/python
timeout 600 $P $W/job/diag_far.py $W/job/ifc2step6_dev3.py $W/in/c13135ba64e2e8fd.bin 0_Aurq9PnFi99OUJ6HJXZq > $W/diag/far2_c131.jsonl 2> $W/diag/far2_c131.err
timeout 600 $P $W/job/diag_far.py $W/job/ifc2step6_dev3.py $W/in/4f6b8e2e96937507.bin 0Dcno5GC10KvAeo5hL2xEF > $W/diag/far2_4f6b.jsonl 2> $W/diag/far2_4f6b.err
timeout 600 $P $W/job/diag_far.py $W/job/ifc2step6_dev3.py $W/in/6f3ceef9bdcb1a56.bin 1zVeLVTnz5cf0on7n7LpQl 3ba3WXXxr7ZORBCV0kgw5D 0fB6h020TFi8KebFAmf8t8 > $W/diag/far2_6f3c.jsonl 2> $W/diag/far2_6f3c.err
python3 -c "
import json,glob
for fn in sorted(glob.glob('$W/diag/far2_*.jsonl')):
    for l in open(fn):
        r=json.loads(l)
        for k in ('tc','kernel_poly','kernel_tri'):
            v=r.get(k)
            if isinstance(v,dict):
                print(r['gid'], r['name'], k, 'in_place', v['in_place']['verdict'], v['in_place']['brepcheck'], '| shifted', v['shifted']['verdict'], '| mapped', v['mapped_translation']['verdict'], v['mapped_translation']['brepcheck'], v['mapped_translation']['occ_vols'], v['mesh_vol'] if 'mesh_vol' in v else v['in_place']['mesh_vol'])
"
aws s3 cp --quiet --recursive $W/diag/ s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-verification-residue/diag/
