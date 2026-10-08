#!/bin/bash
# Read-only: show the z3status publisher's state on the coordinator.
systemctl is-active z3status
journalctl -u z3status --no-pager -n 12 | cut -c1-220
cd /opt/status/cad-extract-status && git log --format='%h %an %s' -3 && git status -sb | head -3
