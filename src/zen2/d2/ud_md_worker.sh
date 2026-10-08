#!/bin/bash
# ud_md_worker.sh - user-data / bootstrap for extra model_drawings workers (Ubuntu 22.04/24.04, instance role with
# read/write on s3://annotationprod/cad-disk-extract/zenitude-data-2/). Workers share the job via S3 chunk claims
# (_state/d2_md_claims/chunk-NNN, conditional writes), so any number of boxes can run this; no code changes needed.
set -u
export DEBIAN_FRONTEND=noninteractive AWS_DEFAULT_REGION=ap-south-1
B=s3://annotationprod/cad-disk-extract/zenitude-data-2
mkdir -p /work/2d /work/md/state /work/md/tmp
exec >> /work/md/state/bootstrap.log 2>&1
echo "$(date -u +%FT%TZ) bootstrap start"
apt-get update -q && apt-get install -y -q python3-venv python3-pip fonts-liberation unzip awscli || apt-get install -y -q python3-venv fonts-liberation
command -v aws >/dev/null || { pip3 install -q awscli || snap install aws-cli --classic; }
cd /work/2d
aws s3 cp --only-show-errors $B/_state/d2_code/d2_code.tgz . && tar xzf d2_code.tgz
python3 -m venv venv && ./venv/bin/pip install -q --upgrade pip && \
  ./venv/bin/pip install -q pymupdf ezdxf olefile numpy pillow boto3 fonttools scipy
NP=$(( $(nproc) - 1 ))
echo "$(date -u +%FT%TZ) starting md_run.py with $NP processes"
./venv/bin/python md_run.py $NP >> /work/md/state/md_run.log 2>&1
echo "$(date -u +%FT%TZ) md_run finished rc=$?"
# optional self-termination when shutdown behaviour = terminate:
[ -f /work/md/NO_SHUTDOWN ] || shutdown -h +2
