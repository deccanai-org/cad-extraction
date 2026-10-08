#!/bin/bash
tail -n 25 /var/log/conv-boot.log | cut -c1-220; echo ==; tail -n 15 /opt/conv/worker-ifc.log 2>/dev/null | cut -c1-220; echo ==; journalctl --list-boots --no-pager 2>/dev/null | tail -3; journalctl -b -1 -n 25 --no-pager 2>/dev/null | cut -c1-220 | tail -25
