#!/bin/bash
# SDS/2 conversion environment on a fresh Linux x86_64 host (AL2023 or Ubuntu); idempotent; converter chosen by converter.json.
#   $W/sds2env        : python 3.12 (micromamba, conda-forge) + the converter's pinned pip requirements (cadquery-ocp, numpy, ...)
#   $W/sds2-<label>   : converter zip unpacked (sha256 verified)
# usage: bash setup.sh [W=/opt/conv] [KIT_DIR]
set -e
unset LD_LIBRARY_PATH
W=${1:-/opt/conv}; K=${2:-$W/kit/sds2}; mkdir -p "$W"
ZIP=$(python3 -c "import json;print(json.load(open('$K/converter.json'))['zip'])")
SHA=$(python3 -c "import json;print(json.load(open('$K/converter.json'))['sha256'])")
LABEL=$(python3 -c "import json;print(json.load(open('$K/converter.json'))['label'])")
if command -v apt-get > /dev/null; then
  export DEBIAN_FRONTEND=noninteractive
  dpkg -s libgl1 libglu1-mesa libxrender1 libxext6 libsm6 libfontconfig1 libxkbcommon0 libxi6 > /dev/null 2>&1 || \
    { apt-get update -y -q > /dev/null && apt-get install -y -q libgl1 libglu1-mesa libxrender1 libxext6 libsm6 libfontconfig1 libxkbcommon0 libxi6 > /dev/null; }
elif command -v dnf > /dev/null; then
  dnf install -y -q mesa-libGL mesa-libGLU libXrender libXext libSM fontconfig libxkbcommon libXi > /dev/null 2>&1 || \
    dnf install -y -q mesa-libGL libXrender libXext libSM fontconfig libxkbcommon libXi > /dev/null
fi
echo "$SHA  $K/$ZIP" | sha256sum -c - > /dev/null
if [ ! -x "$W/micromamba" ]; then
  curl -sSL --retry 5 -o "$W/micromamba" https://github.com/mamba-org/micromamba-releases/releases/latest/download/micromamba-linux-64
  chmod 755 "$W/micromamba"
fi
if [ ! -x "$W/sds2env/bin/python" ]; then
  MAMBA_ROOT_PREFIX="$W/mamba" "$W/micromamba" create -y -q -p "$W/sds2env" -c conda-forge python=3.12 pip > "$W/sds2-mamba.log" 2>&1 || { tail -20 "$W/sds2-mamba.log"; exit 1; }
fi
if [ "$(cat $W/sds2-$LABEL/.zip_sha256 2>/dev/null)" != "$SHA" ] || [ ! -f "$W/sds2-$LABEL/sds2-step-pipeline/decode/sds2_to_step.py" ]; then
  rm -rf "$W/sds2-$LABEL"; mkdir -p "$W/sds2-$LABEL"
  "$W/sds2env/bin/python" -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$K/$ZIP" "$W/sds2-$LABEL"
  echo "$SHA" > "$W/sds2-$LABEL/.zip_sha256"
fi
"$W/sds2env/bin/pip" install -q -r "$W/sds2-$LABEL/sds2-step-pipeline/requirements.txt" boto3 > "$W/sds2-pip.log" 2>&1 || { tail -20 "$W/sds2-pip.log"; exit 1; }
cd "$W/sds2-$LABEL/sds2-step-pipeline"
"$W/sds2env/bin/python" -m py_compile batch/run_batch.py decode/sds2_to_step.py decode/to_step2.py decode/verify_step.py
"$W/sds2env/bin/python" - <<'PY'
import OCP, numpy, scipy, shapely, matplotlib, boto3
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
assert BRepPrimAPI_MakeBox(1, 2, 3).Shape() is not None
print('sds2 env ok: OCP', getattr(OCP, '__version__', '?'), 'numpy', numpy.__version__)
PY
