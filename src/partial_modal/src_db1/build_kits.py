#!/usr/bin/env python3
"""build_kits.py - assemble the two DB1 decoder kits the Modal image carries (kits/kit_u, kits/kit_v) and prove them.

Sources (read-only, never edited):
  kit_v = /Users/dhiren/Downloads/Deccan/z3conv/db1/                       (the live kit = S3 version history as of 2026-10-06T00:00Z)
  kit_u = the same folder with the five code-u files from z3conv/_sprint/db1-code-v/u/ laid over it
          (db1bolts.py, db1bolts2.py, db1old.py, db1step.py, worker.py; worker.py is not copied - fleet only)
Every copied file must have the md5 the S3 version-history manifest records for that kit (kit_manifests/kitsnap_v_1006 /
kitsnap_u_1005). Only the files the decode + STEP stage executes or reads are copied (no fleet / grader / credential-bearing
files). Each kit dir gets KIT.json {code, manifest, files{name: md5}}. A secret scan runs over everything copied.
Exit 1 on any mismatch. Local file copying only (no compute)."""
import hashlib, json, os, re, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = '/Users/dhiren/Downloads/Deccan/z3conv/db1'
U_OVER = '/Users/dhiren/Downloads/Deccan/z3conv/_sprint/db1-code-v/u'
NEEDED = ['attrlink.py', 'bolt_catalog.json', 'convert_one.py', 'db1bolts.py', 'db1bolts2.py', 'db1dec.py', 'db1old.py',
          'db1prof.py', 'db1step.py', 'fittings.py', 'ifc2step6.py', 'layouts.json', 'tekla_bolt_assemblies.json',
          'tekla_profiles.json', 'tekla_profiles_overlay.json']
KITS = {
    'kit_v': dict(code='z3-db1-2026-10-01v', manifest='kitsnap_v_1006.manifest.json', overlay=None),
    'kit_u': dict(code='z3-db1-2026-10-01u', manifest='kitsnap_u_1005.manifest.json', overlay=U_OVER),
}
SECRET = re.compile(rb'(AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|aws_secret_access_key|secret_access_key\s*[=:]|-----BEGIN [A-Z ]*PRIVATE KEY'
                    rb'|xox[baprs]-[0-9A-Za-z-]{10,}|ghp_[0-9A-Za-z]{30,})', re.I)


def md5(p):
    return hashlib.md5(open(p, 'rb').read()).hexdigest()


def main():
    bad = []
    for kit, spec in KITS.items():
        man = json.load(open(os.path.join(HERE, 'kit_manifests', spec['manifest'])))
        dst = os.path.join(HERE, 'kits', kit)
        shutil.rmtree(dst, ignore_errors=True)
        os.makedirs(dst)
        files = {}
        for fn in NEEDED:
            src = os.path.join(spec['overlay'], fn) if spec['overlay'] and os.path.exists(os.path.join(spec['overlay'], fn)) \
                else os.path.join(SRC, fn)
            want = (man['files'].get(fn) or {}).get('md5')
            got = md5(src)
            if got != want:
                bad.append((kit, fn, got, want))
                continue
            data = open(src, 'rb').read()
            if SECRET.search(data):
                bad.append((kit, fn, 'secret-pattern', None))
                continue
            shutil.copyfile(src, os.path.join(dst, fn))
            files[fn] = got
        json.dump({'kit': kit, 'code': spec['code'], 'manifest': spec['manifest'], 'snapshot_as_of': man['as_of'],
                   'files': files}, open(os.path.join(dst, 'KIT.json'), 'w'), indent=1, sort_keys=True)
        print(kit, spec['code'], len(files), 'files ok')
    if bad:
        print('MISMATCH', bad)
        sys.exit(1)


if __name__ == '__main__':
    main()
