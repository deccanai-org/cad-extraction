"""Local unit tests of the bundle contract (stdlib only, tiny synthetic files): python3 publish/tests/test_bundle_lib.py"""
import gzip
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, HERE)
import bundle_lib as BL  # noqa: E402
import fixtures as FX  # noqa: E402

PID = 'Zentitude-data-4__TEKLA-HYD_PROJECT_DATA-2019-2020_MMW_2.P535_HANGAR.7z'
MID = '701f5f69cd9124a9b61555c2e8e728468d2d1adadaab3cea8eee0ff98822fbbb'
FAILS = []


def check(name, cond, extra=''):
    print(('ok   ' if cond else 'FAIL ') + name + (f'  [{extra}]' if extra and not cond else ''))
    if not cond:
        FAILS.append(name)


def expect_refusal(name, path, code, **kw):
    try:
        BL.verify_bundle(path, **kw)
        check(name, False, 'accepted')
    except BL.BundleError as e:
        check(name, e.code == code, f'got {e.code}: {e.message}')


def retar(src, dst, mutate):
    """rewrite a bundle's members through mutate(list of (TarInfo, bytes)) -> list"""
    with tarfile.open(src, 'r:gz') as tf:
        mem = [(m, tf.extractfile(m).read() if m.isreg() else b'') for m in tf.getmembers()]
    mem = mutate(mem)
    with open(dst, 'wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as gz, \
            tarfile.open(fileobj=gz, mode='w', format=tarfile.PAX_FORMAT) as tf:
        for m, data in mem:
            m.size = len(data) if m.isreg() else 0
            tf.addfile(m, io.BytesIO(data) if m.isreg() else None)


def upload_tests(bundle):
    """bundle_lib.upload_bundle against a local fake S3 endpoint (127.0.0.1, no network): success + ETag check, 403 not
    retried, transfer 400 (RequestTimeout) retried, a wrong ETag retried then refused, no signature in any message"""
    import hashlib
    import http.server
    import threading
    os.environ['NO_PROXY'] = os.environ['no_proxy'] = '127.0.0.1,localhost'
    md5 = hashlib.md5(open(bundle, 'rb').read()).hexdigest()
    plan = []
    seen = []

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_PUT(self):
            body = self.rfile.read(int(self.headers['Content-Length']))
            seen.append(len(body))
            act = plan.pop(0) if plan else 'ok'
            if act == 'ok' or act == 'badetag':
                self.send_response(200)
                self.send_header('ETag', '"%s"' % (hashlib.md5(body).hexdigest() if act == 'ok' else '0' * 32))
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            code, s3code = act
            msg = f'<?xml version="1.0"?><Error><Code>{s3code}</Code><Message>x</Message></Error>'.encode()
            self.send_response(code)
            self.send_header('Content-Length', str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)

    srv = http.server.HTTPServer(('127.0.0.1', 0), H)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    url = f'http://127.0.0.1:{srv.server_port}/b/k.tar.gz?X-Amz-Signature=SECRETSIG&X-Amz-Security-Token=SECRETTOKEN'
    try:
        r = BL.upload_bundle(bundle, url, retries=1)
        check('upload: 200 + ETag == MD5 of the body', r['status'] == 200 and r['etag'] == md5 and r['etag_is_md5'] and r['attempts'] == 1)
        plan[:] = [(403, 'AccessDenied')]
        n0 = len(seen)
        try:
            BL.upload_bundle(bundle, url, retries=1)
            check('upload: 403 refused', False, 'accepted')
        except RuntimeError as e:
            check('upload: 403 refused, not retried, no signature/token in the message',
                  len(seen) - n0 == 1 and 'HTTP 403 AccessDenied' in str(e) and 'SECRET' not in str(e), str(e))
        plan[:] = [(400, 'RequestTimeout')]
        r = BL.upload_bundle(bundle, url, retries=1)
        check('upload: 400 RequestTimeout retried, then ok', r['attempts'] == 2 and r['etag'] == md5)
        plan[:] = [(400, 'InvalidArgument')]
        try:
            BL.upload_bundle(bundle, url, retries=1)
            check('upload: other 400 refused', False, 'accepted')
        except RuntimeError as e:
            check('upload: other 400 refused without retry', 'InvalidArgument' in str(e) and 'SECRET' not in str(e), str(e))
        plan[:] = ['badetag', 'badetag']
        try:
            BL.upload_bundle(bundle, url, retries=1)
            check('upload: wrong ETag refused', False, 'accepted')
        except RuntimeError as e:
            check('upload: ETag != MD5 retried, then refused with a clear message',
                  'after 2 attempts' in str(e) and 'corrupted in transit' in str(e) and 'SECRET' not in str(e), str(e))
        plan[:] = ['badetag']
        r = BL.upload_bundle(bundle, url, retries=1)
        check('upload: ETag != MD5 once, retried, then ok', r['attempts'] == 2 and r['etag'] == md5)
        check('upload: every PUT carried the whole bundle', set(seen) == {os.path.getsize(bundle)}, str(set(seen)))
    finally:
        srv.shutdown()


def main():
    t = tempfile.mkdtemp(prefix='pmp_bl_test_')
    try:
        a, info = FX.make(os.path.join(t, 'a'), 'test', PID, MID, 'GRID3', 'model/step/GRID3.step')
        check('good bundle builds + verifies', info['n_files'] == 15 and not info['warnings'], str(info))
        b, info_b = FX.make(os.path.join(t, 'b'), 'test', PID, MID, 'GRID3', 'model/step/GRID3.step', work=os.path.join(t, 'wb'))
        check('deterministic: same inputs -> byte-identical bundle', info['sha256'] == info_b['sha256'])
        x = os.path.join(t, 'x')
        v = BL.verify_bundle(a, extract_to=x, expect=dict(run='test', model_id=MID, sha256=info['sha256']))
        check('extract: every file on disk with its row sha', all(os.path.exists(p) for p in v.files.values())
              and all(BL.sha256_file(v.files[r['path']]) == r['sha256'] for r in v.rows))
        expect_refusal('expected sha256 mismatch', a, 'sha_mismatch', expect=dict(sha256='0' * 64))
        expect_refusal('header model_id vs S3 key', a, 'bad_header', expect=dict(model_id='deadbeef'))

        def tamper(mem):
            out = []
            for m, d in mem:
                if m.name.endswith('build_model.py'):
                    d = d + b'# tampered\n'
                out.append((m, d))
            return out
        p = os.path.join(t, 'tamper.tar.gz')
        retar(a, p, tamper)
        expect_refusal('content changed after rows were written', p, 'sha_mismatch')

        def traversal(mem):
            m = tarfile.TarInfo('scripts/../../etc/evil')
            return mem + [(m, b'x')]
        retar(a, p, traversal)
        expect_refusal('path traversal member', p, 'bad_path')

        def absolute(mem):
            return mem + [(tarfile.TarInfo('/tmp/evil'), b'x')]
        retar(a, p, absolute)
        expect_refusal('absolute member', p, 'bad_path')

        def symlink(mem):
            m = tarfile.TarInfo('scripts/GRID3/link')
            m.type = tarfile.SYMTYPE
            m.linkname = '/etc/passwd'
            return mem + [(m, b'')]
        retar(a, p, symlink)
        expect_refusal('symlink member', p, 'bad_member')

        def extra_unlisted(mem):
            return mem + [(tarfile.TarInfo('scripts/GRID3/schedules/extra.csv'), b'a\n')]
        retar(a, p, extra_unlisted)
        expect_refusal('file without a row', p, 'bad_rows')

        def manifest_in_bundle(mem):
            return mem + [(tarfile.TarInfo('scripts/scripts_manifest.jsonl'), b'{}\n')]
        retar(a, p, manifest_in_bundle)
        expect_refusal('scripts_manifest.jsonl inside a bundle', p, 'bad_layout')

        def other_model(mem):
            return mem + [(tarfile.TarInfo('scripts/OTHER/build_model.py'), b'x\n')]
        retar(a, p, other_model)
        expect_refusal('second model folder in one bundle', p, 'bad_layout')

        def pyc(mem):
            return mem + [(tarfile.TarInfo('scripts/GRID3/__pycache__/x.pyc'), b'x')]
        retar(a, p, pyc)
        expect_refusal('junk __pycache__ file', p, 'junk_file')

        def dup(mem):
            return mem + [mem[-1]]
        retar(a, p, dup)
        expect_refusal('duplicate member', p, 'bad_member')

        with open(p, 'wb') as f:
            f.write(open(a, 'rb').read()[:300])
        expect_refusal('truncated archive', p, 'bad_archive')

        # layout: required file missing
        tree = FX.make_tree(os.path.join(t, 'lay', 'scripts'), 'GRID3', MID)
        os.remove(os.path.join(tree, 'GRID3', 'issues', 'WHERE_TO_LOOK.md'))
        hdr = dict(run='test', model_id=MID, pid=PID, model_folder='GRID3', step_relpath='model/step/GRID3.step', step_source='ifc',
                   code_version='t')
        try:
            BL.make_bundle(tree, os.path.join(t, 'lay.tar.gz'), hdr, lambda r: 'test')
            check('missing WHERE_TO_LOOK.md refused', False, 'accepted')
        except BL.BundleError as e:
            check('missing WHERE_TO_LOOK.md refused', e.code == 'missing_file', e.code)
        # missing parts listed but no MISSING step
        tree = FX.make_tree(os.path.join(t, 'lay2', 'scripts'), 'GRID3', MID, n_missing=0)
        with open(os.path.join(tree, 'GRID3', 'schedules', 'missing_parts.json'), 'w') as f:
            json.dump({'parts': [{'id': 1}]}, f)
        try:
            BL.make_bundle(tree, os.path.join(t, 'lay2.tar.gz'), hdr, lambda r: 'test')
            check('missing parts without MISSING step refused', False, 'accepted')
        except BL.BundleError as e:
            check('missing parts without MISSING step refused', e.code == 'missing_file', e.code)
        tree = FX.make_tree(os.path.join(t, 'lay4', 'scripts'), 'GRID3', MID)
        with open(os.path.join(tree, 'GRID3', 'model_info.json'), 'w') as f:
            f.write('{not json')
        try:
            BL.make_bundle(tree, os.path.join(t, 'lay4.tar.gz'), hdr, lambda r: 'test')
            check('unparseable model_info.json refused', False, 'accepted')
        except BL.BundleError as e:
            check('unparseable model_info.json refused', e.code == 'bad_json', e.code)
        # db1 model must ship its IFC
        tree = FX.make_tree(os.path.join(t, 'lay3', 'scripts'), 'M', MID, step_source='ifc')
        try:
            BL.make_bundle(tree, os.path.join(t, 'lay3.tar.gz'), dict(hdr, model_folder='M', step_source='db1'), lambda r: 'test')
            check('db1 model without source IFC refused', False, 'accepted')
        except BL.BundleError as e:
            check('db1 model without source IFC refused', e.code == 'missing_file', e.code)
        # folder names with spaces (real packages have them) are fine; a slash is not
        _, inf = FX.make(os.path.join(t, 'sp'), 'test', PID, MID, '19058 GIORGI USA', 'model/step/x.step')
        check('model folder with spaces accepted', inf['n_files'] == 15)
        try:
            FX.make(os.path.join(t, 'sl'), 'test', PID, MID, 'a/b', 'model/step/x.step')
            check('model folder with a slash refused', False, 'accepted')
        except BL.BundleError as e:
            check('model folder with a slash refused', e.code == 'bad_path', e.code)
        check('redact_url hides the query', BL.redact_url('https://h/k?X-Amz-Signature=abc&X-Amz-Security-Token=t') ==
              'https://h/k?<signature redacted>')
        upload_tests(a)
    finally:
        shutil.rmtree(t, ignore_errors=True)
    print(f'{len(FAILS)} failed' if FAILS else 'all passed')
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
