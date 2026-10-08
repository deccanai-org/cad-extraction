#!/bin/bash
# Stop the parallel lister BEFORE it restarts the resolver: the original resolver already finished listing and is proving (stage 3).
systemctl stop z3pkgres4-list 2>/dev/null; sleep 2
echo "lister: $(systemctl is-active z3pkgres4-list)  resolver: $(systemctl is-active z3pkgres4)"; tail -n 2 /opt/pkgres4/log.txt
