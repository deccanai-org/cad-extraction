"""Existing fleet stage-2 outputs of the invalid_solids fallbacks (conversions/sds2-step/_not_accepted/<id>/...): re-judge
them with the patched run_batch.parse_log (last read-back block) and grade with the coordinator. No re-conversion."""
import os, sys, json, re, importlib.util, tempfile, boto3
sys.argv += []
W = '/work/agentwork/sds2-weights-failures'; J = f'{W}/j2'
sys.path.insert(0, J)
import gradecheck2 as G                                  # reuses its loaders, result() and grade()
s3 = boto3.client('s3', region_name='ap-south-1'); BK = 'bim-proprietary-data'
RBo = G.load(f'{J}/b553/sds2-step-pipeline/batch/run_batch.py', 'rb_old')
RBn = G.load(f'{J}/w553b/sds2-step-pipeline/batch/run_batch.py', 'rb_new')
ids = json.load(open(sys.argv[1]))
out = {}
for jid in ids:
    r = json.loads(s3.get_object(Bucket=BK, Key=f'cad-disk-extract/zenitude-data-3/_state/conv/sds2/results/{jid}.json')['Body'].read())
    pre = (r.get('outputs') or {}).get('prefix'); files = (r.get('outputs') or {}).get('files') or []
    d = tempfile.mkdtemp(prefix='pc_', dir=f'{J}/tmp') if os.path.isdir(f'{J}/tmp') else tempfile.mkdtemp(prefix='pc_')
    for f in files:
        if f.endswith(('stage2.log', '_manifest.json')):
            s3.download_file(BK, pre + f, os.path.join(d, 'run.log' if f.endswith('.log') else f))
    rec = {'name': r.get('name'), 'converter': (r.get('converter') or {}).get('label'), 'fleet_reason': r.get('stage2_reason')}
    for lab, RB, side in (('old_parse', RBo, 'cur'), ('new_parse', RBn, 'new')):
        res, pub, why = G.result(d, jid, G.WK[side], lab, RB)
        rec[lab] = {'publish2': pub, 'stage2_reason': why, 'solids': res['stage2'].get('solids'), 'valid': res['stage2'].get('valid'),
                    'grade_cur_rule': G.grade(res, G.BI['cur'])}
        if side == 'new':
            rec[lab]['grade_new_rule'] = G.grade(res, G.BI['new'])
    out[jid] = rec
json.dump(out, open(sys.argv[2], 'w'), indent=1, default=str)
print('done', len(out))
