W=/work/agentwork/ifc-volume-residue; export KIT=$W/pkg/kit AWS_DEFAULT_REGION=ap-south-1
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-volume-residue/attrib.py $W/pkg/attrib.py
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-volume-residue/attrib_all.sh $W/pkg/attrib_all.sh
cat $W/w/dev3/progress.jsonl 2>/dev/null | cut -c1-400
ls $W/w/dev3/
d=$W/w/dev3/aa33931d26f7b00f; ls $d
timeout 300 /opt/conv/env/bin/python $W/pkg/attrib.py $d /tmp/attr_test.json --max 50 --all-sample 3 2>&1 | tail -5
/opt/conv/env/bin/python -c "
import json; d=json.load(open('/tmp/attr_test.json'))
for p in d['parts'][:6]: print(json.dumps(p)[:900])
"
