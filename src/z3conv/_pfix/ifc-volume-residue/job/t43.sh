W=/work/agentwork/ifc-volume-residue
ls -la $W/w/dev3/e5f30a12ecc5f3e5/ | head; head -c 300 $W/in/e5f30a12ecc5f3e5.bin | strings | head -3
grep -a -m3 "^#39841\s*=" $W/w/dev3/e5f30a12ecc5f3e5/in.bin | cut -c1-200
grep -a -m3 "^#39845\s*=" $W/w/dev3/e5f30a12ecc5f3e5/in.bin | cut -c1-200
grep -a -m3 "^#39846\s*=" $W/w/dev3/e5f30a12ecc5f3e5/in.bin | cut -c1-200
