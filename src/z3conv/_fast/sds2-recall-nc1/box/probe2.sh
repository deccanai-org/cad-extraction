#!/bin/bash
hostname; nproc; uptime; free -g | head -2; df -h /work 2>/dev/null | tail -1; df -h / | tail -1
ls /opt/conv/env/bin/python 2>&1; /opt/conv/env/bin/python -c "import ifcopenshell, numpy; print(ifcopenshell.version, numpy.__version__)" 2>&1 | tail -1
ls /work/agentwork 2>/dev/null | head
