W=/work/agentwork/ifc-volume-residue
find $W/w -maxdepth 3 \( -name 'out.step' -o -name 'in.bin' -o -name 'schema.ifc' -o -name 'unz.ifc' -o -name 'hdr.ifc' -o -name 'merged.ifc' -o -name 'out.step.png' \) -type f -delete
find $W/w -maxdepth 3 -type d -name '.v6tmp_*' -exec rm -rf {} + 2>/dev/null
rm -rf $W/in $W/diag761 $W/v601 $W/index
du -sh $W; ls $W
