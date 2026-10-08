#!/usr/bin/env python3
"""trace_run.py CONV.py IN OUT [args] - run the converter's main() with periodic stack dumps (faulthandler, every 20 s)"""
import sys, faulthandler, importlib.util, os
faulthandler.dump_traceback_later(20, repeat=True, file=sys.stderr)
spec = importlib.util.spec_from_file_location('conv', sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
sys.exit(m.main(sys.argv[2:]))
