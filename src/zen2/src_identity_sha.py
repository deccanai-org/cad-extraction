"""src_identity_sha.py - prove byte identity of data-4 source objects vs Disk-1 where S3 only has different checksum types
(Disk-1: SHA256, data-4: CRC64NVME): stream each data-4 object, sha256 it, compare with Disk-1's stored ChecksumSHA256."""
import base64, hashlib, json, collections, time, multiprocessing as mp
from concurrent.futures import ThreadPoolExecutor
import boto3
from botocore.config import Config
B = 'annotationprod'; A = 'cad-disk-extract/zentitude-data-4/_state/audit'


def client():
    return boto3.client('s3', region_name='ap-south-1', config=Config(max_pool_connections=64, retries={'max_attempts': 8, 'mode': 'standard'}))


def chunk(items):
    s3 = client()

    def one(u):
        try:
            body = s3.get_object(Bucket='bim-proprietary-data', Key='Zentitude-data-4/' + u['key'])['Body']
            h = hashlib.sha256()
            for part in iter(lambda: body.read(8 << 20), b''):
                h.update(part)
            ok = base64.b64encode(h.digest()).decode() == u['d1']['SHA256']
            return u['key'], 'identical (sha256)' if ok else 'DIFFERENT (sha256)'
        except Exception as e:
            return u['key'], 'read_error ' + type(e).__name__
    with ThreadPoolExecutor(32) as ex:
        return list(ex.map(one, items))


if __name__ == '__main__':
    t0 = time.time()
    items = json.loads(client().get_object(Bucket=B, Key=f'{A}/src_identity_unproven.json')['Body'].read())
    st = collections.Counter(); bad = []
    with mp.Pool(16) as pool:
        for res in pool.imap_unordered(chunk, [items[i:i + 2000] for i in range(0, len(items), 2000)]):
            for k, r in res:
                st[r] += 1
                if not r.startswith('identical'):
                    bad.append([k, r])
            print(time.strftime('%H:%M:%S'), dict(st), flush=True)
    client().put_object(Bucket=B, Key=f'{A}/src_identity_sha_result.json', Body=json.dumps({'result': dict(st), 'not_identical': bad}).encode())
    print('DONE', dict(st), 'not identical sample', bad[:5], round(time.time() - t0), 's', flush=True)
