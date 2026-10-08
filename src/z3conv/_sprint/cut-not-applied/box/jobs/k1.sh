#!/bin/bash
ps -o pid,pgid,cmd -g 2891010 | cut -c1-150
kill -- -2891010; sleep 1; ps -o pid,pgid,cmd -g 2891763 | cut -c1-150
