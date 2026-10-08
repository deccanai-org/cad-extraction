#!/usr/bin/env python3
"""box.py [-t TIMEOUT] [--nosync] 'shell command'  -> sync src/ to the box (via s3 model/_code) then run command there.
Env on the box: PY=/data/s3d/env/bin/python, cwd=/data/s3d/src."""
import argparse, base64, os, subprocess, tempfile
ap = argparse.ArgumentParser(); ap.add_argument('cmd'); ap.add_argument('-t', type=int, default=600); ap.add_argument('--nosync', action='store_true')
a = ap.parse_args()
HERE = os.path.dirname(os.path.abspath(__file__)); SRC = os.path.join(HERE, '..', 'src')
CODE = 's3://annotationprod/cad-disk-extract/zenitude-data-2/model/_code/src/'
env = dict(os.environ, AWS_PROFILE='annotationprod-publish')
if not a.nosync:
    subprocess.run(['aws', 's3', 'sync', '--quiet', '--delete', '--exclude', '__pycache__/*', '--exclude', '*.pyc', SRC, CODE], env=env, check=True)
b64 = base64.b64encode(a.cmd.encode()).decode()
sh = f"""#!/bin/bash
mkdir -p /data/s3d/src /data/s3d/logs
{'' if a.nosync else f'aws s3 sync --quiet --delete {CODE} /data/s3d/src/ --exclude "__pycache__/*"'}
export PY=/data/s3d/env/bin/python S3D_ROOT=/data/s3d LD_LIBRARY_PATH=/data/s3d/env/lib __EGL_VENDOR_LIBRARY_FILENAMES=/data/s3d/env/share/glvnd/egl_vendor.d/50_mesa.json PYOPENGL_PLATFORM=egl EGL_PLATFORM=surfaceless
export PATH=/data/s3d/env/bin:$PATH
cd /data/s3d/src
echo '{b64}' | base64 -d > /data/s3d/tmp_cmd.sh
bash /data/s3d/tmp_cmd.sh 2>&1 | tail -c 2950
"""
fd, p = tempfile.mkstemp(suffix='.sh'); os.write(fd, sh.encode()); os.close(fd)
r = subprocess.run(['/Users/dhiren/Downloads/Deccan/cad-db1-convert/venv/bin/python', '/Users/dhiren/Downloads/Deccan/cad-db1-convert/src/ssm.py',
                    'ap-south-1', 'i-02c20241cf997b48d', p, str(a.t)], env=env, capture_output=True, text=True)
print(r.stdout[-3300:], r.stderr[-800:])
