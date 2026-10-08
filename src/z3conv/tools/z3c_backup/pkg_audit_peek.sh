#!/bin/bash
tail -5 /opt/report/out/pkg_audit.log; ls -la /opt/report/out/pkg_audit.json 2>/dev/null; pgrep -f pkg_audit.py | wc -l
