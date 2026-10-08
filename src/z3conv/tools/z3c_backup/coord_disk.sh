#!/bin/bash
df -h / /opt /scratch 2>/dev/null; lsblk | head -20; ls /opt/pkgd4r2/kit | head -30; diff -q /opt/pkgd4r2/kit/pkgcore.py /opt/z3c/pkgcore.py 2>&1 | head -2; ls /opt/z3c | head -40
