"""The basic publish test from a CLEAN test state, against the FAKE package target only (run on the Mac):

    python3 publish/tests/basic_fake.py

 0. snapshot the 5 REAL new-sample packages (read-only, AWS_PROFILE=bim) -> $PMP_TEST_DIR/real5_before.json
 1. box.py clean-test (deletes ONLY the publisher's test state under _state/pmp/) + box.py fakepkg for n4's pid
    (copies the real manifest.jsonl + project.json into _state/pmp/fakepkg/<pid>/)
 2. build a tiny, labelled fixture bundle for n4's model GRID3 (tests/fixtures.py: no geometry)
 3. box.py presign: 1 PUT URL for _state/pmp/bundles/test/<GRID3>.tar.gz (made on the box with its role)
 4. curl PUT of the bundle (the URL goes to curl on stdin, never on a command line or in a log); HTTP 200 + ETag == MD5
 5. publisher --dry-run: would_publish 15 uploads; nothing written under the fake package's scripts/
 6. publisher for real: published 15 uploads, objects outside scripts/ unchanged; tests/verify_published.py (read-only):
    manifest == files, sha256s, content byte-identical to the fixture
 7. publisher again: already_published, the manifest not rewritten
 8. the 5 REAL packages unchanged (keys, ETags, sizes), none has scripts/
Results -> publish/logs/basic_fake_results.json. Then tests/e2e_fake.py continues from this state.
"""
import hashlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import e2e_fake as E  # noqa: E402  (box(), publish(), check(), verify(), outside_snapshot(), manifest_sha(), constants)

FX, BL, BX = E.FX, E.BL, E.BX


def real5_snapshot():
    snap = {}
    for r in E.NEW5:
        res = subprocess.run(['aws', 's3api', 'list-objects-v2', '--bucket', 'bim-proprietary-data', '--prefix',
                              f'cad-disk-extract/dataset/packages/3d_partial/{r["pid"]}/', '--query', 'Contents[].[Key,ETag,Size]',
                              '--output', 'json'], capture_output=True, text=True, env=dict(os.environ, AWS_PROFILE='bim'), check=True)
        snap[r['pid']] = json.loads(res.stdout or '[]')
    return snap


def curl_put(path, url):
    """PUT with curl; the URL is passed in a curl config on stdin (not visible in argv / ps / logs)"""
    hdr = os.path.join(E.SP, 'curl_headers.txt')
    cfg = f'url = "{url}"\n'
    r = subprocess.run(['curl', '-sS', '-o', '/dev/null', '-D', hdr, '-w', '%{http_code}', '-T', path, '-H',
                        'Content-Type: application/gzip', '-K', '-'], input=cfg, capture_output=True, text=True, timeout=300)
    etag = ''
    for ln in open(hdr, encoding='utf-8', errors='replace'):
        if ln.lower().startswith('etag:'):
            etag = ln.split(':', 1)[1].strip().strip('"')
    os.remove(hdr)
    return r.stdout.strip(), etag, r.stderr.replace(url, '<url>')[-300:]


def main():
    os.makedirs(E.SP, exist_ok=True)
    print('step 0: snapshot the 5 REAL packages (read-only)')
    before = real5_snapshot()
    json.dump(before, open(os.path.join(E.SP, 'real5_before.json'), 'w'), indent=1)
    E.check(0, 'real packages listed, none has scripts/', all(before.values()) and not any('/scripts/' in x[0] for v in before.values() for x in v))

    print('step 1: clean test state + fake package for n4')
    rc, _, out = E.box('clean-test')
    E.check(1, 'clean-test ok', rc == 0, out[-300:])
    rc, _, out = E.box('fakepkg', '--pid', E.PID)
    E.check(1, 'fake package = real manifest.jsonl + project.json only', rc == 0 and out.count('fakepkg/') == 2 and '/scripts/' not in out, out[-400:])
    out0 = E.outside_snapshot()

    print('step 2: tiny labelled fixture bundle for GRID3')
    import shutil
    shutil.rmtree(os.path.join(E.SP, 'b1'), ignore_errors=True)
    path, info = FX.make(os.path.join(E.SP, 'b1'), 'test', E.PID, E.GRID3, 'GRID3', 'model/step/GRID3.step')   # tree: b1/_work/<id>/scripts
    E.check(2, f'fixture bundle {info["n_files"]} files, {info["bytes"]} B, sha256 {info["sha256"][:12]}', info['n_files'] == 15)

    print('step 3: presign 1 PUT URL on the box')
    rc, _, out = E.box('presign', '--run', 'test', '--model-id', E.GRID3, '--min-valid-minutes', '20')
    d = json.load(open(os.path.join(E.PUB, 'presigned', 'test.json')))
    E.check(3, f'1 URL for {d["urls"][E.GRID3]["key"].rsplit("/", 2)[-2]}/<GRID3>.tar.gz, expires {d["expires_utc"]} '
               f'(credentials {d["credential_expiration_utc"]})', rc == 0 and d['n'] == 1 and
            d['urls'][E.GRID3]['key'] == f'cad-disk-extract/_state/pmp/bundles/test/{E.GRID3}.tar.gz', out[-300:])
    E.check(3, 'presign file is mode 0600 on the Mac', oct(os.stat(os.path.join(E.PUB, 'presigned', 'test.json')).st_mode & 0o777) == '0o600')
    E.check(3, 'no URL printed by box.py presign', 'X-Amz-Signature' not in out and 'Security-Token' not in out)

    print('step 4: curl PUT')
    code, etag, err = curl_put(path, d['urls'][E.GRID3]['url'])
    md5 = hashlib.md5(open(path, 'rb').read()).hexdigest()
    E.check(4, f'curl HTTP {code}, ETag == MD5 of the bundle', code == '200' and etag == md5, f'{code} {etag} {md5} {err}')

    print('step 5: publisher --dry-run')
    rc, js, out = E.publish(dry=True)
    b = E.by_model(js).get(E.GRID3, {})
    E.check(5, 'exit 0, would_publish 15 uploads / 0 skipped, manifest preview 15 rows', rc == 0 and b.get('status') == 'would_publish'
            and b.get('uploaded') == 15 and b.get('skipped') == 0 and b.get('manifest_rows') == 15, out[-600:])
    ls = subprocess.run(['aws', 's3', 'ls', '--recursive', f's3://bim-proprietary-data/{E.FAKE}{E.PID}/scripts/'], capture_output=True,
                        text=True, env=dict(os.environ, AWS_PROFILE='bim'))
    E.check(5, 'dry run wrote nothing under the fake package scripts/', ls.stdout.strip() == '', ls.stdout[-300:])

    print('step 6: publisher for real')
    rc, js, out = E.publish()
    b = E.by_model(js).get(E.GRID3, {})
    E.check(6, 'exit 0, published 15 uploads, outside scripts/ unchanged, manifest 15 rows', rc == 0 and b.get('status') == 'published'
            and b.get('uploaded') == 15 and b.get('outside_unchanged') is True and b.get('manifest_rows') == 15, out[-600:])
    E.verify(6, [os.path.join(E.SP, 'b1', '_work', E.GRID3, 'scripts')], ['GRID3'])
    E.check(6, 'fake package objects outside scripts/ unchanged (Mac listing)', E.outside_snapshot() == out0)

    print('step 7: publisher again -> already_published, nothing rewritten')
    m0 = E.manifest_sha()
    rc, js, out = E.publish()
    b = E.by_model(js).get(E.GRID3, {})
    E.check(7, 'exit 0 + already_published', rc == 0 and b.get('status') == 'already_published', out[-600:])
    E.check(7, 'manifest ETag unchanged', E.manifest_sha() == m0)

    print('step 8: the 5 REAL packages unchanged')
    after = real5_snapshot()
    for r in E.NEW5:
        E.check(8, f'real package {r["tag"]}: {len(after[r["pid"]])} objects unchanged, no scripts/', after[r['pid']] == before[r['pid']]
                and not any('/scripts/' in x[0] for x in after[r['pid']]))
    nf = sum(1 for x in E.RESULTS if not x['ok'])
    json.dump(E.RESULTS, open(os.path.join(E.PUB, 'logs', 'basic_fake_results.json'), 'w'), indent=1)
    print(f'{len(E.RESULTS) - nf}/{len(E.RESULTS)} checks passed' + (f', {nf} FAILED' if nf else ''))
    return 1 if nf else 0


if __name__ == '__main__':
    sys.exit(main())
