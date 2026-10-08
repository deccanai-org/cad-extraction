#!/usr/bin/env python3
"""Which SDS/2 converter build produced a shipped STEP (standard library only; runs on the Mac in make_jobs or in the
stage container).

resolve_pin(row, result=None) -> {'label', 'zip', 'sha256', 'basis', 'checks': [...]} or raises PinError.

  row     the package manifest row of the STEP (or a job dict with the same keys): step_key (or source_key), converter
          {'code', 'version'}
  result  optional: the conversion fleet's result JSON of the model (_state/conv/sds2/results/<model_id>.json)

Order of evidence (the first that applies wins; the byte-identical re-run in the stage is the final proof either way):
  1. 'conversion_result'   result['step']['key'] == the shipped step_key: result['converter'] is the build that wrote
                            exactly that object
  2. 'r2_run'              step_key under the v4 r2 run prefix (sds2-step-r2-20260929-01/): v4-candidate; a result
                            JSON of such a model describes a later re-run that was NOT shipped (n5: result says v5.5.0)
  3. 'label_table'         converter.version (and the step_key's /<label>/ folder when it has one; both must agree)
                            looked up in converters.json
A result whose step key differs from the shipped one is recorded in 'checks' and never used.
usage: pin.py MANIFEST_ROW.json [RESULT.json]"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
TABLE = json.load(open(os.path.join(HERE, 'converters.json')))


class PinError(ValueError):
    pass


def _label_from_key(step_key):
    m = re.match(r'cad-disk-extract/[^/]+/conversions/sds2-step/[^/]+/(v[0-9][^/]*)/[^/]+$', step_key or '')
    return m.group(1) if m else None


def resolve_pin(row, result=None):
    step_key = row.get('step_key') or row.get('source_key') or ''
    conv = row.get('converter') or {}
    version = conv.get('version') or row.get('converter_version')
    checks = []
    if result:
        rk = ((result.get('step') or {}).get('key')) or ''
        rc = result.get('converter') or {}
        if rk and rk == step_key and rc.get('zip') and rc.get('sha256'):
            ent = TABLE['labels'].get(rc.get('label'))
            if ent and (ent['zip'], ent['sha256']) != (rc['zip'], rc['sha256']):
                raise PinError(f"result names {rc} but converters.json has {ent} for label {rc.get('label')}")
            if version and rc.get('label') != version:
                checks.append(f"manifest converter.version {version} != result label {rc.get('label')} (result wins: it wrote the shipped key)")
            return dict(label=rc['label'], zip=rc['zip'], sha256=rc['sha256'], basis='conversion_result', checks=checks)
        checks.append(f"result JSON describes another run (its step key {rk[-90:]!r}, converter {rc.get('label')}): not used")
    if step_key.startswith(TABLE['r2_run_prefix']):
        lab = TABLE['r2_run_label']
        if version and version != lab:
            raise PinError(f'step_key is in the v4 r2 run but converter.version is {version}')
        ent = TABLE['labels'][lab]
        return dict(label=lab, zip=ent['zip'], sha256=ent['sha256'], basis='r2_run', checks=checks)
    kl = _label_from_key(step_key)
    if kl and version and kl != version:
        raise PinError(f'step_key folder label {kl} != converter.version {version}')
    lab = kl or version
    if not lab:
        raise PinError('no converter label (step_key without a version folder and no converter.version)')
    ent = TABLE['labels'].get(lab)
    if not ent:
        raise PinError(f'converter label {lab} not in converters.json (no pinned zip)')
    return dict(label=lab, zip=ent['zip'], sha256=ent['sha256'], basis='label_table', checks=checks)


if __name__ == '__main__':
    row = json.load(open(sys.argv[1]))
    res = json.load(open(sys.argv[2])) if len(sys.argv) > 2 else None
    print(json.dumps(resolve_pin(row, res), indent=1))
