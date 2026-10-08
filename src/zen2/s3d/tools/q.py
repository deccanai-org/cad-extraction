#!/usr/bin/env python3
"""q.py SQLFILE [-d DB] [-v K=V ...] [-o NAME] [-t TIMEOUT]
Runs a SQL file on the S3D box via SSM (sqlcmd, read-only SELECTs). With -o the full output is
uploaded to s3://.../zenitude-data-2/model/_debug/NAME and copied to ../dbg/NAME locally."""
import argparse, base64, os, subprocess, sys, tempfile
ap = argparse.ArgumentParser()
ap.add_argument('sql'); ap.add_argument('-d', default='MLNG@1_MDB'); ap.add_argument('-v', nargs='*', default=[])
ap.add_argument('-o'); ap.add_argument('-t', type=int, default=600); ap.add_argument('--sh', action='store_true', help='file is a shell script')
a = ap.parse_args()
body = open(a.sql).read()
b64 = base64.b64encode(body.encode()).decode()
DBG = 's3://annotationprod/cad-disk-extract/zenitude-data-2/model/_debug'
name = a.o or 'last.txt'
if a.sh:
    sh = f"""#!/bin/bash
echo '{b64}' | base64 -d > /data/s3d/tmp/q_{name}.sh
bash /data/s3d/tmp/q_{name}.sh > /data/s3d/tmp/{name} 2>&1
"""
else:
    vars_ = ' '.join(f"-v {v}" for v in a.v)
    sh = f"""#!/bin/bash
mkdir -p /data/s3d/tmp
echo '{b64}' | base64 -d > /data/s3d/tmp/q_{name}.sql
export SQLCMDPASSWORD="$(cat /root/.mssql_sa)"
/opt/mssql-tools18/bin/sqlcmd -C -S 127.0.0.1 -U sa -d "{a.d}" -W -s '|' {vars_} -i /data/s3d/tmp/q_{name}.sql > /data/s3d/tmp/{name} 2>&1
"""
sh += f"""echo "rc=$? bytes=$(wc -c < /data/s3d/tmp/{name})"
"""
if a.o:
    sh += f"aws s3 cp --quiet /data/s3d/tmp/{name} {DBG}/{name}\n"
else:
    sh += f"head -c 2900 /data/s3d/tmp/{name}\n"
fd, p = tempfile.mkstemp(suffix='.sh'); os.write(fd, sh.encode()); os.close(fd)
env = dict(os.environ, AWS_PROFILE='annotationprod-publish')
r = subprocess.run(['/Users/dhiren/Downloads/Deccan/cad-db1-convert/venv/bin/python', '/Users/dhiren/Downloads/Deccan/cad-db1-convert/src/ssm.py',
                    'ap-south-1', 'i-02c20241cf997b48d', p, str(a.t)], env=env, capture_output=True, text=True)
print(r.stdout[-3500:], r.stderr[-1500:])
if a.o:
    loc = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'dbg', name)
    subprocess.run(['aws', 's3', 'cp', '--quiet', f'{DBG}/{name}', loc], env=env)
    print('local:', os.path.abspath(loc), os.path.getsize(loc) if os.path.exists(loc) else 'MISSING')
