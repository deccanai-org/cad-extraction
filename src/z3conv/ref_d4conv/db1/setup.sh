#!/bin/bash
# Build the conversion environment on a fresh Linux x86_64 host (AL2023 / Ubuntu); idempotent; no sudo packages needed.
#   conda env  $W/env   : python 3.11, ifcopenshell 0.9.0, pythonocc-core, numpy, lark, boto3   (convert + OCC read-back)
#   venv       $W/ifc84 : ifcopenshell 0.8.4.post1 (fallback geometry kernel; 0.8.5 hung on boolean cuts of hollow sections)
# usage: bash setup.sh [W=/opt/conv]
set -e
unset LD_LIBRARY_PATH
W=${1:-/opt/conv}; mkdir -p "$W"
cd "$W"
if [ ! -x "$W/env/bin/python" ] || ! "$W/env/bin/python" -c "import ifcopenshell, OCC.Core.STEPControl, boto3, numpy" 2>/dev/null; then
  if [ ! -x "$W/micromamba" ]; then
    curl -sSL --retry 5 -o "$W/micromamba" https://github.com/mamba-org/micromamba-releases/releases/latest/download/micromamba-linux-64
    chmod 755 "$W/micromamba"
  fi
  rm -rf "$W/env"
  MAMBA_ROOT_PREFIX="$W/mamba" "$W/micromamba" create -y -q -p "$W/env" -c conda-forge \
      python=3.11 ifcopenshell=0.9.0 pythonocc-core numpy lark boto3 > "$W/mamba.log" 2>&1 || { tail -30 "$W/mamba.log"; exit 1; }
fi
if [ ! -x "$W/ifc84/bin/python" ] || ! "$W/ifc84/bin/python" -c "import ifcopenshell, ifcopenshell.geom" 2>/dev/null; then
  rm -rf "$W/ifc84"
  "$W/env/bin/python" -m venv "$W/ifc84"
  "$W/ifc84/bin/pip" install -q "ifcopenshell==0.8.4.post1" numpy lark > "$W/ifc84.log" 2>&1 || { tail -20 "$W/ifc84.log"; echo "WARN: 0.8.4 fallback kernel not available"; }
fi
"$W/env/bin/python" -c "import ifcopenshell, OCC, boto3; from OCC.Core.STEPControl import STEPControl_Reader; print('env ok ifcopenshell', ifcopenshell.version, 'occ', OCC.VERSION)"
[ -x "$W/ifc84/bin/python" ] && "$W/ifc84/bin/python" -c "import ifcopenshell; print('fallback ifcopenshell', ifcopenshell.version)" || true
