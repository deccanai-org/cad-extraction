"""Write-guard unit test - runs ON the box (needs boto3; makes no S3 calls): /opt/pm/venv/bin/python tests/test_guards.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import publisher as P  # noqa: E402

R, S, L = P.TARGETS['packages'], P.STATE, P.PUBLOG
fails = []


def t(name, cond):
    print(('ok   ' if cond else 'FAIL ') + name)
    if not cond:
        fails.append(name)


real = P.Store('packages', {'P1', 'P 2#x.7z'}, dry_run=False)
for k in (R + 'P1/scripts/a.py', R + 'P1/scripts/M/schedules/parts.csv', R + 'P 2#x.7z/scripts/README.md', L + 'test.jsonl',
          L + 'locks/packages/abc.lock'):
    t(f'packages: allowed {k}', real._write_ok(k))
for k in (R + 'P1/manifest.jsonl', R + 'P1/project.json', R + 'P1/model/step/x.step', R + 'P1/scripts', R + 'P1/scripts/',
          R + 'P2/scripts/a.py', R + 'P1/scriptsX/a', R + 'P1/drawings/scripts/a', 'cad-disk-extract/dataset/packages/3d/P1/scripts/a',
          S + 'bundles/test/x.tar.gz', S + 'presign/test.json', S + 'fakepkg/P1/scripts/a', R + 'P1/scripts/../manifest.jsonl',
          R + 'P1/scripts//a', R + 'P1/scripts/./a', 'cad-disk-extract/_state/other/x', R + '/scripts/a'):
    t(f'packages: refused {k}', not real._write_ok(k))
dry = P.Store('packages', {'P1'}, dry_run=True)
t('dry: refuses package scripts/', not dry._write_ok(R + 'P1/scripts/a.py'))
t('dry: allows publish log', dry._write_ok(L + 'test.dryrun.jsonl'))
fake = P.Store('fake', None, dry_run=False)
t('fake: allows any pid scripts/', fake._write_ok(S + 'fakepkg/ANY/scripts/a.py'))
t('fake: refuses fake manifest.jsonl', not fake._write_ok(S + 'fakepkg/ANY/manifest.jsonl'))
t('fake: refuses real package', not fake._write_ok(R + 'P1/scripts/a.py'))
t('fake: refuses bundles/', not fake._write_ok(S + 'bundles/test/x'))
try:
    real.put(R + 'P1/manifest.jsonl', b'x')
    t('put on a refused key raises before any S3 call', False)
except RuntimeError as e:
    t('put on a refused key raises before any S3 call', 'write guard' in str(e))
for k in (R + 'P1/scripts/a.py', L + 'test.jsonl', S + 'bundles/test/x'):
    try:
        real.delete(k)
        t(f'delete refused {k}', False)
    except RuntimeError:
        t(f'delete refused {k}', True)


# S3 user metadata <= 2 KB: a max-length ASCII row fits; a row whose source percent-encodes past the limit is refused at
# plan time (Refuse metadata_too_large) instead of failing in the middle of a package's uploads
hdr = {'model_id': 'm' * 128}
t('metadata: max-length ASCII row fits 2 KB',
  P.meta_bytes(P.object_meta(dict(sha256='a' * 64, source='x' * 512, code_version='y' * 128), hdr, 'r' * 64, 'b' * 64)) <= P.S3_META_LIMIT)
t('metadata: 512 reserved chars exceed 2 KB once encoded',
  P.meta_bytes(P.object_meta(dict(sha256='a' * 64, source='#' * 512, code_version='y' * 128), hdr, 'r' * 64, 'b' * 64)) > P.S3_META_LIMIT)
t('metadata: source round-trips through quote/unquote',
  P.urllib.parse.unquote(P.object_meta(dict(sha256='a', source='code z3-db1 #5: kit/x.py (100%)', code_version='v'), hdr, 'r', 'b')
                         ['pmp-source']) == 'code z3-db1 #5: kit/x.py (100%)')


# --expect: Modal index rows (bundle.sha256 / upload.bundle_sha256) and plain rows; failed models ignored; a file with no
# bundle sha at all, or two different shas for one model, is an error (never silently disables the check)
import json, tempfile  # noqa: E401,E402
def _exp(rows):
    f = tempfile.NamedTemporaryFile('w', suffix='.jsonl', delete=False)
    f.write(''.join(json.dumps(r) + '\n' for r in rows)); f.close()
    try:
        return P.load_expect(f.name)
    except SystemExit:
        return 'refused'
    finally:
        os.remove(f.name)
t('expect: Modal index rows', _exp([dict(model_id='a', bundle=dict(sha256='1' * 64), upload=dict(bundle_sha256='1' * 64)),
                                   dict(model_id='b', status='pipeline_failed'), dict(model_id='c', bundle_sha256='2' * 64)])
  == {'a': '1' * 64, 'c': '2' * 64})
t('expect: conflicting shas refused', _exp([dict(model_id='a', bundle=dict(sha256='1' * 64), upload=dict(bundle_sha256='3' * 64))]) == 'refused')
t('expect: file without any bundle sha refused', _exp([dict(model_id='b', status='error')]) == 'refused')


class A:
    run = 'test'; target = 'packages'; allow_pids = None; all_pids = False; dry_run = False; expect = None; workdir = None


try:
    P.Publisher(A())
    t('packages target without --allow-pids refused', False)
except SystemExit:
    t('packages target without --allow-pids refused', True)
os.environ['PMP_TEST_FAIL_AFTER'] = '1'
try:
    A.all_pids = True
    P.Publisher(A())
    t('test crash hook refused on the real target', False)
except SystemExit:
    t('test crash hook refused on the real target', True)
print(f'{len(fails)} failed' if fails else 'all passed')
sys.exit(1 if fails else 0)
