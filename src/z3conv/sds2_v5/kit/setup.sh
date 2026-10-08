#!/bin/bash
# Build the SDS/2 conversion environment on a fresh Linux x86_64 host (AL2023 or Ubuntu 22.04/24.04); idempotent.
#   $W/sds2env : python 3.12 (micromamba, conda-forge) + the v4 pipeline's pinned pip requirements
#                (cadquery-ocp 8.0.1.0.0, numpy 2.5.3, scipy 1.18.1, shapely 2.1.2, matplotlib 3.11.2, boto3, py7zr)
#   $W/sds2-v4 : sds2-step-pipeline-v4-candidate.zip unpacked (sha256 verified)
#   system GL/X client libs the OCP wheel links against (apt or dnf; headless use only)
# usage: bash setup.sh [W=/opt/conv] [KIT_DIR]
set -e
unset LD_LIBRARY_PATH
W=${1:-/opt/conv}; K=${2:-$W/kit/sds2}; mkdir -p "$W"
if command -v apt-get > /dev/null; then
  export DEBIAN_FRONTEND=noninteractive
  dpkg -s libgl1 libglu1-mesa libxrender1 libxext6 libsm6 libfontconfig1 libxkbcommon0 libxi6 > /dev/null 2>&1 || \
    { apt-get update -y -q > /dev/null && apt-get install -y -q libgl1 libglu1-mesa libxrender1 libxext6 libsm6 libfontconfig1 libxkbcommon0 libxi6 > /dev/null; }
elif command -v dnf > /dev/null; then
  dnf install -y -q mesa-libGL mesa-libGLU libXrender libXext libSM fontconfig libxkbcommon libXi > /dev/null 2>&1 || \
    dnf install -y -q mesa-libGL libXrender libXext libSM fontconfig libxkbcommon libXi > /dev/null
fi
if [ ! -x "$W/sds2env/bin/python" ] || ! "$W/sds2env/bin/python" -c "import OCP, numpy, scipy, shapely, matplotlib, boto3" 2>/dev/null; then
  if [ ! -x "$W/micromamba" ]; then
    curl -sSL --retry 5 -o "$W/micromamba" https://github.com/mamba-org/micromamba-releases/releases/latest/download/micromamba-linux-64
    chmod 755 "$W/micromamba"
  fi
  rm -rf "$W/sds2env"
  MAMBA_ROOT_PREFIX="$W/mamba" "$W/micromamba" create -y -q -p "$W/sds2env" -c conda-forge python=3.12 pip > "$W/sds2-mamba.log" 2>&1 || { tail -20 "$W/sds2-mamba.log"; exit 1; }
  mkdir -p "$W/sds2-v4"
  "$W/sds2env/bin/python" -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extract('sds2-step-pipeline/requirements.txt', sys.argv[2])" "$K/sds2-step-pipeline-v4-candidate.zip" "$W/sds2-v4"
  "$W/sds2env/bin/pip" install -q -r "$W/sds2-v4/sds2-step-pipeline/requirements.txt" > "$W/sds2-pip.log" 2>&1 || { tail -20 "$W/sds2-pip.log"; exit 1; }
fi
SHA=c5b65d271d3a6c69853d745d705cbb92b431e8891686068e7a555e720b3c15f0
echo "$SHA  $K/sds2-step-pipeline-v4-candidate.zip" | sha256sum -c - > /dev/null
if [ "$(cat $W/sds2-v4/.zip_sha256 2>/dev/null)" != "$SHA" ] || [ ! -f "$W/sds2-v4/sds2-step-pipeline/decode/sds2_to_step.py" ]; then
  "$W/sds2env/bin/python" -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$K/sds2-step-pipeline-v4-candidate.zip" "$W/sds2-v4"
  echo "$SHA" > "$W/sds2-v4/.zip_sha256"
fi
cd "$W/sds2-v4/sds2-step-pipeline"
"$W/sds2env/bin/python" -m py_compile batch/run_batch.py decode/sds2_to_step.py decode/to_step2.py decode/verify_step.py
"$W/sds2env/bin/python" - <<'PY'
import OCP, numpy, scipy, shapely, matplotlib, boto3, py7zr
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
assert BRepPrimAPI_MakeBox(1, 2, 3).Shape() is not None
print('sds2 env ok: OCP', getattr(OCP, '__version__', '?'), 'numpy', numpy.__version__)
PY
