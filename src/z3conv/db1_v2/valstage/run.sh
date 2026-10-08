#!/bin/bash
SLUG=db1v2-val; W=/work/agentwork/$SLUG; mkdir -p $W; cd $W
aws s3 cp --quiet --recursive s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/$SLUG/ .
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/db1/tekla_profiles.json code/tekla_profiles.json
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/$SLUG
cat > driver.sh <<'L'
#!/bin/bash
W=/work/agentwork/db1v2-val; cd $W; OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/db1v2-val
export RUN=${RUN:-r2}
python3 -c "import json; [print(k) for k in json.load(open('val_keys.json'))]" > tags.txt
# RE probes (8.85 / 9.08 / 8.65 bolt storage)
mkdir -p re; for T in 8.85_Amazon_IAD_192 9.08_ASV_Brain_and_Spine 8.85_TORAY 9.08_I8973 8.65_19058_Giorgi_USA; do
  ( D=$W/$RUN/$T; mkdir -p $D; cd $D
    DB1=$(python3 -c "import json,sys; print(json.load(open('$W/val_keys.json'))[sys.argv[1]][0])" "$T"); IFC=$(python3 -c "import json,sys; print(json.load(open('$W/val_keys.json'))[sys.argv[1]][1])" "$T")
    [ -f in.db1 ] || aws s3 cp --quiet "s3://bim-proprietary-data/$DB1" in.db1; [ -f in.ifc ] || aws s3 cp --quiet "s3://bim-proprietary-data/$IFC" in.ifc
    cd $W/code && /opt/conv/env/bin/python probe28.py $D/in.db1 $D/in.ifc > $W/re/$T.p28.txt 2>&1; /opt/conv/env/bin/python probe26.py $D/in.db1 >> $W/re/$T.p28.txt 2>&1
    aws s3 cp --quiet $W/re/$T.p28.txt $OUT/re/$T.p28.txt ) &
done
cat tags.txt | xargs -P 10 -I{} bash $W/val_one.sh {} > val.log 2>&1
wait
aws s3 cp --quiet val.log $OUT/$RUN/val.log
# pair scan resume (IO-bound)
aws s3 cp --quiet s3://bim-proprietary-data/cad-disk-extract/_work/db1_v2/pairscan.jsonl pairscan.jsonl
( python3 pairscan.py pairscan_jobs.json pairscan.jsonl 32 > pairscan.log 2>&1; aws s3 cp --quiet pairscan.jsonl $OUT/pairscan.jsonl ) &
PS=$!
while kill -0 $PS 2>/dev/null; do sleep 120; aws s3 cp --quiet pairscan.jsonl $OUT/pairscan.jsonl; done
echo finished > FINISHED; aws s3 cp --quiet FINISHED $OUT/$RUN/FINISHED
L
chmod +x driver.sh val_one.sh
RUN=r2 setsid nohup ./driver.sh > driver.log 2>&1 < /dev/null &
echo started
