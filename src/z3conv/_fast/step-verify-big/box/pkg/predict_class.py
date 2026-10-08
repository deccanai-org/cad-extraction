#!/usr/bin/env python3
"""predict_class.py FINAL_DIR OUT.json  (box; instance role, read-only S3)
Class of each model before / after overlaying a final-pass readback record built from step_verify_big.py, computed with the
coordinator's own code (a read-only copy of coord/build_index.py: classify_ifc + apply_final + the live rules.json), so the
'lifted' numbers are the index builder's verdicts, not an estimate. FINAL_DIR holds f-ifc-<id[:40]>-readback.json records."""
import sys, os, json, glob, gzip
os.environ.setdefault('INDEX_WORK', os.path.join(os.getcwd(), 'index_work'))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'coord_copy'))
import build_index as bi                                   # noqa: E402


def main():
    fdir, outp = sys.argv[1], sys.argv[2]
    bi.RULES = dict(bi.DEFAULT_RULES); bi.RULES.update(bi.getj(f'{bi.CTL}/coord/rules.json', bi.CB) or {})
    finals = {}
    for p in sorted(glob.glob(os.path.join(fdir, 'f-ifc-*-readback.json'))):
        r = json.load(open(p)); finals[r['id']] = r
    want = {r['model_id'] for r in finals.values()}
    rows = [json.loads(l) for l in gzip.decompress(bi.s3.get_object(Bucket=bi.B, Key=f'{bi.ST}/scan/contents_ifc.jsonl.gz')['Body'].read()).decode().splitlines() if l.strip()]
    cs = {c['id']: c for c in rows if c['id'] in want}
    out = []
    for mid in sorted(want):
        c = cs.get(mid)
        if c is None:
            out.append({'id': mid, 'error': 'not in contents_ifc'}); continue
        res = bi.getj(f'{bi.ST}/ifc/results/{mid}.json')
        grade = bi.getj(f'{bi.ST}/grade/results/ifc-{mid}.json')
        before = bi.classify_ifc(c, res, grade)
        after = bi.classify_ifc(c, bi.apply_final('ifc', mid, res, finals), bi.apply_final('ifc', mid, grade, finals))
        out.append({'id': mid, 'class_before': before.get('class'), 'class_after': after.get('class'),
                    'issues_before': before.get('issues'), 'issues_after': after.get('issues'),
                    'reasons_after': after.get('reasons'), 'standins_after': after.get('standins'),
                    'graded_by_after': after.get('graded_by'), 'solids_after': after.get('solids'),
                    'invalid_solids_after': after.get('invalid_solids'), 'coverage_all_after': after.get('coverage_all'),
                    'corpus_after': after.get('corpus')})
    import collections
    summ = {'models': len(out), 'class_before': dict(collections.Counter(o.get('class_before') for o in out)),
            'class_after': dict(collections.Counter(o.get('class_after') for o in out)),
            'lifted_to_class1': [o['id'] for o in out if o.get('class_after') == 1 and o.get('class_before') != 1],
            'not_read_back_large_file_cleared': sum(1 for o in out if 'not_read_back_large_file' in (o.get('issues_before') or [])
                                                    and 'not_read_back_large_file' not in (o.get('issues_after') or [])),
            'issues_after_count': dict(collections.Counter(i.split(':')[0] for o in out for i in (o.get('issues_after') or [])))}
    json.dump({'summary': summ, 'models': out}, open(outp, 'w'), indent=1)
    print(json.dumps(summ, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
