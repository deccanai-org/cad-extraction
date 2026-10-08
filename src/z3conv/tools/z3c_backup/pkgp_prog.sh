#!/bin/bash
L=/opt/pkgpartial/loop.log; echo "partial ok jobs: $(grep -c ' ok ' $L) fail: $(grep -c ' fail ' $L)"; grep -E " (ok|fail) " $L | tail -n 3 | cut -c1-300
L2=/opt/pkgperf/loop.log; echo "perfect ok jobs: $(grep -c ' ok ' $L2) fail: $(grep -c ' fail ' $L2)"; grep " fail " $L2 | tail -n 3 | cut -c1-300
