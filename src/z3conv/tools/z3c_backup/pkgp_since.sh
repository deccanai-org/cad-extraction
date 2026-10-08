#!/bin/bash
L=/opt/pkgpartial/loop.log; S=$(grep -n "04:33:28 DELTA" $L | tail -1 | cut -d: -f1)
tail -n +$S $L > /tmp/pkgp_new.log
echo "since restart: ok $(grep -c ' ok ' /tmp/pkgp_new.log) fail $(grep -c ' fail ' /tmp/pkgp_new.log) verify_bad $(grep ' ok ' /tmp/pkgp_new.log | grep -vc '{} ')"
grep -E " fail |Traceback" /tmp/pkgp_new.log | head -5 | cut -c1-300; grep ' ok ' /tmp/pkgp_new.log | tail -n 4 | cut -c1-220
