#!/bin/bash
W=/work/agentwork/sds2-grating-cylinders; cd $W
pkill -f "run_v55.sh"; pkill -f "conv.sh v55 "; pkill -f "sds2-grating-cylinders/v55/sds2-step-pipeline/decode/sds2_to_step.py"; sleep 3
pkill -f "run_rod2.sh"; pkill -f "rod2.py"; sleep 1
ps -eo pid,args | grep "sds2-grating-cylinders/v55/" | grep -v grep | wc -l
rm -rf out/v55 v55; mkdir -p v55
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-grating-cylinders/v55sgc.tgz .
tar xzf v55sgc.tgz -C v55; grep -c "0.6 < abs(g.Mass())" v55/sds2-step-pipeline/decode/to_step2.py
aws s3 rm --quiet --recursive s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-grating-cylinders/conv/v55/
setsid nohup bash run_v55.sh > run_v55.out 2>&1 < /dev/null &
# rod replay: v55 only (base54 results kept)
cat > run_rod2b.sh <<'EOS'
#!/bin/bash
W=/work/agentwork/sds2-grating-cylinders; cd $W
export LD_PRELOAD=/work/agentwork/sds2v54/env/lib/libexpat.so.1
rm -rf rod2/v55; mkdir -p rod2/v55 rod2/base54
for d in jobs/*/; do n=$(basename $d); [ -f $d/subm/subm_idx ] || continue
  echo "v55 $n"; [ -f rod2/base54/$n.json ] || echo "base54 $n"
done | xargs -P 3 -L 1 bash -c 'timeout 3000 env/bin/python rod2.py $0/sds2-step-pipeline jobs/$1 rod2/$0/$1.json >> logs/rod2.log 2>&1'
aws s3 cp --recursive --quiet rod2 s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-grating-cylinders/rod2/
echo done > logs/rod2.done; aws s3 cp --quiet logs/rod2.done s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/sds2-grating-cylinders/logs/rod2.done
EOS
setsid nohup bash run_rod2b.sh > run_rod2b.out 2>&1 < /dev/null &
echo restarted
