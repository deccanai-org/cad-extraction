#!/usr/bin/env python3
"""'package' vpipe for the z3conv fleet runtime (convfleet).  One job = one project (create or update).

Job list  (written by the coordinator hook coord_hook.round()) PKG_JOBS_KEY, default
          bim cad-disk-extract/zenitude-data-3/_state/conv/package/jobs.json
          {id: pkg-<sha1(project)[:16]>-<sig>, vpipe: package, adapter, project_id, archive, kind create|update, add, refresh,
           index_key (immutable index snapshot), policy, size}
Result    _state/conv/package/results/<id>.json  (convfleet) + bim cad-disk-extract/_state/packaging/{done,ledger_parts,verify_fail}/
Kit files (flat): worker.py convfleet.py pkg.py pkgcore.py adapter_zen3.py
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import convfleet as cf
os.environ['PKG_ALLOW_WRITE'] = '1'          # fleet instance role writes bim; the operator Mac never sets this
import pkg, pkgcore as pc

CODE = 'z3-package-' + pc.VERSION
FILES = ('worker.py', 'convfleet.py', 'pkg.py', 'pkgcore.py', 'adapter_zen3.py')


def need_bytes(job):
    # manifests up to ~1 GB gz (largest data-3 archive) are parsed in memory; SDS2 zips stream to disk
    return int(min(64 << 30, (4 << 30) + (job.get('size') or 0) // 8))


def need_disk(job):
    return int(min(800 << 30, (8 << 30) + (job.get('size') or 0)))       # SDS2 job zips are built on local disk


def process(fl, job, d):
    r = pkg.package_job(job, workdir=d)
    if r.get('status') == 'retry':
        return dict(r, status='fail', transient=True, retry_limit=50)
    r.pop('verify', None) if r.get('status') == 'ok' else None
    return r


if __name__ == '__main__':
    fl = cf.Fleet('package', CODE, process, need_bytes, FILES, need_disk=need_disk)
    sys.exit(fl.main())
