#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W
/opt/conv/env/bin/python tools/cutter_probe.py dec/after/748b957ceaceeb17.json 'PD40*3' 'D21.000000' 'PL65*65' 'L75*75*6'
/opt/conv/env/bin/python tools/cutter_probe.py dec/after/0762effe61de88c0.json 'D21' 'D10' 'PLT178.1' 'D12' 'BL24'
/opt/conv/env/bin/python tools/cutter_probe.py dec/after/6eabb07e71459be6.json 'PL145.509' 'PL190.721' 'PL79.85'
/opt/conv/env/bin/python tools/cutter_probe.py dec/after/7c82c44be6c7ae3f.json 'PL147' 'PL185.1' 'PL619.6'
/opt/conv/env/bin/python tools/cutter_probe.py dec/after/5b33936fcd1e3efc.json 'ROD31.75' 'PL119.855' 'RB25.4'
/opt/conv/env/bin/python tools/cutter_probe.py dec/after/0632e878d57c36f0.json 'L150*90*10' 'D20'
