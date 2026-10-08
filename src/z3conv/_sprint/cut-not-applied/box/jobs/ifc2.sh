#!/bin/bash
cd /work/agentwork/cut-not-applied; /opt/conv/env/bin/python tools/ifc_one.py truth/gsk.ifc  2>&1 | cut -c1-300
