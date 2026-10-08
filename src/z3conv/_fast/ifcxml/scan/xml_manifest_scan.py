#!/usr/bin/env python3
"""Stream every data-3 manifest (_state/manifests/<jid>.jsonl.gz) and keep the rows whose path ends in
.xml / .ifcxml / .ifczip / .ifc.xml (any case). Output: xml_rows.jsonl.gz (row + job id). Read-only on S3.
Low memory: each manifest is decompressed in 8 MB chunks; 6 worker processes."""
import os, sys, json, gzip, zlib, time, boto3
from multiprocessing import Pool
from botocore.config import Config
B = 'bim-proprietary-data'; P = 'cad-disk-extract/zenitude-data-3/_state/manifests/'
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'xml_rows')
NEEDLES = (b'.xml"', b'.ifcxml"', b'.ifczip"')

def s3():
    return boto3.session.Session(profile_name='bim').client('s3', region_name='ap-south-1',
        config=Config(retries={'max_attempts': 20, 'mode': 'standard'}, read_timeout=300))

def one(args):
    key, = args
    jid = key.rsplit('/', 1)[-1].split('.')[0]
    outp = os.path.join(OUT, jid + '.jsonl')
    if os.path.exists(outp):
        return jid, -1, 0
    c = s3()
    for att in range(5):
        try:
            body = c.get_object(Bucket=B, Key=key)['Body']
            d = zlib.decompressobj(16 + zlib.MAX_WBITS)
            carry = b''; hits = []; nrows = 0
            while True:
                raw = body.read(4 << 20)
                if not raw:
                    data = carry + d.flush(); carry = b''
                else:
                    data = carry + d.decompress(raw)
                    cut = data.rfind(b'\n')
                    if cut < 0:
                        carry = data; continue
                    carry = data[cut + 1:]; data = data[:cut + 1]
                nrows += data.count(b'\n')
                low = data.lower()
                for nd in NEEDLES:
                    i = low.find(nd)
                    while i >= 0:
                        a = data.rfind(b'\n', 0, i) + 1; z = data.find(b'\n', i)
                        if z < 0: z = len(data)
                        line = data[a:z]
                        try:
                            e = json.loads(line)
                            if e.get('path', '').lower().endswith(('.xml', '.ifcxml', '.ifczip')):
                                e['job'] = jid; hits.append(e)
                        except Exception:
                            pass
                        i = low.find(nd, z)
                if not raw:
                    break
            with open(outp + '.tmp', 'w') as f:
                for e in hits:
                    f.write(json.dumps(e) + '\n')
            os.replace(outp + '.tmp', outp)
            return jid, nrows, len(hits)
        except Exception as ex:
            if att == 4:
                return jid, -2, str(ex)[:200]
            time.sleep(3 * (att + 1))

if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    c = s3(); keys = []
    for pg in c.get_paginator('list_objects_v2').paginate(Bucket=B, Prefix=P):
        for o in pg.get('Contents', []):
            keys.append((o['Key'], o['Size']))
    keys.sort(key=lambda x: -x[1])
    print(time.strftime('%H:%M:%S'), 'manifests', len(keys), 'bytes', sum(s for _, s in keys), flush=True)
    t0 = time.time(); done = 0; tot_rows = 0; tot_hits = 0; done_b = 0; sz = dict(keys)
    with Pool(int(os.environ.get('NPROC', '6'))) as pool:
        for jid, n, h in pool.imap_unordered(one, [(k,) for k, _ in keys], chunksize=1):
            done += 1
            if n == -2:
                print('ERROR', jid, h, flush=True)
            elif n >= 0:
                tot_rows += n; tot_hits += h
            if done % 200 == 0 or done == len(keys):
                print(time.strftime('%H:%M:%S'), f'{done}/{len(keys)} rows={tot_rows} hits={tot_hits} {time.time()-t0:.0f}s', flush=True)
    print('DONE', flush=True)
