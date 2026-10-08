#!/bin/bash
curl -sS -m 10 -o /dev/null -w "pypi %{http_code}\n" https://pypi.org/simple/cadquery-ocp/ 2>&1 | tail -1
curl -sS -m 10 -o /dev/null -w "github %{http_code}\n" https://github.com 2>&1 | tail -1
ls /opt/conv/ 2>&1; ls /work/agentwork/sds2v54/env/bin/python 2>&1
