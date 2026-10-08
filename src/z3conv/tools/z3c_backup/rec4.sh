#!/bin/bash
# (data-4 variant of rec3.sh) Recover the remaining unresolved data-4 package files that are stored nowhere (Disk-1/2 name collisions overwrote them): download each of the 20 source
# archives, extract ONLY those members (nested '!/' handled), check sha256 = manifest sha, store at
# bim cad-disk-extract/zentitude-data-4/recovered/<sha256> (S3 computes SHA-256 on upload; must equal), delete the local copy.
# Output rows for the resolver map: /opt/pkgrec4/map_rows.jsonl. Idempotent: first call starts unit z3rec4.
export AWS_DEFAULT_REGION=ap-south-1
D=/opt/pkgrec4; mkdir -p $D/work
if systemctl is-active -q z3rec4; then echo "running since $(cat $D/started)"; tail -n 4 $D/log.txt; exit 0; fi
if [ -f $D/finished ]; then echo "finished $(cat $D/finished)"; tail -n 8 $D/log.txt; exit 0; fi
if [ ! -x /usr/local/bin/7zz ]; then
  ( curl -sfL https://www.7-zip.org/a/7z2408-linux-x64.tar.xz -o /tmp/7z.tar.xz || curl -sfL https://github.com/ip7z/7zip/releases/download/24.08/7z2408-linux-x64.tar.xz -o /tmp/7z.tar.xz ) \
    && tar xJf /tmp/7z.tar.xz -C /usr/local/bin 7zz && chmod +x /usr/local/bin/7zz
fi
/usr/local/bin/7zz | sed -n 2p
cat > $D/run.py <<'PYEOF'
import json, os, subprocess, hashlib, base64, shutil, collections, time, boto3
D = '/opt/pkgrec4'; B = 'bim-proprietary-data'; Z = '/usr/local/bin/7zz'
s3 = boto3.client('s3', region_name='ap-south-1')
def log(*a): print(time.strftime('%H:%M:%SZ', time.gmtime()), *a, flush=True)
un = json.load(open('/opt/pkgd4r3/unresolved_all.json'))
arch = collections.defaultdict(dict)
for pid, us in un.items():
    if pid.startswith('Zentitude-data-4__'):
        for u in us:
            a, m = u['path'].split(' :: ', 1); arch[a][m] = u
done = {json.loads(l)['sha256'] for l in open(f'{D}/map_rows.jsonl')} if os.path.exists(f'{D}/map_rows.jsonl') else set()
out = open(f'{D}/map_rows.jsonl', 'a'); fails = open(f'{D}/fails.jsonl', 'a'); n = collections.Counter()
def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()
def extract(arc, member, outdir):
    os.makedirs(outdir, exist_ok=True)
    r = subprocess.run([Z, 'x', '-y', '-p', f'-o{outdir}', arc, member], capture_output=True, text=True, errors='replace')
    p = os.path.join(outdir, member)
    return p if os.path.isfile(p) else None, (r.stdout[-300:] + r.stderr[-300:])
for a, ms in sorted(arch.items(), key=lambda x: x[0]):
    need = {m: u for m, u in ms.items() if u['sha256'] not in done}
    if not need: continue
    loc = f'{D}/work/src{os.path.splitext(a)[1]}'
    log('download', a, len(need), 'members')
    subprocess.run(['aws', 's3', 'cp', '--only-show-errors', f's3://{B}/{a}', loc], check=True)
    for m, u in need.items():
        parts = m.split('!/'); cur = loc; ok = None; why = ''
        for i, pm in enumerate(parts):
            p, why = extract(cur, pm, f'{D}/work/x{i}')
            if not p: break
            cur = p
        else:
            ok = cur
        if not ok:
            n['not_extracted'] += 1; fails.write(json.dumps(dict(u, archive=a, why='not_extracted', tool=why)) + '\n'); fails.flush(); continue
        got = sha(ok); size = os.path.getsize(ok)
        if got != u['sha256'] or size != u['bytes']:
            n['sha_differs'] += 1; fails.write(json.dumps(dict(u, archive=a, why='sha_differs', got=got, got_bytes=size)) + '\n'); fails.flush(); continue
        key = f'cad-disk-extract/zentitude-data-4/recovered/{got}'
        with open(ok, 'rb') as f:
            r = s3.put_object(Bucket=B, Key=key, Body=f, ChecksumAlgorithm='SHA256', Metadata={'recovered-from': a[:900].encode('ascii', 'replace').decode(), 'member-sha256': got})
        s3sha = base64.b64decode(r['ChecksumSHA256']).hex()
        if s3sha != got:
            n['s3_sha_differs'] += 1; fails.write(json.dumps(dict(u, archive=a, why='s3_sha_differs')) + '\n'); continue
        row = {'sha256': got, 'bytes': size, 'key': key, 'proof': 's3_sha256', 'bucket': B, 'etag': r['ETag'].strip('"'),
               'found_by': 'recovered_from_data4_source_archive', 'source_archive': a, 'member': m, 'checked_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
        out.write(json.dumps(row) + '\n'); out.flush(); done.add(got); n['recovered'] += 1
        for i in range(len(parts)): shutil.rmtree(f'{D}/work/x{i}', ignore_errors=True)
    os.remove(loc); log('done archive', dict(n))
log('FINISHED', dict(n))
PYEOF
date -u +%FT%TZ > $D/started
systemctl reset-failed z3rec4 2>/dev/null
systemd-run --unit=z3rec4 --collect --nice=5 --working-directory=$D --setenv=AWS_DEFAULT_REGION=ap-south-1 /bin/bash -c \
  "/opt/conv/env/bin/python $D/run.py > $D/log.txt 2>&1; echo rc=\$? >> $D/log.txt; date -u +%FT%TZ > $D/finished"
sleep 20; echo "started: $(systemctl is-active z3rec4)"; tail -n 3 $D/log.txt
