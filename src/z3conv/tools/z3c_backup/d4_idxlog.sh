#!/bin/bash
L=/opt/z3c/index-zentitude-data-4.log
ls -la $L; grep -n -i "redo_ids\|reconvert\|error" $L | tail -15 | cut -c1-300; echo ---; tail -5 $L | cut -c1-400
ls /work/index-zentitude-data-4 | head; md5sum /opt/z3c/kit/coord/build_index.py
