W=/work/agentwork/ifc-volume-residue
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-volume-residue/bisect_mem.py $W/pkg/bisect_mem.py
cd $W/diag761 && setsid nohup bash -c "timeout 3000 /opt/conv/env/bin/python $W/pkg/bisect_mem.py $W/pkg/ifc2step6_dev3.py $W/w/dev3/761b25e0fe15219f/in.bin 4 120 6 > bisect.json 2> bisect.log; aws s3 cp --quiet bisect.json s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-volume-residue/diag/bisect761.json; aws s3 cp --quiet bisect.log s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-volume-residue/diag/bisect761.log" > /dev/null 2>&1 < /dev/null &
echo started
