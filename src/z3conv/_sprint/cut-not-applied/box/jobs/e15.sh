#!/bin/bash
# P15 on new engines: per-part bbox vs Tekla IFC, kitnp6 (P1-P14, no P15) = run 0 vs kitnp9 (final, P15) = run 1, fittings on in both
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/e2e_fit_kit.py stage/tools/guid2.py tools/
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
until [ -f kitnp9/.patched ]; do sleep 10; done
export KIT=$W/kitnp6 KIT2=$W/kitnp9 OMP_NUM_THREADS=1
for p in p7.64 p8.53 p8.85 p807_0 p9.08; do
  ( timeout 3600 /opt/conv/ifc84/bin/python tools/e2e_fit_kit.py fit/$p.db1 fit/$p.ifc res/e15/$p > res/e15_$p.txt 2>&1; aws s3 cp --quiet res/e15_$p.txt $OUT/final/e15_$p.txt ) &
done; wait; echo E15DONE
