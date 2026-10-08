#!/bin/bash
# Agent compute box (AL2023, Mumbai): heavy validation / regression runs for the conversion fix agents, driven via SSM.
# Env: /opt/conv/env (python 3.11, ifcopenshell 0.9, pythonocc-core, numpy, boto3), /opt/conv/ifc84, /opt/mono (mono), 7zz.
# Work dirs /work/agentwork/<slug>; results -> s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/<slug>/
# Self-terminates when s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/RELEASE exists, or after 20 h.
exec > /var/log/agentbox-boot.log 2>&1
set -x
O=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork
K=s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs
dnf install -y python3-pip xz tar git jq > /dev/null 2>&1
pip3 install -q -U boto3
( sleep 72000; shutdown -h now ) &
( while true; do aws s3 ls $K/RELEASE > /dev/null 2>&1 && shutdown -h now; sleep 300; done ) &
mkdir -p /opt/conv /work/agentwork
( curl -sfL https://www.7-zip.org/a/7z2408-linux-x64.tar.xz -o /tmp/7z.tar.xz || curl -sfL https://github.com/ip7z/7zip/releases/download/24.08/7z2408-linux-x64.tar.xz -o /tmp/7z.tar.xz ) \
  && tar xJf /tmp/7z.tar.xz -C /usr/local/bin 7zz && chmod +x /usr/local/bin/7zz
aws s3 cp --quiet s3://annotationprod/cad-disk-extract/_control/z3conv/ifc/setup.sh /opt/conv/setup.sh && bash /opt/conv/setup.sh /opt/conv > /opt/conv/setup.out 2>&1
MAMBA_ROOT_PREFIX=/opt/conv/mamba /opt/conv/micromamba create -y -q -p /opt/mono -c conda-forge mono > /opt/conv/mono.log 2>&1 || true
echo "$(date -u +%FT%TZ) $(hostname) $(nproc) cpus; env: $(tail -2 /opt/conv/setup.out | tr '\n' ' '); mono: $(/opt/mono/bin/mono --version 2>/dev/null | head -1)" > /work/agentwork/READY
aws s3 cp --quiet /work/agentwork/READY $O/_boxes/$(hostname).ready
