#!/bin/bash
# remove my large intermediate files on the box (all results already uploaded to s3 agentwork/ifcxml/); scripts + small logs kept
cd /work/agentwork/ifcxml || exit 1
before=$(du -sm . | cut -f1)
find work hx find t2 h1 -type f \( -name '*.step' -o -name '*.ifc' -o -name 'in.*' -o -name '*.bin' -o -name '*.ifc.gz' -o -name '*.step.gz' -o -name 'xml_rows_*.jsonl.gz' -o -name 'member.xml' -o -name '*.xml' -o -name '*.ifcXML' -o -name '*.ifczip' -o -name '*.ifcZIP' \) -delete 2>/dev/null
find work hx -type d -name '.v6tmp*' -exec rm -rf {} + 2>/dev/null
after=$(du -sm . | cut -f1)
echo "ifcxml workdir ${before} MB -> ${after} MB"; ps -eo pid,args | grep agentwork/ifcxml | grep -v grep | head -3
