#!/bin/bash
hostname; uptime; nproc; free -g | head -2; df -h /work 2>/dev/null | tail -1
ls -la /work/agentwork/ 2>&1 | head -30
ls /opt/conv/ 2>&1
/opt/conv/env/bin/python -c "import ifcopenshell, OCC; print(ifcopenshell.version)" 2>&1
/opt/conv/ifc84/bin/python -c "import ifcopenshell; print(ifcopenshell.version)" 2>&1
ps aux --sort=-%cpu | head -8
