#!/bin/bash
# read-only: packaging hook lines in the coordinator log
journalctl -u z3coord --since "-20 min" --no-pager 2>/dev/null | grep -i "zen4\|packaging\|hook\|Traceback\|Error" | tail -n 25 | cut -c1-260
ls -la /opt/z3c/kit/coord/ | grep -i "pkg\|adapter\|hook"
