#!/bin/bash
grep -E "CANARY|DELTA|ROUND|Traceback|Error|rc=" /opt/pkgpartial/loop.log | tail -n 8 | cut -c1-600; tail -n 2 /opt/pkgpartial/loop.log | cut -c1-300
