#!/bin/bash
echo "== $(date -u +%FT%TZ) services: p3 $(systemctl is-active z3pkgp-loop) p4 $(systemctl is-active z3pkgp-loop4) perf $(systemctl is-active z3pkgperf-loop) finish $(systemctl is-active z3finish)"
for d in pkgpartial pkgpartial4; do L=/opt/$d/loop.log; echo "$d: ok $(grep -c ' ok ' $L) fail $(grep -c ' fail ' $L) | last: $(grep -E 'DELTA|ROUND' $L | tail -1 | cut -c1-230)"; grep ' fail ' $L | tail -2 | cut -c1-220; done
echo "partial ledger parts (packaged projects): $(aws s3 ls s3://bim-proprietary-data/cad-disk-extract/_state/packaging_partial/ledger_parts/ --region ap-south-1 | wc -l)"
echo "partial results recorded: $(aws s3 ls s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/conv/package_partial/results/ --region ap-south-1 | wc -l)"
tail -n 3 /opt/finish/finish.log | cut -c1-400
uptime; free -g | sed -n 2p; df -h / | tail -1
