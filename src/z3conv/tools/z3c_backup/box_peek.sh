#!/bin/bash
uptime | sed 's/.*load/load/'; ps -eo etime,pcpu,args --sort=-pcpu | grep -E 'python|conv' | grep -v grep | head -4 | cut -c1-150; ls /opt/*/FINAL_OK /opt/*/DONE 2>/dev/null | head -3
