W=/work/agentwork/ifc-volume-residue
for i in 3a5129c14f17f9b0 03af2c3170d9a570 e5f30a12ecc5f3e5; do aws s3 cp --quiet $W/w/dev3/$i/src_parts3.jsonl.gz s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifc-volume-residue/dev3/$i/src_parts3.jsonl.gz; done
zcat $W/w/dev3/3a5129c14f17f9b0/src_parts3.jsonl.gz | grep -E "1876302|1876310" | cut -c1-400
