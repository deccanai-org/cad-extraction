#!/usr/bin/env python3
"""offline checks of the convfleet disk-lane changes (no AWS): paths, guards, registry wait signal, release block"""
import os, sys, json, time, importlib, tempfile, datetime
sys.path.insert(0, '/Users/dhiren/Downloads/Deccan/z3conv/common')
ok = True


def check(n, v):
    global ok
    print(('PASS ' if v else 'FAIL ') + n); ok &= bool(v)


def load(disk):
    os.environ.pop('CONV_DISK', None)
    if disk:
        os.environ['CONV_DISK'] = disk
    if 'convfleet' in sys.modules:
        del sys.modules['convfleet']
    import convfleet
    return convfleet


cf3 = load('')
check('data-3 paths unchanged', cf3.ROOT == 'cad-disk-extract/zenitude-data-3' and cf3.SROOT == 'cad-disk-extract/zenitude-data-3/_state/conv')
cf4 = load('zentitude-data-4')
check('disk lane paths', cf4.ROOT == 'cad-disk-extract/zentitude-data-4' and cf4.SROOT == 'cad-disk-extract/zentitude-data-4/_state/conv2')
try:
    load('nope'); check('unknown disk refused', False)
except SystemExit:
    check('unknown disk refused', True)
cf4 = load('zentitude-data-4')


class FakeS3:
    def __init__(self, objs): self.objs = objs
    def head_object(self, Bucket, Key):
        if Key not in self.objs:
            raise cf4.ClientError({'Error': {'Code': '404'}}, 'HeadObject')
        return {'LastModified': self.objs[Key], 'ETag': '"x"'}
    def put_object(self, **kw): self.objs[kw['Key']] = datetime.datetime.now(datetime.timezone.utc)
    def upload_file(self, path, b, k, ExtraArgs=None): self.objs[k] = datetime.datetime.now(datetime.timezone.utc)


old = datetime.datetime(2026, 9, 30, tzinfo=datetime.timezone.utc)
fs = FakeS3({'cad-disk-extract/zentitude-data-4/conversions/ifc-step/abc.step': old,
             'cad-disk-extract/zentitude-data-4/conversions/ifc-step/new.v6110.step': datetime.datetime(2026, 10, 3, 6, tzinfo=datetime.timezone.utc)})
cf4.s3 = fs
fl = cf4.Fleet.__new__(cf4.Fleet)
try:
    fl.upload('/dev/null', 'cad-disk-extract/zentitude-data-4/conversions/ifc-step/abc.step'); check('old object not overwritten', False)
except RuntimeError:
    check('old object not overwritten', True)
fl.upload('/dev/null', 'cad-disk-extract/zentitude-data-4/conversions/ifc-step/new.v6110.step'); check('own lane object may be rewritten', True)
fl.upload('/dev/null', 'cad-disk-extract/zentitude-data-4/conversions/ifc-step/fresh.v6110.step'); check('new object written', True)
for bad in ('cad-disk-extract/zenitude-data-3/_state/conv/ifc/results/x.json', 'cad-disk-extract/zentitude-data-4/_state/conv/ifc/results/x.json',
            'cad-disk-extract/zentitude-data-4/extracted/x'):
    try:
        fl.put(bad, {}); check(f'refused {bad[17:60]}', False)
    except AssertionError:
        check(f'refused {bad[17:60]}', True)
fl.put('cad-disk-extract/zentitude-data-4/_state/conv2/ifc/results/x.json', {}); check('conv2 state write allowed', True)

# registry wait signal: a data-3 process waiting -> H['d3_wait'] for a disk process; a disk process waiting is ignored
rd = tempfile.mkdtemp()
me = os.getpid()
reg3 = {'pid': os.getppid(), 'pipe': 'ifc', 'at': time.time(), 'jobs': [{'id': 'a', 'size': 200 << 20, 'exp': 1, 'rss': 1, 't0': time.time()}],
        'disk': '', 'd3_wait': time.time()}
json.dump(reg3, open(os.path.join(rd, f'reg-{os.getppid()}.json'), 'w'))
fl.rundir = rd; fl.running = {}; fl.lock = __import__('threading').Lock(); fl.others = {}; fl.total = 64 << 30
fl.pipe = 'ifc'; fl.job_cores = 3.0; fl.mem_tabs = {}; fl.ctl_env = lambda: {}
fl._mem_tab = lambda pipe=None: {}
H = fl._host()
check('disk lane sees data-3 wait', H['d3_wait'] > 0)
check('data-3 waiting need reserved (default 16 GB / 2 cores)', H['d3_exp'] == 16 << 30 and H['d3_cores'] == 2.0)
check('registry job tagged with disk ""', H['jobs'][0]['disk'] == '')
reg3['disk'] = 'zentitude-data-4'
json.dump(reg3, open(os.path.join(rd, f'reg-{os.getppid()}.json'), 'w'))
check('a disk-lane registry wait is ignored', fl._host()['d3_wait'] == 0)
reg3['disk'] = ''; reg3['d3_wait'] = time.time() - 600
json.dump(reg3, open(os.path.join(rd, f'reg-{os.getppid()}.json'), 'w'))
check('stale data-3 wait ignored', fl._host()['d3_wait'] == 0)
check('disk lane never releases', fl._release_now() is False)
print('ALL PASS' if ok else 'SOME FAILED')
# singleton: a disk-lane process does not wait for the data-3 process of the same pipeline/code (legacy or new file names)
rd2 = tempfile.mkdtemp()
for name in (f'db1-{os.getppid()}.json', f'db1~{os.getppid()}.json'):
    json.dump({'pid': os.getppid(), 'code': 'z3-db1-x'}, open(os.path.join(rd2, name), 'w'))
fl.rundir = rd2; fl.pipe = 'db1'; fl.code = 'z3-db1-x'
t0 = time.time(); r_ = fl._singleton()
check('disk lane singleton does not wait for data-3', r_ is True and time.time() - t0 < 5 and os.path.exists(os.path.join(rd2, f'db1@zentitude-data-4~{os.getpid()}.json')))
print('ALL PASS' if ok else 'SOME FAILED')
