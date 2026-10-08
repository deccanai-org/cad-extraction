#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W; export KIT=$W/kitnp9
timeout 900 /opt/conv/env/bin/python tools/bbox_pair.py gambro ifconly/kitn/truth_gambro ifconly/kitnp8/truth_gambro 0 20 2>&1 | tail -8 | cut -c1-600
