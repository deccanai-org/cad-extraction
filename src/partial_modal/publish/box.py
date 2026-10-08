#!/usr/bin/env python3
"""box.py - Mac-side driver for the publishing tools on the EC2 box i-0f35da72bf742063d (Mumbai), over SSM only.

The Mac's own AWS identities never write bim-proprietary-data: every write happens ON the box with its instance role.
Code goes to the box inside SSM commands (chunked base64, sha256-checked), not through S3.

    box.py deploy                                     copy bundle_lib.py presign_put.py publisher.py -> /opt/bench/pmp_publish/
    box.py presign --run R (--model-id ID ... | --ids-file F) [--out FILE] [--min-valid-minutes 60]
                                                      sign PUT URLs on the box -> s3 _state/pmp/presign/<run>.json, then read it
                                                      back with AWS_PROFILE=bim into FILE (default publish/presigned/<run>.json,
                                                      mode 0600). Prints counts + expiry only, never a URL.
    box.py publish --run R --target fake|packages [--allow-pids F] [--dry-run] [publisher options...] [--detach]
                                                      run publisher.py on the box; prints its JSON summary; copies the publish
                                                      log to publish/logs/ (AWS_PROFILE=bim)
    box.py fakepkg --pid PID                          test target: copy the REAL package's manifest.jsonl + project.json (read)
                                                      into _state/pmp/fakepkg/<pid>/ (the only write)
    box.py status                                     tail of detached publisher runs
    box.py clean-test                                 delete the publisher TEST state (only under _state/pmp/: bundles/test/,
                                                      presign/test.json, fakepkg/, publish/test{,.dryrun}.jsonl,
                                                      publish/{state,locks}/fake/, publish/dryrun/test/)

Environment: PMP_BOX (instance id), PMP_BOX_REGION (ap-south-1), PMP_SSM_PROFILE (annotationprod-publish, used for SSM only),
PMP_READ_PROFILE (bim, read-only S3 reads on the Mac).
"""
import argparse
import base64
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BOX = os.environ.get('PMP_BOX', 'i-0f35da72bf742063d')
REGION = os.environ.get('PMP_BOX_REGION', 'ap-south-1')
SSM_PROFILE = os.environ.get('PMP_SSM_PROFILE', 'annotationprod-publish')
READ_PROFILE = os.environ.get('PMP_READ_PROFILE', 'bim')
REMOTE = '/opt/bench/pmp_publish'
PY = '/opt/pm/venv/bin/python'
BUCKET = 'bim-proprietary-data'
STATE = 'cad-disk-extract/_state/pmp/'
CODE = ('bundle_lib.py', 'presign_put.py', 'publisher.py')
TESTS = ('tests/test_guards.py',)
CHUNK = 30000                     # base64 characters per SSM command
RUN_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')


def aws(args, profile, check=True, capture=True):
    env = dict(os.environ, AWS_PROFILE=profile)
    r = subprocess.run(['aws'] + args, env=env, capture_output=capture, text=True)
    if check and r.returncode != 0:
        raise SystemExit(f'aws {args[0]} {args[1] if len(args) > 1 else ""} failed: {r.stderr.strip()[-400:]}')
    return r


def ssm(script, timeout=300, quiet=False):
    """run a bash script on the box (AWS-RunShellScript); returns (ok, stdout, stderr)"""
    b64 = base64.b64encode(script.encode()).decode()
    cmd = f'echo {b64} | base64 -d > /tmp/pmp_ssm_$$.sh && bash /tmp/pmp_ssm_$$.sh; rc=$?; rm -f /tmp/pmp_ssm_$$.sh; exit $rc'
    params = json.dumps({'commands': [cmd], 'executionTimeout': [str(timeout)]})
    r = aws(['ssm', 'send-command', '--region', REGION, '--instance-ids', BOX, '--document-name', 'AWS-RunShellScript',
             '--parameters', params, '--timeout-seconds', '60', '--query', 'Command.CommandId', '--output', 'text'], SSM_PROFILE)
    cid = r.stdout.strip()
    end = time.time() + timeout + 60
    st = 'Pending'
    while time.time() < end:
        time.sleep(2)
        q = aws(['ssm', 'get-command-invocation', '--region', REGION, '--command-id', cid, '--instance-id', BOX, '--output', 'json'],
                SSM_PROFILE, check=False)
        if q.returncode != 0:
            continue
        d = json.loads(q.stdout)
        st = d.get('Status')
        if st in ('Success', 'Failed', 'Cancelled', 'TimedOut', 'Undeliverable', 'Terminated'):
            out, err = d.get('StandardOutputContent', ''), d.get('StandardErrorContent', '')
            if not quiet:
                print(out, end='' if out.endswith('\n') else '\n')
                if err.strip():
                    print(err, file=sys.stderr)
            return st == 'Success', out, err
    raise SystemExit(f'SSM command {cid} did not finish in time (last status {st})')


def put_file_script(remote_path, data):
    """bash snippets that write data to remote_path in chunks (one SSM call per chunk)"""
    b64 = base64.b64encode(data).decode()
    parts = [b64[i:i + CHUNK] for i in range(0, len(b64), CHUNK)] or ['']
    tmp = remote_path + '.b64part'
    scripts = []
    for i, p in enumerate(parts):
        op = '>' if i == 0 else '>>'
        scripts.append(f'mkdir -p {shlex.quote(os.path.dirname(remote_path))} && printf %s {shlex.quote(p)} {op} {shlex.quote(tmp)}')
    return scripts, tmp


def push(remote_path, data, mode='644'):
    scripts, tmp = put_file_script(remote_path, data)
    for s in scripts:
        ok, out, err = ssm(s, 120, quiet=True)
        if not ok:
            raise SystemExit(f'push {remote_path}: chunk failed: {err[-300:]}')
    want = hashlib.sha256(data).hexdigest()
    fin = (f'base64 -d {shlex.quote(tmp)} > {shlex.quote(remote_path)}.new && rm -f {shlex.quote(tmp)} && '
           f'got=$(sha256sum {shlex.quote(remote_path)}.new | cut -d" " -f1) && '
           f'if [ "$got" = "{want}" ]; then chmod {mode} {shlex.quote(remote_path)}.new && mv -f {shlex.quote(remote_path)}.new '
           f'{shlex.quote(remote_path)} && echo OK; else echo "SHA MISMATCH $got"; exit 1; fi')
    ok, out, err = ssm(fin, 120, quiet=True)
    if not ok or 'OK' not in out:
        raise SystemExit(f'push {remote_path}: verification failed: {out[-200:]} {err[-200:]}')
    return want


def cmd_deploy(a):
    for f in CODE + (TESTS if a.with_tests else ()):
        data = open(os.path.join(HERE, f), 'rb').read()
        h = push(f'{REMOTE}/{f}', data)
        print(f'deployed {f} {len(data)} B sha256 {h[:16]}')
    ok, out, err = ssm(f'cd {REMOTE} && {PY} -c "import bundle_lib, boto3; print(\'import ok\', bundle_lib.FORMAT, boto3.__version__)" && '
                       f'{PY} -m py_compile presign_put.py publisher.py && echo compiled && sha256sum {" ".join(CODE)}', 120)
    if ok and a.with_tests:
        ok, out, err = ssm(f'cd {REMOTE} && {PY} tests/test_guards.py | grep -v "^ok"', 120)
    return 0 if ok else 1


def cmd_presign(a):
    if not RUN_RE.match(a.run):
        raise SystemExit(f'bad run {a.run!r}')
    ids = list(a.model_id)
    if a.ids_file:
        raw = open(a.ids_file, encoding='utf-8').read().strip()
        if raw.startswith('['):
            ids += [x['model_id'] if isinstance(x, dict) else x for x in json.loads(raw)]
        else:
            ids += [json.loads(x)['model_id'] if x.strip().startswith('{') else x.strip() for x in raw.splitlines() if x.strip()]
    if not ids:
        raise SystemExit('no model ids')
    data = ('\n'.join(ids) + '\n').encode()
    rpath = f'{REMOTE}/inputs/presign_{a.run}_{hashlib.sha256(data).hexdigest()[:12]}.ids'
    push(rpath, data)
    ok, out, err = ssm(f'cd {REMOTE} && {PY} presign_put.py --run {shlex.quote(a.run)} --ids-file {shlex.quote(rpath)} '
                       f'--min-valid-minutes {a.min_valid_minutes}', 300)
    if not ok:
        return 1
    out_path = a.out or os.path.join(HERE, 'presigned', f'{a.run}.json')
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    tmp = out_path + '.tmp'
    aws(['s3', 'cp', '--only-show-errors', f's3://{BUCKET}/{STATE}presign/{a.run}.json', tmp], READ_PROFILE)
    os.chmod(tmp, 0o600)
    os.replace(tmp, out_path)
    d = json.load(open(out_path))
    miss = sorted(set(ids) - set(d['urls']))
    print(f'presign file -> {out_path} (0600): {d["n"]} URLs, expires {d["expires_utc"]} (credential expiry '
          f'{d["credential_expiration_utc"]}){"; MISSING " + str(miss) if miss else ""}')
    return 0 if not miss else 1


def cmd_publish(a, extra):
    if not RUN_RE.match(a.run):
        raise SystemExit(f'bad run {a.run!r}')
    args = ['--run', a.run, '--target', a.target]
    if a.allow_pids:
        data = open(a.allow_pids, 'rb').read()
        rpath = f'{REMOTE}/inputs/allow_{hashlib.sha256(data).hexdigest()[:12]}.json'
        push(rpath, data)
        args += ['--allow-pids', rpath]
    if a.expect:
        data = open(a.expect, 'rb').read()
        rpath = f'{REMOTE}/inputs/expect_{a.run}_{hashlib.sha256(data).hexdigest()[:12]}.jsonl'
        push(rpath, data)
        args += ['--expect', rpath]
    if a.dry_run:
        args.append('--dry-run')
    args += extra
    env = ''
    if a.test_fail_after:
        if a.target != 'fake':
            raise SystemExit('--test-fail-after is for --target fake only')
        env = f'PMP_TEST_FAIL_AFTER={int(a.test_fail_after)} '
    line = f'cd {REMOTE} && {env}{PY} publisher.py ' + ' '.join(shlex.quote(x) for x in args)
    if a.detach:
        tag = f'{a.run}.{int(time.time())}'
        ok, out, err = ssm(f'mkdir -p {REMOTE}/runs && cd {REMOTE} && (setsid nohup bash -c {shlex.quote(line + f" > runs/{tag}.out 2>&1; echo $? > runs/{tag}.rc")} '
                           f'> /dev/null 2>&1 < /dev/null &) ; sleep 1; echo started {tag}', 60)
        return 0 if ok else 1
    ok, out, err = ssm(line + '; echo "[publisher exit $?]"', a.timeout)
    m = re.search(r'\[publisher exit (\d+)\]', out)
    rc = int(m.group(1)) if m else 1
    os.makedirs(os.path.join(HERE, 'logs'), exist_ok=True)
    name = f'{a.run}{".dryrun" if a.dry_run else ""}.jsonl'
    r = aws(['s3', 'cp', '--only-show-errors', f's3://{BUCKET}/{STATE}publish/{name}', os.path.join(HERE, 'logs', name)], READ_PROFILE,
            check=False)
    if r.returncode == 0:
        print(f'publish log -> {os.path.join(HERE, "logs", name)}')
    return rc


def cmd_fakepkg(a):
    pid = a.pid
    if '/' in pid or not pid.strip():
        raise SystemExit('bad pid')
    src = f's3://{BUCKET}/cad-disk-extract/dataset/packages/3d_partial/{pid}/'
    dst = f's3://{BUCKET}/{STATE}fakepkg/{pid}/'
    s = (f'set -e\nSRC={shlex.quote(src)}\nDST={shlex.quote(dst)}\n'
         'case "$DST" in s3://bim-proprietary-data/cad-disk-extract/_state/pmp/fakepkg/*) ;; *) echo "refusing $DST"; exit 1;; esac\n'
         'for f in manifest.jsonl project.json; do aws s3 cp --only-show-errors "$SRC$f" "$DST$f"; done\n'
         'aws s3 ls --recursive "$DST"\n')
    ok, out, err = ssm(s, 120)
    return 0 if ok else 1


def cmd_status(a):
    ok, out, err = ssm(f'cd {REMOTE}/runs 2>/dev/null && for f in $(ls -t *.out | head -5); do echo "== $f rc=$(cat ${{f%.out}}.rc 2>/dev/null || echo running)"; '
                       f'tail -c 1500 $f; done', 60)
    return 0 if ok else 1


def cmd_clean_test(a):
    """delete ONLY the publisher's test state (run name "test", fake target) - all under _state/pmp/"""
    pre = f's3://{BUCKET}/{STATE}'
    prefixes = ['bundles/test/', 'fakepkg/', 'publish/state/fake/', 'publish/locks/fake/', 'publish/dryrun/test/']
    objects = ['presign/test.json', 'publish/test.jsonl', 'publish/test.dryrun.jsonl']
    lines = ['set -e']
    for t in prefixes:
        assert t.endswith('/') and (pre + t).startswith(f's3://{BUCKET}/{STATE}')
        lines.append(f'aws s3 rm --only-show-errors --recursive {shlex.quote(pre + t)}')
    for o in objects:
        lines.append(f'aws s3 rm --only-show-errors {shlex.quote(pre + o)} || true')
    lines.append(f'echo "left under _state/pmp/: $(aws s3 ls --recursive {shlex.quote(pre)} | wc -l) objects"')
    ok, out, err = ssm('\n'.join(lines), 300)
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('deploy')
    p.add_argument('--with-tests', action='store_true', help='also copy tests/test_guards.py and run it on the box')
    p = sub.add_parser('presign')
    p.add_argument('--run', required=True)
    p.add_argument('--model-id', action='append', default=[])
    p.add_argument('--ids-file')
    p.add_argument('--out')
    p.add_argument('--min-valid-minutes', type=float, default=60)
    p = sub.add_parser('publish')
    p.add_argument('--run', required=True)
    p.add_argument('--target', choices=('fake', 'packages'), required=True)
    p.add_argument('--allow-pids')
    p.add_argument('--expect')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--detach', action='store_true')
    p.add_argument('--timeout', type=int, default=1800)
    p.add_argument('--test-fail-after', type=int, default=0)
    p = sub.add_parser('fakepkg')
    p.add_argument('--pid', required=True)
    sub.add_parser('status')
    sub.add_parser('clean-test')
    a, extra = ap.parse_known_args()
    if extra and a.cmd != 'publish':
        ap.error(f'unrecognized arguments: {extra}')
    if a.cmd == 'publish':
        return cmd_publish(a, extra)
    return dict(deploy=cmd_deploy, presign=cmd_presign, fakepkg=cmd_fakepkg, status=cmd_status)[a.cmd](a) if a.cmd != 'clean-test' \
        else cmd_clean_test(a)


if __name__ == '__main__':
    sys.exit(main())
