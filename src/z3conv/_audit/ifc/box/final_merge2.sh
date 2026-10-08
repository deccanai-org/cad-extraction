#!/bin/bash
cd /work/agentwork/audit-ifc
left=""
for p in $(ls /proc | grep -E '^[0-9]+$'); do
  [ "$p" = "$$" ] && continue
  c=$(readlink /proc/$p/cwd 2>/dev/null)
  case "$c" in /work/agentwork/audit-ifc*) left="$left $p";; esac
done
echo "remaining own pids (excluding this shell):$left"
/opt/conv/env/bin/python - <<'PY'
import os, gzip
W='/work/agentwork/audit-ifc'
n=0
with gzip.open(W+'/scan.jsonl.gz','wt') as f:
    for x in sorted(os.listdir(W+'/out')):
        if x.endswith('.json'):
            f.write(open(W+'/out/'+x).read().strip()+'\n'); n+=1
print('merged', n)
PY
aws s3 cp --quiet scan.jsonl.gz s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/audit-ifc/scan.jsonl.gz
echo '{"phase": "merged-final", "note": "3 class-1 models not scanned: kernel booleans on perforated plates exceeded the per-model timeout"}' | aws s3 cp - s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/audit-ifc/progress.json
rm -rf src src2 proofs proofs2 v61/src
du -sh /work/agentwork/audit-ifc
