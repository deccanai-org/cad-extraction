#!/bin/bash
# Build the conversion environment on a fresh Linux x86_64 host (AL2023 / Ubuntu); no sudo packages needed.
# usage: bash setup.sh [W=/opt/s3d3d]
set -e
unset LD_LIBRARY_PATH __EGL_VENDOR_LIBRARY_FILENAMES   # system curl/aws must not see the conda libs
W=${1:-/opt/s3d3d}; mkdir -p "$W/code"
aws s3 sync --only-show-errors s3://annotationprod/cad-disk-extract/zenitude-data-2/_control/s3d3d/ "$W/code/" --exclude "jobs.json"
if [ ! -x "$W/env/bin/python" ] || ! "$W/env/bin/python" -c "import ifcopenshell, OCC, trimesh, pyrender" 2>/dev/null; then
  if [ ! -x "$W/micromamba" ]; then
    curl -sSL -o "$W/micromamba" https://github.com/mamba-org/micromamba-releases/releases/latest/download/micromamba-linux-64
    chmod 755 "$W/micromamba"
  fi
  MAMBA_ROOT_PREFIX="$W/mamba" "$W/micromamba" create -y -p "$W/env" -c conda-forge \
      python=3.11 ifcopenshell=0.9.0 pythonocc-core numpy lark trimesh pillow boto3 mesalib pyopengl
  "$W/env/bin/pip" install -q pyrender==0.1.45
  "$W/env/bin/pip" install -q "PyOpenGL==3.1.7"
fi
export LD_LIBRARY_PATH="$W/env/lib" __EGL_VENDOR_LIBRARY_FILENAMES="$W/env/share/glvnd/egl_vendor.d/50_mesa.json" PYOPENGL_PLATFORM=egl EGL_PLATFORM=surfaceless
"$W/env/bin/python" -c "import ifcopenshell, OCC, boto3, trimesh, pyrender; print('env ok ifcopenshell', ifcopenshell.version)"
"$W/env/bin/IfcConvert" --version | head -1
