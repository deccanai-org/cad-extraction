set -e
uptime; nproc; free -g | head -2; df -h /work | tail -1
ps aux --sort=-%cpu | grep -v grep | grep python | head -10 | cut -c1-200
ls /work; ls /work/out; ls /work/out/state | head
echo ---; ls /work/in/src | head -40
echo ---; find /work/in/src -type f | sed 's/.*\.//' | sort | uniq -c | sort -rn | head -20
echo ---; cat /work/out/state/dxf_failures.tsv | cut -c1-300
wc -l /work/out/json/source_sha256.tsv
ls /work/out/png | head -5; find /work/out/png -type f | head -3; find /work/out/png -type f | wc -l
find /work/out/dxf -type f | head -3
find /work/out/json/drawings_text -type f | head -3
python3 --version; which inkscape xvfb-run dwg2dxf ODAFileConverter 2>&1 | head
