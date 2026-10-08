CTL=s3://annotationprod/cad-disk-extract/_control/z3conv/db1/v2/_box
until [ -f /opt/v2/ENV_READY ]; do sleep 20; done
mkdir -p /opt/v2/code && aws s3 sync --quiet $CTL/code/ /opt/v2/code/
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/db1/tekla_profiles.json /opt/v2/code/tekla_profiles.json
aws s3 cp --quiet $CTL/val_one.sh /opt/v2/val_one.sh; aws s3 cp --quiet $CTL/val_pairs.json /opt/v2/val_pairs.json
cd /opt/v2
python3 -c "
import json
for s in json.load(open('val_pairs.json')): print(s['tag'] + '\t' + s['db1'] + '\t' + s['ifc'])
" > val_pairs.tsv
export RUN=r1
cat val_pairs.tsv | xargs -P 6 -d '\n' -I{} bash -c 'IFS=$(printf "\t"); set -- {}; bash /opt/v2/val_one.sh "$1" "$2" "$3"'
echo all done
