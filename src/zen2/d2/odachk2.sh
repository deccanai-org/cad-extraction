#!/bin/bash
rm -rf /tmp/odachk2; mkdir -p /tmp/odachk2/in /tmp/odachk2/out
find /work/2d/out/dxf_from_pdf -name 'page-*.dxf' -size -20M | sort | awk 'NR%97==1' | head -25 > /tmp/odachk2/list.txt
i=0; while read -r f; do i=$((i+1)); d="/tmp/odachk2/in/s$i"; mkdir -p "$d"; cp "$f" "$d/p.dxf"; cp "$(dirname "$f")"/page-*_img*.png "$d/" 2>/dev/null; done < /tmp/odachk2/list.txt
timeout 1200 xvfb-run -a ODAFileConverter /tmp/odachk2/in /tmp/odachk2/out ACAD2018 DWG 1 1 "*.dxf" > /tmp/odachk2/log 2>&1; echo rc=$?
echo "dwg written: $(find /tmp/odachk2/out -name '*.dwg' | wc -l) of $(find /tmp/odachk2/in -name '*.dxf' | wc -l); err files: $(find /tmp/odachk2/out -name '*.err' | wc -l)"
find /tmp/odachk2/out -name '*.err' | head -3 | while read -r e; do head -c 300 "$e"; echo; done
