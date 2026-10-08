#!/bin/bash
grep -E "DELTA|ROUND|Traceback|Error" /opt/pkgpartial4/loop.log | tail -n 3 | cut -c1-400; echo "ok $(grep -c ' ok ' /opt/pkgpartial4/loop.log) fail $(grep -c ' fail ' /opt/pkgpartial4/loop.log)"; tail -n 2 /opt/pkgpartial4/loop.log | cut -c1-250; free -g | sed -n 2p
