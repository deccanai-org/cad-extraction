# layout_diff.py BASE_DECODE PATCH_DECODE JOBDIR... : per job, calibrate() / sparse_layout() / read_members() layout with the
# base sds2job and with the patched one (read-only)
import sys, os, json, importlib.util, collections, traceback
def load(name, d):
    spec = importlib.util.spec_from_file_location(name, os.path.join(d, 'sds2job.py'))
    m = importlib.util.module_from_spec(spec); sys.modules[name] = m; spec.loader.exec_module(m); return m
sys.path.insert(0, sys.argv[1])   # piece_table (calibrate's main-piece agreement) must be importable, as in the converter
B = load('sj_base', sys.argv[1]); P = load('sj_pat', sys.argv[2])
for job in sys.argv[3:]:
    rec = {'job': job}
    try:
        sh = B.read_shapes(job); rec['ver'] = B.read_version(job)
        md = os.path.join(job, 'mem')
        rec['member_files'] = sum(1 for n in os.listdir(md) if n.isdigit())
        try:
            rec['calibrate'] = B.calibrate(job, sh)
        except ValueError as e:
            rec['calibrate_err'] = str(e)
            rec['sparse_base'] = B.sparse_layout(job, sh)
            rec['sparse_patch'] = P.sparse_layout(job, P.read_shapes(job))
        for nm, M in (('base', B), ('patch', P)):
            try:
                mem, L = M.read_members(job)
                rec[nm] = {'layout': L, 'n': len(mem), 'types': collections.Counter(m.type for m in mem).most_common(5),
                           'with_section': sum(1 for m in mem if m.section is not None)}
            except Exception as e:
                rec[nm] = {'err': f'{type(e).__name__}: {e}'}
    except Exception as e:
        rec['err'] = f'{type(e).__name__}: {e}'
    rec['same'] = rec.get('base') == rec.get('patch')
    print(json.dumps(rec, default=str), flush=True)
