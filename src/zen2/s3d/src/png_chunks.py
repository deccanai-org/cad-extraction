"""Optional PNG previews from converted GLBs (runs on the SQL box after the fan-out): one iso view per IFC chunk.

png_chunks.py [--procs 4]   (resumable: skips chunks whose PNG already exists in s3 model/png/)
"""
import os, sys, json, glob, time, subprocess, argparse
import multiprocessing as mp
from common import *

PNG_PRE = S3_PREFIX + '/png/'


def _one(r):
    import boto3
    s3 = boto3.client('s3')
    key = r['glb']['key']
    area_id = key.split('/model/gltf/', 1)[1][:-4]           # <area>/<id>
    d = os.path.join(WORK, 'pngtmp', r['id']); os.makedirs(d, exist_ok=True)
    g = os.path.join(d, 'm.glb')
    try:
        s3.download_file(S3_BUCKET, key, g)
        p = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'render.py'), os.path.join(d, 'r'), g,
                            '--views', 'iso_ne', '--size', '1280x960'], capture_output=True, text=True, timeout=1800)
        out = json.loads(p.stdout.strip().splitlines()[-1])
        for x in out:
            s3.upload_file(x['png'], S3_BUCKET, '%s%s__%s.png' % (PNG_PRE, area_id, x['view']))
        return r['id'], 'ok'
    except Exception as e:
        return r['id'], 'fail %s' % str(e)[:120]
    finally:
        subprocess.run(['rm', '-rf', d])


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--procs', type=int, default=4); a = ap.parse_args()
    conv = json.load(open(os.path.join(WORK, 'conversions.json')))
    import boto3
    s3 = boto3.client('s3'); have = set()
    for page in s3.get_paginator('list_objects_v2').paginate(Bucket=S3_BUCKET, Prefix=PNG_PRE):
        for o in page.get('Contents', []):
            have.add(o['Key'])
    todo = [r for r in conv.values() if (r.get('glb') or {}).get('ok') and
            '%s%s__iso_ne.png' % (PNG_PRE, r['glb']['key'].split('/model/gltf/', 1)[1][:-4]) not in have]
    todo.sort(key=lambda r: (r.get('glb') or {}).get('bytes') or 0)
    log('png chunks to render: %d (have %d)' % (len(todo), len(have)))
    n = 0
    with mp.get_context('spawn').Pool(a.procs, maxtasksperchild=20) as pool:
        for i, st in pool.imap_unordered(_one, todo):
            n += 1
            if n % 25 == 0 or st != 'ok':
                log('%d/%d %s %s' % (n, len(todo), i, st))
    log('png done %d' % n)


if __name__ == '__main__':
    main()
