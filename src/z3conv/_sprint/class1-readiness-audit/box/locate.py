"""locate.py IDS_JSON MAX_GB : the model folder's own catalogs (screwdb.db, assdb.db, profdb.bin) that are NOT next to the extracted DB1
(Disk-1/2 / data-4 extractions kept only the .db1): pulled from the model's data-3 source archive (zip / 7z / rar, nested 'x.zip!/'),
same folder as the DB1 inside the archive, case-insensitive name. -> src/<sha12>_sib/<name> + locate_report.json"""
import json, os, sys, subprocess, hashlib, shutil, boto3, concurrent.futures as cf, threading
s3 = boto3.client('s3', region_name='ap-south-1'); B = 'bim-proprietary-data'
W = {'screwdb.db', 'assdb.db', 'profdb.bin'}
MAXB = float(sys.argv[2]) * (1 << 30)
AR = os.path.abspath('arch'); os.makedirs(AR, exist_ok=True)
Z = '/usr/local/bin/7zz'
lock = {}; glock = threading.Lock()


def members(arch):
    r = subprocess.run([Z, 'l', '-slt', '-ba', arch], capture_output=True, text=True, errors='replace', timeout=1800)
    out = []
    for blk in r.stdout.split('\n\n'):
        kv = dict(l.split(' = ', 1) for l in blk.splitlines() if ' = ' in l)
        if kv.get('Path') and kv.get('Folder') != '+': out.append(kv['Path'])
    return out


def extract(arch, member, dest_dir):
    os.makedirs(dest_dir, exist_ok=True)
    r = subprocess.run([Z, 'e', '-y', '-o' + dest_dir, arch, member], capture_output=True, text=True, errors='replace', timeout=3600)
    p = os.path.join(dest_dir, os.path.basename(member.replace('\\', '/')))
    return p if r.returncode == 0 and os.path.exists(p) else None


def get_archive(key):
    with glock:
        lk = lock.setdefault(key, threading.Lock())
    with lk:
        h = hashlib.md5(key.encode()).hexdigest()[:16]; p = os.path.join(AR, h + os.path.splitext(key)[1].lower())
        if not os.path.exists(p):
            sz = s3.head_object(Bucket=B, Key=key)['ContentLength']
            if sz > MAXB: return None, f'archive {sz / 2**30:.1f} GB > limit'
            s3.download_file(B, key, p + '.part'); os.replace(p + '.part', p)
        return p, None


def one(j):
    sha = j['sha256']; sd = os.path.join('src', sha[:12] + '_sib'); os.makedirs(sd, exist_ok=True)
    want = {s.lower() for s in j.get('siblings') or []} & W
    have = {f for f in os.listdir(sd) if f in W}
    need = want - have
    rep = {'want': sorted(want), 'had': sorted(have), 'got': [], 'how': None}
    if not need: return sha, rep
    for path in j.get('paths') or []:
        if ' :: ' not in path: continue
        arch, inner = path.split(' :: ', 1)
        try:
            if arch.endswith('/'):                      # plain data-3 folder
                d = 'Zenitude-data-3/' + inner.rsplit('/', 1)[0] + '/'
                lst = s3.list_objects_v2(Bucket=B, Prefix=d, Delimiter='/').get('Contents', [])
                for o in lst:
                    n = o['Key'][len(d):]
                    if n.lower() in need and not os.path.exists(os.path.join(sd, n.lower())):
                        s3.download_file(B, o['Key'], os.path.join(sd, n.lower())); rep['got'].append(n.lower()); rep['how'] = 'data3 folder ' + d
            else:
                ap, err = get_archive(arch)
                if not ap: rep['how'] = err; continue
                parts = inner.split('!/')
                cur = ap; tmpd = os.path.join(AR, sha[:12] + '_x'); os.makedirs(tmpd, exist_ok=True)
                for nest in parts[:-1]:                 # nested archives: x.zip!/...
                    ms = members(cur)
                    m = next((x for x in ms if x.replace('\\', '/') == nest), None)
                    if not m: raise RuntimeError(f'nested member not found {nest[-80:]}')
                    cur = extract(cur, m, os.path.join(tmpd, hashlib.md5(nest.encode()).hexdigest()[:8]))
                    if not cur: raise RuntimeError('nested extract failed')
                d = parts[-1].rsplit('/', 1)[0] + '/' if '/' in parts[-1] else ''
                for m in members(cur):
                    mm = m.replace('\\', '/')
                    if mm.lower().startswith(d.lower()) and '/' not in mm[len(d):] and mm[len(d):].lower() in need:
                        n = mm[len(d):].lower()
                        if os.path.exists(os.path.join(sd, n)): continue
                        p = extract(cur, m, tmpd)
                        if p: shutil.move(p, os.path.join(sd, n)); rep['got'].append(n); rep['how'] = 'archive ' + arch[-120:]
                shutil.rmtree(tmpd, ignore_errors=True)
        except Exception as e:
            rep['err'] = f'{type(e).__name__}: {str(e)[:200]}'
        need = want - {f for f in os.listdir(sd) if f in W}
        if not need: break
    rep['missing'] = sorted(want - {f for f in os.listdir(sd) if f in W})
    return sha, rep


ids = json.load(open(sys.argv[1]))
with cf.ThreadPoolExecutor(6) as ex:
    R = dict(ex.map(one, ids))
json.dump(R, open('locate_report.json', 'w'), indent=1)
s3.upload_file('locate_report.json', B, 'cad-disk-extract/zenitude-data-3/_state/agentwork/class1-readiness-audit/locate_report.json')
print(sum(1 for r in R.values() if r['got']), 'models got files;', sum(1 for r in R.values() if r.get('missing')), 'still missing;',
      sum(1 for r in R.values() if {'screwdb.db', 'assdb.db'} <= set(r['had']) | set(r['got'])), 'with screwdb+assdb')
shutil.rmtree(AR, ignore_errors=True)
