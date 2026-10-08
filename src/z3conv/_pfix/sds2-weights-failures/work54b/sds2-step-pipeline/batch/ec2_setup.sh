#!/usr/bin/env bash
# One-time setup on an Ubuntu 24.04 EC2 instance (Python 3.12 is the system Python there).
# usage: bash batch/ec2_setup.sh            (run from the sds2-step-pipeline folder)
set -euo pipefail
cd "$(dirname "$0")/.."

sudo apt-get update -y
# OpenCascade (cadquery-ocp) wheels need the GL / X client libraries even headless
sudo apt-get install -y python3.12 python3.12-venv python3-pip tmux unzip \
    libgl1 libglu1-mesa libxrender1 libxext6 libsm6 libfontconfig1 libxkbcommon0 libxi6
# 7-Zip CLI for .7z archives (all codecs incl. BCJ2, which py7zr can't decode; faster than py7zr)
sudo apt-get install -y 7zip || sudo apt-get install -y p7zip-full
command -v 7zz || command -v 7z || { echo "no 7-Zip binary found: .7z archives will use py7zr only"; }

python3.12 -m venv "$HOME/sds2env"
"$HOME/sds2env/bin/pip" install --upgrade pip
"$HOME/sds2env/bin/pip" install -r requirements.txt

"$HOME/sds2env/bin/python" - <<'EOF'
import OCP, numpy, scipy, shapely, matplotlib, boto3, py7zr
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
assert BRepPrimAPI_MakeBox(1, 2, 3).Shape() is not None
import boto3
print("python deps ok; AWS identity:", boto3.client("sts").get_caller_identity()["Arn"])
EOF
echo "setup done: activate with  source ~/sds2env/bin/activate"
