#!/bin/bash
# own SDS2 converter env (python 3.12 + the pipeline's pinned requirements) and both converter builds (v4c, v5.3)
set -e
W=/work/agentwork/sds2-recall-nc1
cd $W
unset LD_LIBRARY_PATH
if [ ! -x $W/sds2env/bin/python ]; then
  MAMBA_ROOT_PREFIX=$W/mamba /opt/conv/micromamba create -y -q -p $W/sds2env -c conda-forge python=3.12 pip > $W/logs/mamba.log 2>&1
fi
for z in sds2-step-pipeline-v5.3.zip sds2-step-pipeline-v4-candidate.zip; do
  aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/sds2/$z $W/$z || true
done
ls -la $W/*.zip
sha256sum $W/*.zip
mkdir -p $W/conv/v5.3 $W/conv/v4c
[ -f $W/conv/v5.3/sds2-step-pipeline/decode/sds2_to_step.py ] || $W/sds2env/bin/python -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" $W/sds2-step-pipeline-v5.3.zip $W/conv/v5.3
[ -f $W/conv/v4c/sds2-step-pipeline/decode/sds2_to_step.py ] || $W/sds2env/bin/python -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" $W/sds2-step-pipeline-v4-candidate.zip $W/conv/v4c
$W/sds2env/bin/pip install -q -r $W/conv/v5.3/sds2-step-pipeline/requirements.txt boto3 > $W/logs/pip.log 2>&1
$W/sds2env/bin/python -c "import OCP, numpy, scipy, shapely; from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox; print('env ok', numpy.__version__)"
