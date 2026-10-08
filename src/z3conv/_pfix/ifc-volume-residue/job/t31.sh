W=/work/agentwork/ifc-volume-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-volume-residue/ifc2step6_dev3pf.py $W/pkg/ifc2step6_dev3pf.py
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifcv6/ifc2step6_6.0.1.py $W/pkg/ifc2step6_601.py
mkdir -p $W/v601 && cd $W/v601
timeout 300 /opt/conv/env/bin/python $W/pkg/ifc2step6_601.py $W/in/aa33931d26f7b00f.bin $W/v601/aa33.step --mode hybrid --prec 2 --threads 2 > aa33.log 2>&1
/opt/conv/env/bin/python -c "
import json; s=json.load(open('$W/v601/aa33.step.stats.json')); print('6.0.1 aa33', s.get('converter'), 'parts', s.get('parts'), 'nogeom', s.get('parts_without_geometry'), s.get('parts_without_geometry_examples'))"
cd $W && setsid nohup bash $W/pkg/batch.sh dev3pf $W/pkg/ifc2step6_dev3pf.py --jobs 2 --ids aa33931d26f7b00f,224b42bfc48cf6d2 > $W/batch_dev3pf.out 2>&1 < /dev/null &
echo started
