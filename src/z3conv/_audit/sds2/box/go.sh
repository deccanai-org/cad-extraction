#!/bin/bash
# background: env + converter setup, then diagnostics (all under /work/agentwork/audit-sds2-pipeline)
W=/work/agentwork/audit-sds2-pipeline
cd $W
echo "$(date -u +%FT%TZ) go start" >> go.log
aws s3 cp s3://annotationprod/cad-disk-extract/_control/z3conv/sds2/sds2-step-pipeline-v5.3.zip . --quiet --region ap-south-1
echo "81ca1f95dbb3bb2e115574045e4cd0e20a8ff067242655f1d1c7eb59ca8d9822  sds2-step-pipeline-v5.3.zip" | sha256sum -c - >> go.log 2>&1 || exit 1
rm -rf v53 && mkdir v53 && (cd v53 && /opt/conv/env/bin/python -c "import zipfile;zipfile.ZipFile('../sds2-step-pipeline-v5.3.zip').extractall('.')")
if [ ! -x env/bin/python ]; then
  MAMBA_ROOT_PREFIX=$W/mamba /opt/conv/micromamba create -y -q -p $W/env -c conda-forge python=3.12 pip > mamba.log 2>&1
  env/bin/pip install -q -r v53/sds2-step-pipeline/requirements.txt > pip.log 2>&1
fi
env/bin/python -c "import OCP, numpy, scipy; from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox; print('env ok', numpy.__version__)" >> go.log 2>&1 || { tail -20 pip.log >> go.log; exit 1; }
echo "$(date -u +%FT%TZ) env ready" >> go.log
aws s3 cp go.log s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/audit-sds2-pipeline/diag/go.log --quiet --region ap-south-1
/opt/conv/env/bin/python diag.py "$@" > diag.log 2>&1
echo "$(date -u +%FT%TZ) diag exit $?" >> go.log
aws s3 cp go.log s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/audit-sds2-pipeline/diag/go.log --quiet --region ap-south-1
aws s3 cp diag.log s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/audit-sds2-pipeline/diag/diag.log --quiet --region ap-south-1
