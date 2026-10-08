W=/work/agentwork/ifc-volume-residue
cd $W/pkg && timeout 200 /opt/conv/env/bin/python peek.py $W/w/dev3/e5f30a12ecc5f3e5/in.bin 1Ff5L8dq16ehh6ac8ostWW 2>&1 | cut -c1-600
timeout 200 /opt/conv/env/bin/python try_vol.py $W/w/dev3/e5f30a12ecc5f3e5/in.bin 1Ff5L8dq16ehh6ac8ostWW 2>&1 | tail -12 | cut -c1-300
timeout 200 /opt/conv/env/bin/python bool_steps.py $W/w/dev3/e5f30a12ecc5f3e5/in.bin 1Ff5L8dq16ehh6ac8ostWW 2>&1 | tail -14 | cut -c1-250
