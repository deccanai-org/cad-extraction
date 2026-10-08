"""source stage: a faithful source IFC for the model.

  package_ifc            the package's own IFC (converted_from): downloaded and sha256-checked inside the pipeline
                         stage (no container of its own); /<id>/source/provenance.json says where it is
  regenerated_from_db1   IFC regenerated from the DB1 with the kit that produced the shipped STEP, GlobalIds restored,
                         reproduction proven (src_db1 plug-in, in its own image)
  emitted_from_sds2      IFC emitted from the SDS/2 job with the pinned converter (src_sds2 plug-in, its own image)

plan() decides where the source comes from; run_plugin() runs src_db1 / src_sds2 and publishes their output to
/<id>/source/ (only when the plug-in reports ok and its IFC exists with the sha256 it reported).
"""
import os, shutil, time, traceback

from . import common as C
from . import plugins

PLUGIN_BY_KIND = {'regenerated_from_db1': 'src_db1', 'emitted_from_sds2': 'src_sds2'}


def plan(job):
    kind = job['source_kind']
    if kind == 'package_ifc':
        return {'where': 'inline', 'mode': 'package', 'url_key': 'ifc'}
    return {'where': 'plugin', 'plugin': PLUGIN_BY_KIND[kind]}


def make_fetch(job, log):
    def fetch(url_key, dest, sha256=None, nbytes=None):
        url = (job.get('urls') or {}).get(url_key)
        if not url:
            raise C.DownloadError(f'job has no urls.{url_key}')
        return C.download(url, dest, sha256=sha256, nbytes=nbytes, log=log)
    return fetch


def run_plugin(name, job, cls, deadline, workroot='/tmp/pmp'):
    """run the src_db1 / src_sds2 plug-in for one model; publish its out/ to /<id>/source/ on success.
    Returns {'ok', 'ifc', 'ifc_path' (volume path), 'sha256', 'provenance', 'verdict', 'error', 'seconds', ...}"""
    t0 = time.time()
    cpu = C.CpuMeter()
    ID, STEM = job['id'], job['id'][:16]
    JD = os.path.join(workroot, STEM + '.' + name)
    shutil.rmtree(JD, ignore_errors=True)
    work, out = os.path.join(JD, 'work'), os.path.join(JD, 'out')
    os.makedirs(work)
    os.makedirs(out)
    log = C.StageLog(os.path.join(JD, 'log', name + '.log'), prefix=f'[{STEM} {name}] ')
    mem = C.MemSampler()
    MD = os.path.join(C.VOL, ID)
    ctx = dict(stage=name, work=work, out=out, model_dir=MD, cls=cls, J=C.RES[cls]['J'], deadline=deadline, log=log,
               fetch=make_fetch(job, log), code_dir=os.path.join(C.CODE_ROOT, job['code_version']))
    rec = {'ok': False, 'stage': name, 'cls': cls, 'error': None}
    log(f'start {name} {ID} cls {cls}')
    try:
        mod = plugins.load(name)
        r = mod.run(job, ctx) or {}
        if not isinstance(r, dict):
            raise TypeError(f'{name}.run returned {type(r).__name__}, expected dict')
        rec.update({k: v for k, v in r.items() if k not in ('ok', 'error')})
        rec['error'] = r.get('error')
        if r.get('ok'):
            ifc = r.get('ifc')
            p = os.path.join(out, ifc or '')
            if not ifc or not os.path.isfile(p):
                raise RuntimeError(f'{name} reported ok but its IFC {ifc!r} is not in out/')
            got = C.file_sha256(p)
            if r.get('sha256') and r['sha256'] != got:
                raise RuntimeError(f'{name} IFC sha256 {got} != reported {r["sha256"]}')
            if not os.path.isfile(os.path.join(out, 'provenance.json')):
                raise RuntimeError(f'{name} reported ok but wrote no provenance.json')
            rec.update(ok=True, sha256=got, ifc=ifc, ifc_path=os.path.join(MD, 'source', ifc), bytes=os.path.getsize(p))
    except Exception as e:
        rec['ok'] = False
        rec['error'] = f'{type(e).__name__}: {e}'
        log('EXCEPTION ' + traceback.format_exc())
    rec['seconds'] = round(time.time() - t0, 1)
    rec['cpu_seconds'] = cpu.done()
    rec['peak_gib'], rec['peak_how'] = mem.done()
    rec['container'] = C.container_info(cls)
    log(f'done ok={rec["ok"]} error={rec["error"]} {rec["seconds"]}s')
    os.makedirs(os.path.join(MD, 'logs'), exist_ok=True)
    if rec['ok']:
        C.publish(out, os.path.join(MD, 'source'))
    else:
        shutil.rmtree(os.path.join(MD, 'source'), ignore_errors=True)   # never leave an older source looking current
        if os.listdir(out):
            C.publish(out, os.path.join(MD, 'logs', name + '_failed_out'))
    shutil.copy(log.path, os.path.join(MD, 'logs', name + '.log'))
    shutil.rmtree(JD, ignore_errors=True)
    return rec


def plugin_missing(name, job, cls, why):
    """the record of a source stage that cannot run in this deployment (no plug-in image / code)"""
    return {'ok': False, 'stage': name, 'cls': cls, 'error': f'plugin_image_missing: {why}', 'seconds': 0}
