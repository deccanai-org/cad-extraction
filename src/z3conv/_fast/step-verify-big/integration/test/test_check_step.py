#!/usr/bin/env python3
"""offline test of the patched grade/worker.py check_step (box): (1) STEP >= RB_MAX -> streamed read-back instead of the text-only
pass; (2) step_check memory-killed twice (simulated rc -9) -> streamed fallback; (3) normal path unchanged. Checks the signals
step_checks() reads (read_status, solids, invalid, nonpos_vol, ...) and that no 'skipped' is set."""
import os, sys, json, subprocess, shutil, tempfile
T = os.path.dirname(os.path.abspath(__file__))
KIT = sys.argv[1]; STEP = sys.argv[2]
os.environ['STUB_S3_DIR'] = os.path.dirname(os.path.abspath(STEP))
os.environ['CONV_HOME'] = '/opt/conv'
sys.path.insert(0, KIT)
import worker as W                                         # noqa: E402


class FL:
    def __init__(self, kill_check=0):
        self.kill_check = kill_check; self.calls = []

    def run(self, jid, cmd, logf, timeout, **kw):
        tool = os.path.basename(cmd[1]); self.calls.append(tool)
        if tool == 'step_check.py' and self.kill_check > 0:
            self.kill_check -= 1; return -9
        with open(logf, 'a') as lf:
            return subprocess.call(cmd, stdout=lf, stderr=subprocess.STDOUT, timeout=timeout)


res = {}
for case, rbmax, kills in (('big_file', 10 << 20, 0), ('oom_twice', 1 << 40, 2), ('normal', 1 << 40, 0)):
    W.RB_MAX = rbmax
    d = tempfile.mkdtemp(prefix=f'tcs_{case}_', dir=os.getcwd())
    fl = FL(kills)
    v, parts, png = W.check_step(fl, 'test', 'x/' + os.path.basename(STEP), d, 'test')
    res[case] = {'calls': fl.calls, 'skipped': v.get('skipped'), 'read_status': v.get('read_status'),
                 'solids': v.get('solids'), 'invalid': v.get('invalid'), 'nonpos_vol': v.get('nonpos_vol'), 'transferred': v.get('transferred'),
                 'streamed': bool(v.get('streamed')), 'version': (v.get('streamed') or {}).get('version'), 'parts': bool(parts),
                 'step_bytes': v.get('step_bytes')}
    shutil.rmtree(d, ignore_errors=True)
print(json.dumps(res, indent=1))
ok = (res['big_file']['streamed'] and res['big_file']['read_status'] == 'ok' and not res['big_file'].get('skipped')
      and res['oom_twice']['streamed'] and res['oom_twice']['calls'] == ['step_check.py', 'step_check.py', 'step_verify_big.py']
      and not res['normal']['streamed'] and res['normal']['calls'] == ['step_check.py']
      and res['big_file']['solids'] == res['normal']['solids'] == res['oom_twice']['solids']
      and res['big_file']['invalid'] == res['normal']['invalid'] and res['big_file']['nonpos_vol'] == res['normal']['nonpos_vol'])
print('PASS' if ok else 'FAIL')
