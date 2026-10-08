uptime; nproc; free -g | head -2; df -h /work | tail -1
ps -eo pid,pcpu,pmem,etime,args --sort=-pcpu | grep -v grep | grep -i python | cut -c1-160 | head
dwg2dxf --version 2>&1 | head -2
aws --version 2>&1; which s5cmd
head -3 /work/out/json/source_sha256.tsv | cut -c1-200
awk -F'\t' '{print $2}' /work/out/json/source_sha256.tsv | grep -ci '\.pdf$'
awk -F'\t' '{print $2}' /work/out/json/source_sha256.tsv | grep -i '\.pdf$' | grep -c '^PLC'
awk -F'\t' 'tolower($2) ~ /\.pdf$/ {print $1}' /work/out/json/source_sha256.tsv | sort -u | wc -l
awk -F'\t' 'tolower($2) ~ /\.sha$/ {print $1}' /work/out/json/source_sha256.tsv | sort -u | wc -l
awk -F'\t' 'tolower($2) ~ /\.pdf$/' /work/out/json/source_sha256.tsv | awk -F'\t' '{print $2}' | awk -F/ '{print $1}' | sort | uniq -c
