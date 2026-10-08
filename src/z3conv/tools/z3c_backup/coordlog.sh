#!/bin/bash
grep -h -i "reconvert\|db1.*redo\|redo.*db1" /opt/z3c/index.log /opt/z3c/index-zentitude-data-4.log | tail -6 | cut -c1-400
