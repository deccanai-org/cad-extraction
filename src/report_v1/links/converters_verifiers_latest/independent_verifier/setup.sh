#!/bin/bash
# Conversion + grading environment on a fresh Linux x86_64 host (AL2023 / Ubuntu); idempotent.
#   conda env  $W/env   : python 3.11, ifcopenshell 0.9.0, pythonocc-core, numpy, lark, boto3, matplotlib, orjson
#   venv       $W/ifc84 : ifcopenshell 0.8.4.post1 (fallback kernel; 0.8.5 hung on boolean cuts of hollow sections)
# usage: bash setup_occ.sh [W=/opt/conv]
set -e
unset LD_LIBRARY_PATH
W=${1:-/opt/conv}; mkdir -p "$W"; cd "$W"
if command -v dnf > /dev/null; then dnf install -y -q mesa-libGL libXrender libXext libSM fontconfig libxkbcommon libXi > /dev/null 2>&1 || true; fi
if command -v apt-get > /dev/null; then DEBIAN_FRONTEND=noninteractive apt-get install -y -q libgl1 libxrender1 libxext6 libsm6 libfontconfig1 > /dev/null 2>&1 || true; fi
if [ ! -x "$W/env/bin/python" ] || ! "$W/env/bin/python" -c "import ifcopenshell, OCC.Core.STEPControl, boto3, numpy, matplotlib" 2>/dev/null; then
  if [ ! -x "$W/micromamba" ]; then
    curl -sSL --retry 5 -o "$W/micromamba" https://github.com/mamba-org/micromamba-releases/releases/latest/download/micromamba-linux-64
    chmod 755 "$W/micromamba"
  fi
  rm -rf "$W/env"
  MAMBA_ROOT_PREFIX="$W/mamba" "$W/micromamba" create -y -q -p "$W/env" -c conda-forge \
      python=3.11 ifcopenshell=0.9.0 pythonocc-core numpy lark boto3 matplotlib orjson > "$W/mamba.log" 2>&1 || { tail -30 "$W/mamba.log"; exit 1; }
fi
if [ ! -x "$W/ifc84/bin/python" ] || ! "$W/ifc84/bin/python" -c "import ifcopenshell, ifcopenshell.geom" 2>/dev/null; then
  rm -rf "$W/ifc84"
  "$W/env/bin/python" -m venv "$W/ifc84"
  "$W/ifc84/bin/pip" install -q "ifcopenshell==0.8.4.post1" numpy lark > "$W/ifc84.log" 2>&1 || { tail -20 "$W/ifc84.log"; echo "WARN: 0.8.4 fallback kernel not available"; }
fi
"$W/env/bin/python" -c "import ifcopenshell, OCC, boto3, matplotlib; from OCC.Core.STEPControl import STEPControl_Reader; print('env ok ifcopenshell', ifcopenshell.version, 'occ', OCC.VERSION)"
[ -x "$W/ifc84/bin/python" ] && "$W/ifc84/bin/python" -c "import ifcopenshell; print('fallback ifcopenshell', ifcopenshell.version)" || true
# independent verifiers (IFC / DB1 adapters, lead 20:45Z): python 3.12 venv with requirements_ifc_db1.txt (cadquery-ocp 8.0.1,
# ifcopenshell 0.8.5, numpy >= 2.3, scipy, pillow, boto3); the OCP wheels need these libraries even headless
K=${2:-$W/kit/verify}
if command -v dnf > /dev/null; then dnf install -y -q mesa-libGL mesa-libGLU libXrender libXext libSM fontconfig libxkbcommon libXi > /dev/null 2>&1 || true; fi
if [ -f "$K/requirements_ifc_db1.txt" ] && { [ ! -x "$W/verifyenv/bin/python" ] || ! "$W/verifyenv/bin/python" -c "import OCP, ifcopenshell, scipy, numpy" 2>/dev/null; }; then
  rm -rf "$W/verifyenv"
  MAMBA_ROOT_PREFIX="$W/mamba" "$W/micromamba" create -y -q -p "$W/verifyenv" -c conda-forge python=3.12 pip > "$W/verifyenv.log" 2>&1 || { tail -20 "$W/verifyenv.log"; echo "WARN: verifyenv python 3.12 not created"; }
  [ -x "$W/verifyenv/bin/pip" ] && "$W/verifyenv/bin/pip" install -q -r "$K/requirements_ifc_db1.txt" >> "$W/verifyenv.log" 2>&1 || { tail -20 "$W/verifyenv.log"; echo "WARN: verifyenv requirements failed"; }
fi
[ -x "$W/verifyenv/bin/python" ] && "$W/verifyenv/bin/python" -c "import OCP, ifcopenshell, scipy; print('verifyenv ok ifcopenshell', ifcopenshell.version)" || true
