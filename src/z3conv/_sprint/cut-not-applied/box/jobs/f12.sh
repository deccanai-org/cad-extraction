#!/bin/bash
# P12 (eng fittings in the patched code-n kit): end-to-end vs Tekla IFC on the eng fork's truth pairs
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/*.py tools/; mkdir -p fit res/e2e
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
cat stage/fitdl/*.tsv | while IFS=$'\t' read -r n k; do n=$(basename "$n"); [ -s fit/$n ] || aws s3 cp --quiet "s3://bim-proprietary-data/$k" fit/$n; done
ls -la fit
until [ -f kitn/worker.py ]; do sleep 5; done
rm -rf kitnp2; cp -r kitn kitnp2; /opt/conv/env/bin/python stage/patch2/apply_cut_patch.py kitnp2 > res/patch_kitnp2.txt 2>&1 && touch kitnp2/.patched; tail -2 res/patch_kitnp2.txt
export KIT=$W/kitnp2 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
for p in p7.64 p8.53 p8.85 p807_0 p807_1 p9.08 p7.98; do
  [ -s fit/$p.db1 ] && [ -s fit/$p.ifc ] || continue
  ( timeout 3600 /opt/conv/ifc84/bin/python tools/e2e_fit_kit.py fit/$p.db1 fit/$p.ifc res/e2e/$p > res/e2e/$p.txt 2>&1; aws s3 cp --quiet res/e2e/$p.txt $OUT/fit/e2e_$p.txt ) &
done; wait
echo F12DONE
