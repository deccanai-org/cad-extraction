#!/bin/bash
W=/work/agentwork/sds2-grating-cylinders; cd $W
A=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-grating-cylinders
aws s3 cp --quiet $A/tube1.py . ; aws s3 cp --quiet $A/v553sgc.tgz . && rm -rf v553sgc && mkdir -p v553sgc && tar xzf v553sgc.tgz -C v553sgc
grep -c round_tube_local v553sgc/sds2-step-pipeline/decode/to_step2.py
mkdir -p tube1
cat > run_tube1.sh <<'EOS'
#!/bin/bash
W=/work/agentwork/sds2-grating-cylinders; cd $W
for d in jobs/*/; do n=$(basename $d); [ -f $d/subm/subm_idx ] && echo $n; done | xargs -P 3 -I{} bash -c 'timeout 2400 env/bin/python tube1.py v553sgc/sds2-step-pipeline jobs/{} tube1/{}.json >> logs/tube1.log 2>&1'
aws s3 cp --recursive --quiet tube1 s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-grating-cylinders/tube1/
aws s3 cp --quiet logs/tube1.log s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-grating-cylinders/logs/tube1.log
echo done > logs/tube1.done; aws s3 cp --quiet logs/tube1.done s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-grating-cylinders/logs/tube1.done
EOS
setsid nohup bash run_tube1.sh > run_tube1.out 2>&1 < /dev/null &
echo launched
