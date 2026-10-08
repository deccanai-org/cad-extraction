#!/bin/bash
WD=/work/agentwork/sds2-grating-cylinders; cd $WD
grep -v LD_PRELOAD logs/fetch2r.log logs/fetch3g.log 2>/dev/null | cut -c1-250
ls jobs/
