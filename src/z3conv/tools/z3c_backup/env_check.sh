#!/bin/bash
/opt/conv/env/bin/python -c "import ifcopenshell, ifcopenshell.geom, OCC; print('ifcopenshell', ifcopenshell.version)" 2>&1 | tail -1
ls /opt/conv/ifc 2>/dev/null | head; ls /opt/z3c/kit 2>/dev/null; nproc; free -g | head -2
