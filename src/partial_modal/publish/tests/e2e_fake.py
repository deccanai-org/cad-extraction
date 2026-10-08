"""End-to-end publisher test against the FAKE package target only (s3://.../_state/pmp/fakepkg/<pid>/), run on the Mac:

    python3 publish/tests/e2e_fake.py [--from-step N]

Uses the real n4 package's pid (its manifest.jsonl was copied into the fake target by `box.py fakepkg`) and its 3 real model
ids (GRID3, GRID2, P535_TRUSS) + n3's model id (not in that package) with synthetic, labelled fixture bundles. Uploads go
through pre-signed PUT URLs made on the box (bundle_lib.upload_bundle, the same code Modal uses); every publish runs on the
box (box.py publish). Writes happen only under _state/pmp/ (bundles/test/, presign/test.json, fakepkg/, publish/).
Checks after each step: statuses, exit codes, uploaded/skipped counts, the published tree (tests/verify_published.py,
read-only, AWS_PROFILE=bim), the fake package's objects outside scripts/ unchanged, and finally the 5 REAL new-sample
packages unchanged vs the snapshot taken before the tests.
"""
import argparse
import gzip
import hashlib
import io
import json
import os
import subprocess
import re
import sys
import tarfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PUB = os.path.dirname(HERE)
sys.path.insert(0, PUB)
sys.path.insert(0, HERE)
import box as BX  # noqa: E402
import bundle_lib as BL  # noqa: E402
import fixtures as FX  # noqa: E402

SP = os.environ.get('PMP_TEST_DIR', '/private/tmp/claude-501/-Users-dhiren-Downloads-Deccan/5462df30-9e2f-4b34-a06f-5d008d800062/scratchpad/pubtest')
NEW5 = json.load(open(os.path.join(PUB, '..', 'new5.json')))
PID = NEW5[3]['pid']
GRID3 = '701f5f69cd9124a9b61555c2e8e728468d2d1adadaab3cea8eee0ff98822fbbb'
GRID2 = '1f2681d69185985014467fba06320dd77cfb50cca301d6a8f2ae408458a49bc4'
TRUSS = '006f0214842f27657f97c8885014131354fae71164b6240d408740cf14ec5c9e'
N3 = NEW5[2]['model_id']
FAKE = 'cad-disk-extract/_state/pmp/fakepkg/'
RESULTS = []


def box(*args, timeout=900):
    r = subprocess.run([sys.executable, os.path.join(PUB, 'box.py')] + list(args), capture_output=True, text=True, timeout=timeout)
    out = r.stdout
    try:
        js = json.loads(out[out.index('{'):out.rindex('}') + 1]) if '"summary"' in out else None
    except ValueError:
        js = None
    m = re.search(r'\[publisher exit (\d+)\]', out)
    return (int(m.group(1)) if m else r.returncode), js, out + r.stderr


def publish(*extra, dry=False):
    a = ['publish', '--run', 'test', '--target', 'fake', '--allow-pids', os.path.join(PUB, '..', 'new5.json')] + list(extra)
    if dry:
        a.append('--dry-run')
    return box(*a)


def by_model(js):
    return {b['model_id']: b for b in (js or {}).get('bundles', [])}


def check(step, name, cond, info=''):
    RESULTS.append(dict(step=step, check=name, ok=bool(cond), info=str(info)[:600] if not cond else ''))
    print(f'  {"ok  " if cond else "FAIL"} {name}' + (f'   [{str(info)[:600]}]' if not cond else ''))


def urls():
    return json.load(open(os.path.join(PUB, 'presigned', 'test.json')))['urls']


def bundle(name, mid, folder, **kw):
    out, info = FX.make(os.path.join(SP, name), 'test', kw.pop('pid', PID), mid, folder, kw.pop('relpath', f'model/step/{folder}.step'),
                        work=os.path.join(SP, name, '_work'), **kw)
    return out, info


def upload(path, mid):
    return BL.upload_bundle(path, urls()[mid]['url'])


def verify(step, fixtures, expect_models):
    r = subprocess.run([sys.executable, os.path.join(HERE, 'verify_published.py'), '--root', FAKE, '--pid', PID, '--out',
                        os.path.join(SP, f'dl_{step}'), '--fixtures'] + fixtures, capture_output=True, text=True,
                       env=dict(os.environ, AWS_PROFILE='bim'))
    try:
        d = json.loads(r.stdout)
    except ValueError:
        d = {}
    check(step, f'published tree consistent (manifest == files, sha256s, fixtures byte-identical): {d.get("files")} files',
          r.returncode == 0, r.stdout[-500:] + r.stderr[-300:])
    check(step, f'model folders = {sorted(expect_models)}', sorted(d.get('model_folders', {})) == sorted(expect_models), d.get('model_folders'))
    return d


def outside_snapshot():
    r = subprocess.run(['aws', 's3api', 'list-objects-v2', '--bucket', 'bim-proprietary-data', '--prefix', f'{FAKE}{PID}/', '--query',
                        'Contents[].[Key,ETag,Size]', '--output', 'json'], capture_output=True, text=True, env=dict(os.environ, AWS_PROFILE='bim'))
    return sorted(tuple(x) for x in json.loads(r.stdout or '[]') if '/scripts/' not in x[0])


def manifest_sha():
    r = subprocess.run(['aws', 's3api', 'head-object', '--bucket', 'bim-proprietary-data', '--key', f'{FAKE}{PID}/scripts/scripts_manifest.jsonl',
                        '--query', 'ETag', '--output', 'text'], capture_output=True, text=True, env=dict(os.environ, AWS_PROFILE='bim'))
    return r.stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--from-step', type=int, default=1)
    a = ap.parse_args()
    os.makedirs(SP, exist_ok=True)
    out0 = outside_snapshot()
    fx = {}

    print('step 1: presign 4 URLs on the box (run test)')
    rc, js, out = box('presign', '--run', 'test', '--model-id', GRID3, '--model-id', GRID2, '--model-id', TRUSS, '--model-id', N3,
                      '--min-valid-minutes', '20')
    check(1, 'presign ok, 4 URLs', rc == 0 and len(urls()) == 4, out[-400:])

    print('step 2: re-run on the already published GRID3 bundle -> already_published (idempotent, nothing written)')
    m0 = manifest_sha()
    rc, js, out = publish()
    b = by_model(js).get(GRID3, {})
    check(2, 'exit 0 + already_published', rc == 0 and b.get('status') == 'already_published', out[-600:])
    check(2, 'manifest untouched', manifest_sha() == m0)

    print('step 3: --recheck -> full re-verify, every file skipped, manifest not rewritten')
    rc, js, out = publish('--recheck')
    b = by_model(js).get(GRID3, {})
    check(3, 'exit 0 + published with 0 uploads / 15 skipped', rc == 0 and b.get('status') == 'published' and b.get('uploaded') == 0
          and b.get('skipped') == 15, out[-600:])
    check(3, 'manifest untouched (same ETag)', manifest_sha() == m0)

    print('step 4: second model GRID2 (same shared files) -> merged, shared files skipped')
    p, inf = bundle('g2', GRID2, 'GRID2')
    fx['GRID2'] = os.path.join(SP, 'g2', '_work', 'scripts')
    fx['GRID3'] = [os.path.join(SP, 'b1', '_work', d, 'scripts') for d in os.listdir(os.path.join(SP, 'b1', '_work'))][0]
    up = upload(p, GRID2)
    check(4, 'upload_bundle: HTTP 200 and ETag == MD5', up['status'] == 200 and up['etag_is_md5'], up)
    rc, js, out = publish(dry=True)
    b = by_model(js).get(GRID2, {})
    check(4, 'dry run: would_publish 11 uploads, 4 shared skipped', rc == 0 and b.get('status') == 'would_publish' and b.get('uploaded') == 11
          and b.get('skipped') == 4, out[-600:])
    rc, js, out = publish()
    b = by_model(js).get(GRID2, {})
    check(4, 'published 11 uploads / 4 skipped, outside unchanged', rc == 0 and b.get('status') == 'published' and b.get('uploaded') == 11
          and b.get('skipped') == 4 and b.get('outside_unchanged') is True and b.get('manifest_rows') == 26, out[-600:])
    verify(4, [fx['GRID3'], fx['GRID2']], ['GRID2', 'GRID3'])

    print('step 5: TRUSS bundle whose shared README differs -> refused, nothing written')
    p, inf = bundle('t_conf', TRUSS, 'P535_TRUSS', readme_extra='a different README\n')
    upload(p, TRUSS)
    m1 = manifest_sha()
    rc, js, out = publish()
    b = by_model(js).get(TRUSS, {})
    check(5, 'exit 2 + refused shared_file_conflict', rc == 2 and b.get('status') == 'refused' and b.get('reason') == 'shared_file_conflict', out[-600:])
    check(5, 'manifest untouched', manifest_sha() == m1)
    verify(5, [fx['GRID3'], fx['GRID2']], ['GRID2', 'GRID3'])

    print('step 6: TRUSS bundle claiming folder GRID3 (owned by another model) -> refused model_folder_taken')
    p, inf = bundle('t_fold', TRUSS, 'GRID3', relpath='model/step/P535_TRUSS.step')
    upload(p, TRUSS)
    rc, js, out = publish()
    b = by_model(js).get(TRUSS, {})
    check(6, 'refused model_folder_taken', rc == 2 and b.get('reason') == 'model_folder_taken', out[-600:])

    print('step 7: n3 model (another package) claiming this package -> refused model_not_in_package')
    p, inf = bundle('n3', N3, 'GCP3', relpath='model/step/31-2214 GCP3_STL-e7a9c8.step')
    upload(p, N3)
    rc, js, out = publish('--models', N3)
    b = by_model(js).get(N3, {})
    check(7, 'refused model_not_in_package', rc == 2 and b.get('reason') == 'model_not_in_package', out[-600:])

    print('step 8: tampered bundle (file changed after its row was written) -> refused at verification')
    src = p
    tp = os.path.join(SP, 'n3', 'tampered.tar.gz')
    with tarfile.open(src, 'r:gz') as tf:
        mem = [(m, tf.extractfile(m).read()) for m in tf.getmembers()]
    with open(tp, 'wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as gz, \
            tarfile.open(fileobj=gz, mode='w', format=tarfile.PAX_FORMAT) as tf:
        for m, d in mem:
            if m.name.endswith('build_model.py'):
                d += b'# tampered\n'
            m.size = len(d)
            tf.addfile(m, io.BytesIO(d))
    upload(tp, N3)
    rc, js, out = publish('--models', N3)
    b = by_model(js).get(N3, {})
    check(8, 'refused sha_mismatch', rc == 2 and b.get('reason') == 'sha_mismatch', out[-600:])

    print('step 9: GRID2 re-published with a changed build_model.py -> refused without --allow-update, overwritten with it')
    tree = FX.make_tree(os.path.join(SP, 'g2b', 'scripts'), 'GRID2', GRID2)
    with open(os.path.join(tree, 'GRID2', 'build_model.py'), 'a') as f:
        f.write('# v2\n')
    hdr = dict(run='test', model_id=GRID2, pid=PID, model_folder='GRID2', step_relpath='model/step/GRID2.step', step_source='ifc',
               code_version='pmp-test-fixture/1')
    p = os.path.join(SP, 'g2b', 'v2.tar.gz')
    BL.make_bundle(tree, p, hdr, lambda rel: f'test fixture: publish/tests/fixtures.py ({rel})')
    upload(p, GRID2)
    rc, js, out = publish()
    b = by_model(js).get(GRID2, {})
    check(9, 'refused model_file_differs', rc == 2 and b.get('reason') == 'model_file_differs', out[-600:])
    rc, js, out = publish('--allow-update', '--models', GRID2)
    b = by_model(js).get(GRID2, {})
    check(9, '--allow-update: published, 1 file overwritten', rc == 0 and b.get('status') == 'published' and b.get('uploaded') == 1, out[-600:])
    fx['GRID2'] = tree
    verify(9, [fx['GRID3'], fx['GRID2']], ['GRID2', 'GRID3'])

    print('step 10: GRID2 bundle lacking a published file -> refused would_need_delete even with --allow-update')
    tree3 = FX.make_tree(os.path.join(SP, 'g2c', 'scripts'), 'GRID2', GRID2, n_missing=0)
    with open(os.path.join(tree3, 'GRID2', 'build_model.py'), 'a') as f:
        f.write('# v2\n')
    p = os.path.join(SP, 'g2c', 'v3.tar.gz')
    BL.make_bundle(tree3, p, hdr, lambda rel: f'test fixture: publish/tests/fixtures.py ({rel})')
    upload(p, GRID2)
    rc, js, out = publish('--allow-update', '--models', GRID2)
    b = by_model(js).get(GRID2, {})
    check(10, 'refused would_need_delete', rc == 2 and b.get('reason') == 'would_need_delete', out[-600:])

    print('step 11: crash after 3 uploads (test hook) -> error, manifest does not list the half-published model; re-run completes it')
    p, inf = bundle('t_ok', TRUSS, 'P535_TRUSS')
    fx['P535_TRUSS'] = os.path.join(SP, 't_ok', '_work', 'scripts')
    upload(p, TRUSS)
    m2 = manifest_sha()
    rc, js, out = publish('--models', TRUSS, '--test-fail-after', '3')
    b = by_model(js).get(TRUSS, {})
    check(11, 'exit 1 + error publish_failed', rc == 1 and b.get('status') == 'error' and b.get('reason') == 'publish_failed', out[-600:])
    check(11, 'manifest (commit record) not rewritten after the crash', manifest_sha() == m2)
    rc, js, out = publish('--models', TRUSS)
    b = by_model(js).get(TRUSS, {})
    check(11, 're-run: published, 3 orphans recognised by their sha256 (8 uploads, 7 skipped)', rc == 0 and b.get('status') == 'published'
          and b.get('uploaded') == 8 and b.get('skipped') == 7, out[-600:])
    verify(11, [fx['GRID3'], fx['GRID2'], fx['P535_TRUSS']], ['GRID2', 'GRID3', 'P535_TRUSS'])

    print('step 12: package lock held by another publisher -> refused locked (no write)')
    lk = f'cad-disk-extract/_state/pmp/publish/locks/fake/{hashlib.sha1(PID.encode()).hexdigest()[:20]}.lock'
    s = (f'echo \'{{"pid": "x", "run": "other", "host": "test", "at": "{time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}"}}\' > /tmp/pmp_lock.json && '
         f'aws s3api put-object --bucket bim-proprietary-data --key {lk} --body /tmp/pmp_lock.json --query ETag --output text')
    ok, o, e = BX.ssm(s, 60, quiet=True)
    rc, js, out = publish('--recheck', '--models', GRID3)
    b = by_model(js).get(GRID3, {})
    check(12, 'refused locked', rc == 2 and b.get('reason') == 'locked', out[-600:])
    ok, o, e = BX.ssm(f'aws s3 rm --only-show-errors s3://bim-proprietary-data/{lk} && echo removed', 60, quiet=True)
    check(12, 'test lock removed', ok and 'removed' in o, o + e)

    print('step 13: expired pre-signed URL -> upload_bundle raises a clear error without leaking the signature')
    ok, o, e = BX.ssm(f'cd {BX.REMOTE} && {BX.PY} presign_put.py --run test --model-id {GRID3} --min-valid-minutes 0 --expires-seconds 1 > /dev/null && echo signed', 120, quiet=True)
    BX.aws(['s3', 'cp', '--only-show-errors', 's3://bim-proprietary-data/cad-disk-extract/_state/pmp/presign/test.json',
            os.path.join(PUB, 'presigned', 'test.json')], 'bim')
    os.chmod(os.path.join(PUB, 'presigned', 'test.json'), 0o600)
    time.sleep(3)
    try:
        upload(os.path.join(SP, 'b1', f'{GRID3}.tar.gz'), GRID3)
        check(13, 'expired URL refused', False, 'upload succeeded')
    except RuntimeError as e:
        msg = str(e)
        check(13, 'expired URL refused (HTTP 403, not retried)', 'HTTP 403' in msg, msg)
        check(13, 'error message carries no signature / token', 'Signature=' not in msg and 'Security-Token' not in msg, msg)

    print('step 14: the fake package outside scripts/ and the 5 REAL packages are unchanged')
    check(14, 'fake package objects outside scripts/ unchanged', outside_snapshot() == out0)
    before = json.load(open(os.path.join(SP, 'real5_before.json')))
    for r in NEW5:
        res = subprocess.run(['aws', 's3api', 'list-objects-v2', '--bucket', 'bim-proprietary-data', '--prefix',
                              f'cad-disk-extract/dataset/packages/3d_partial/{r["pid"]}/', '--query', 'Contents[].[Key,ETag,Size]', '--output', 'json'],
                             capture_output=True, text=True, env=dict(os.environ, AWS_PROFILE='bim'))
        now = json.loads(res.stdout or '[]')
        check(14, f'real package {r["tag"]}: {len(now)} objects, keys/ETags/sizes unchanged, no scripts/', now == before[r['pid']]
              and not any('/scripts/' in x[0] for x in now))
    nf = sum(1 for x in RESULTS if not x['ok'])
    json.dump(RESULTS, open(os.path.join(PUB, 'logs', 'e2e_fake_results.json'), 'w'), indent=1)
    print(f'{len(RESULTS) - nf}/{len(RESULTS)} checks passed' + (f', {nf} FAILED' if nf else ''))
    return 1 if nf else 0


if __name__ == '__main__':
    sys.exit(main())
