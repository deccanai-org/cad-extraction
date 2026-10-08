#!/bin/bash
echo "host: $(hostname) $(nproc) cpus; mem: $(free -g | awk '/Mem/{print $2"G total "$7"G avail"}')"
df -h /data / | tail -n +1
uptime
ls -la /data/ | head -30
ls -la /data/s3d 2>&1 | head
which python3 python3.11 python3.9 aws 2>&1
python3 --version
ls /opt/microsoft/msodbcsql18/lib64/ 2>&1
odbcinst -q -d 2>&1
curl -sS -o /dev/null -w "github %{http_code}\n" https://github.com --max-time 10
curl -sS -o /dev/null -w "condaforge %{http_code}\n" https://conda.anaconda.org/conda-forge/ --max-time 10
curl -sS -o /dev/null -w "pypi %{http_code}\n" https://pypi.org/simple/ --max-time 10
ps aux --sort=-%cpu | head -8
aws s3 ls s3://annotationprod/cad-disk-extract/zenitude-data-2/ 2>&1 | head -30
