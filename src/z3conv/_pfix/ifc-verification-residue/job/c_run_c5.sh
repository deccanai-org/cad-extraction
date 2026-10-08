#!/bin/bash
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue/sds2; cd $W
cat > bg.sh <<'EOS'
#!/bin/bash
W=/work/agentwork/ifc-verification-residue/sds2; cd $W
PY=/opt/conv/env/bin/python; SPY=/work/agentwork/sds2v54/env/bin/python
id=332cb8a3d530bf3aba509ff9; fpc=332cb8a3d530bf3aba509ff975f13826d08d2b44c3e44e229c27ab09c07e8db0
if [ ! -f jobs/$id.fetched ]; then $PY mkfetch2.py $id $fpc $W/jobs/$id && $PY fetch.py fetch_$id.json 32 > jobs/$id.fetch.json && touch jobs/$id.fetched; fi
JD=$(cd $(dirname $(find jobs/$id -name mem_idx | head -1))/.. && pwd)
export PYTHONUNBUFFERED=1 MPLBACKEND=Agg
[ -f /work/agentwork/sds2v54/env/lib/libexpat.so.1 ] && export LD_PRELOAD=/work/agentwork/sds2v54/env/lib/libexpat.so.1
o=$W/out/v5.5.3/$id; mkdir -p $o; cd $o
# memory guard for this run only (kill > 40 GB RSS)
( while sleep 5; do p=$(pgrep -f "out/v5.5.3/$id/job_stage2.step" | head -1); [ -z "$p" ] && continue; r=$(awk '/VmRSS/{print $2}' /proc/$p/status 2>/dev/null); [ -n "$r" ] && [ "$r" -gt 41943040 ] && { echo "guard kill rss=$r" >> $o/guard.txt; kill -9 $p; }; done ) &
G=$!
/usr/bin/time -v timeout 10800 $SPY -u $W/v5.5.3/sds2-step-pipeline/decode/sds2_to_step.py "$JD" -o $o/job_stage2.step --stage 2 --verify > $o/log.txt 2> $o/err.txt
echo "rc=$?" > $o/rc.txt; kill $G
grep -v "^\*\|Transferr" $o/log.txt | tail -40 > $o/log_tail.txt
for f in rc.txt log_tail.txt err.txt job_stage2_manifest.json guard.txt; do [ -f $o/$f ] && aws s3 cp --quiet $o/$f s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-verification-residue/sds2_bg/$id/$f; done
EOS
setsid nohup bash bg.sh > bg.log 2>&1 < /dev/null &
echo launched $!
# upload 7.243 outputs summary
for f in $(find out/v5.4 out/v5.4ivr out/v5.5.3ivr -name '*manifest.json' -o -name log.txt -o -name '*_pieces.csv' | grep -v 332cb8a3); do aws s3 cp --quiet $f s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-verification-residue/sds2_7243/$f; done
aws s3 cp --quiet out/summary.txt s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-verification-residue/sds2_7243/summary.txt
echo uploaded
