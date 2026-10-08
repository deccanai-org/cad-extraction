#!/bin/bash
# READ-ONLY: latest coordinator summary lines (class counts per disk/type) + status files.
tail -n 3 /opt/z3c/index.log | cut -c1-1500; echo ==; tail -n 3 /opt/z3c/index-zentitude-data-4.log | cut -c1-1500; echo ==
ls -lt /opt/z3c/*.json /opt/z3c/out 2>/dev/null | head -20; systemctl cat z3status 2>/dev/null | grep -i exec | head -3
