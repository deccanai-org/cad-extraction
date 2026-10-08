"""Synthetic, clearly labelled TEST fixtures for the publisher: tiny scripts/ trees + bundles. They contain no geometry and
are only ever published to the fake package target s3://.../_state/pmp/fakepkg/<pid>/ (never a real package)."""
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import bundle_lib as BL  # noqa: E402

TAG = 'PMP PUBLISHER TEST FIXTURE - synthetic, not a model, not geometry'


def write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)


def make_tree(root, model_folder, model_id, step_source='ifc', readme_extra='', n_missing=1, stem=None):
    """root = the scripts/ folder to create"""
    stem = stem or model_folder
    shutil.rmtree(root, ignore_errors=True)
    write(os.path.join(root, 'README.md'), f'# scripts/ ({TAG})\n{readme_extra}')
    write(os.path.join(root, 'requirements.txt'), 'build123d==0.13.0\n')
    write(os.path.join(root, 'steelbuild.py'), f'# {TAG}\n')
    write(os.path.join(root, 'issues_lib.py'), f'# {TAG}\n')
    m = os.path.join(root, model_folder)
    write(os.path.join(m, 'build_model.py'), f'# {TAG}: build_model.py for {model_id}\n')
    write(os.path.join(m, 'build_issues_model.py'), f'# {TAG}: build_issues_model.py for {model_id}\n')
    write(os.path.join(m, 'model_info.json'), json.dumps(dict(model_id=model_id, note=TAG)) + '\n')
    write(os.path.join(m, 'schedules', 'parts.csv'), 'part_id,profile\n1,TEST\n')
    write(os.path.join(m, 'schedules', 'issues.json'), json.dumps(dict(note=TAG, issues=[])) + '\n')
    write(os.path.join(m, 'schedules', 'missing_parts.json'), json.dumps(dict(note=TAG, parts=[{'id': i} for i in range(n_missing)])) + '\n')
    write(os.path.join(m, 'verification', 'verification.csv'), 'part_id,verdict\n1,test\n')
    write(os.path.join(m, 'issues', 'WHERE_TO_LOOK.md'), f'# {TAG}\n')
    write(os.path.join(m, 'issues', f'{stem}{BL.ISSUES_STEP_SUFFIX}'), f'ISO-10303-21;\n/* {TAG} */\nEND-ISO-10303-21;\n')
    if n_missing:
        write(os.path.join(m, 'issues', f'{stem}{BL.MISSING_STEP_SUFFIX}'), f'ISO-10303-21;\n/* {TAG} */\nEND-ISO-10303-21;\n')
    write(os.path.join(m, 'source', 'provenance.json'), json.dumps(dict(note=TAG, step_source=step_source)) + '\n')
    if step_source in ('db1', 'sds2'):
        write(os.path.join(m, 'source', f'{stem}.ifc'), f'ISO-10303-21;\n/* {TAG} */\nEND-ISO-10303-21;\n')
    return root


def make(out_dir, run, pid, model_id, model_folder, step_relpath, step_source='ifc', readme_extra='', n_missing=1, work=None):
    work = work or os.path.join(out_dir, '_work', model_id)
    tree = make_tree(os.path.join(work, 'scripts'), model_folder, model_id, step_source, readme_extra, n_missing)
    header = dict(run=run, model_id=model_id, pid=pid, model_folder=model_folder, step_relpath=step_relpath,
                  step_source=step_source, code_version='pmp-test-fixture/1')
    src = lambda rel: f'test fixture: publish/tests/fixtures.py ({rel})'  # noqa: E731
    out = os.path.join(out_dir, f'{model_id}.tar.gz')
    info = BL.make_bundle(tree, out, header, src)
    return out, info
