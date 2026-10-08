#!/bin/bash
echo "$(nproc) $(cut -d' ' -f1 /proc/loadavg) $(free -g | awk '/Mem/{print $2, $7}') $(pgrep -fc 'db1@')"
