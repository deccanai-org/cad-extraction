#!/bin/bash
# env + base pipeline for agentjob sds2-weights-failures (idempotent)
set -e
unset LD_LIBRARY_PATH
W=/work/agentwork/sds2-weights-failures; mkdir -p $W && cd $W
aws s3 cp --recursive --only-show-errors s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/sds2-weights-failures/ $W/
if [ ! -x $W/env/bin/python ]; then
  MAMBA_ROOT_PREFIX=$W/mamba /opt/conv/micromamba create -y -q -p $W/env -c conda-forge python=3.12 pip > $W/mamba.log 2>&1
fi
$W/env/bin/python -c "import OCP" 2>/dev/null || $W/env/bin/pip install -q cadquery-ocp==8.0.1.0.0 numpy==2.5.3 scipy==1.18.1 shapely==2.1.2 matplotlib==3.11.2 boto3 > $W/pip.log 2>&1
if [ ! -f $W/v54/sds2-step-pipeline/decode/sds2_to_step.py ]; then
  mkdir -p $W/v54 && cd $W/v54 && $W/env/bin/python -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall('.')" $W/sds2-step-pipeline-v5.4.zip && cd $W
fi
echo "$(sha256sum $W/sds2-step-pipeline-v5.4.zip)"
$W/env/bin/python - <<'PY'
import OCP, numpy, scipy, shapely, matplotlib
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
assert BRepPrimAPI_MakeBox(1, 2, 3).Shape() is not None
print('env ok numpy', numpy.__version__)
PY
