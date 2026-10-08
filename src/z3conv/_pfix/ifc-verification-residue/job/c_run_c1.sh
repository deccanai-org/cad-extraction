#!/bin/bash
# ifc-verification-residue on BOX-C: SDS2 valueerror (mem_idx) diagnosis; small jobs only
export AWS_DEFAULT_REGION=ap-south-1
W=/work/agentwork/ifc-verification-residue; mkdir -p $W/sds2 && cd $W/sds2
S=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifc-verification-residue/sds2
aws s3 cp --quiet --recursive $S/ . 
for v in v5.4 v5.5.3; do [ -d $v ] || { mkdir -p $v && (cd $v && aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/sds2/sds2-step-pipeline-$v.zip z.zip && /opt/conv/env/bin/python -c "import zipfile;zipfile.ZipFile('z.zip').extractall('.')" && rm z.zip); }; done
PY=/opt/conv/env/bin/python
for j in a47a130792964d28:a47a130792964d283c4b9ab9a404404c9906689f111c6b20a479ef2b52d341c0 58c969614e6f06bd:58c969614e6f06bde4ab3d44c4d6d681d2473568cef4565cdabcd3c06df72b74; do
  id=${j%%:*}; fpc=${j#*:}
  if [ ! -d jobs/$id ]; then
    $PY mkfetch.py $id cad-disk-extract/zenitude-data-3/_state/conv/sds2/files/$fpc.json.gz $W/sds2/jobs/$id
    $PY fetch.py fetch_$id.json 32
  fi
done
SPY=/work/agentwork/sds2v54/env/bin/python
for id in a47a130792964d28 58c969614e6f06bd; do
  JD=$(dirname $(find jobs/$id -name mem_idx | head -1))/..
  echo "=== $id $JD"; ls $JD; 
  $SPY diag_mem.py $W/sds2/v5.4/sds2-step-pipeline/decode $JD 2>&1 | tail -60
done
