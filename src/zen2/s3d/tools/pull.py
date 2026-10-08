#!/usr/bin/env python3
"""pull.py REMOTE_PATH [...]  -> copies files from the box to ../dbg/ via s3 model/_debug/"""
import os, sys, subprocess
HERE = os.path.dirname(os.path.abspath(__file__)); DBG = os.path.join(HERE, '..', 'dbg')
S3 = 's3://annotationprod/cad-disk-extract/zenitude-data-2/model/_debug/pull/'
env = dict(os.environ, AWS_PROFILE='annotationprod-publish')
cmd = ' ; '.join('aws s3 cp --quiet "%s" "%s%s"' % (p, S3, os.path.basename(p)) for p in sys.argv[1:])
subprocess.run([sys.executable, os.path.join(HERE, 'box.py'), '--nosync', cmd, '-t', '300'], env=env, capture_output=True)
for p in sys.argv[1:]:
    subprocess.run(['aws', 's3', 'cp', '--quiet', S3 + os.path.basename(p), os.path.join(DBG, os.path.basename(p))], env=env)
    print(os.path.join(DBG, os.path.basename(p)), os.path.exists(os.path.join(DBG, os.path.basename(p))))
