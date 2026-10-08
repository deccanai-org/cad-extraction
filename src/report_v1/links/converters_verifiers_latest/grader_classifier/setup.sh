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
# scipy for the grader's stray-part check (verifier grader patches, 20:45Z)
"$W/env/bin/python" -c "import scipy" 2>/dev/null || "$W/env/bin/python" -m pip install -q scipy > "$W/scipy.log" 2>&1 || echo "WARN: scipy not installed (stray check unavailable)"
# shapely for ifc2step6 6.1.8+ (coplanar-overlap union repair; without it that repair is skipped and noted in stats)
"$W/env/bin/python" -c "import shapely" 2>/dev/null || "$W/env/bin/python" -m pip install -q shapely==2.1.2 > "$W/shapely.log" 2>&1 || echo "WARN: shapely not installed (coplanar union repair skipped)"
"$W/env/bin/python" -c "import ifcopenshell, OCC, boto3, matplotlib; from OCC.Core.STEPControl import STEPControl_Reader; print('env ok ifcopenshell', ifcopenshell.version, 'occ', OCC.VERSION)"
[ -x "$W/ifc84/bin/python" ] && "$W/ifc84/bin/python" -c "import ifcopenshell; print('fallback ifcopenshell', ifcopenshell.version)" || true
