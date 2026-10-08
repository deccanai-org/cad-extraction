#!/bin/bash
# Start one detached conversion worker per host.
#   aws s3 cp s3://annotationprod/cad-disk-extract/zenitude-data-2/_control/s3d3d/run.sh /tmp/run.sh && bash /tmp/run.sh [SLOTS]
# SLOTS defaults to nproc/3 (each job uses ~2-3 threads). Scratch: $WORKDIR (default /tmp/s3d3d; needs ~20 GB per 8 slots).
set -e
unset LD_LIBRARY_PATH __EGL_VENDOR_LIBRARY_FILENAMES   # system curl/aws must not see the conda libs
W=${S3D3D_HOME:-/opt/s3d3d}
mkdir -p "$W"
aws s3 cp --only-show-errors s3://annotationprod/cad-disk-extract/zenitude-data-2/_control/s3d3d/setup.sh "$W/setup.sh"
bash "$W/setup.sh" "$W" > "$W/setup.log" 2>&1 || { tail -30 "$W/setup.log"; exit 1; }
export LD_LIBRARY_PATH="$W/env/lib" __EGL_VENDOR_LIBRARY_FILENAMES="$W/env/share/glvnd/egl_vendor.d/50_mesa.json" PYOPENGL_PLATFORM=egl EGL_PLATFORM=surfaceless
SLOTS=${1:-$(( $(nproc) / 3 ))}
setsid nohup "$W/env/bin/python" "$W/code/worker.py" --slots "$SLOTS" ${S3D3D_PNG:+--png} --work "${WORKDIR:-/tmp/s3d3d}" > "$W/worker.log" 2>&1 < /dev/null &
echo "worker started: slots=$SLOTS log=$W/worker.log"
