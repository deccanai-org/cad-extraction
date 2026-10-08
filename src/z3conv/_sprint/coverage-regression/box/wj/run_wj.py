#!/usr/bin/env python3
"""BOX job (coverage-regression): exact per-part Tekla-id join of every graded Windows-pipeline STEP (reuse_from =
disk-1/2-windows) with the grader's python-decoder inventory (grade/detail/db1-<sha>.decoded_parts.json.gz), plus the
Windows pipeline's own per-part schedule (part_schedule.csv next to the STEP). Read-only on the sources; the STEP is
streamed from S3 and never stored. Output: <OUT>/<sha>.json and <OUT>/_summary.json.

per model:
  join       windows_join.join(): coverage member / connection / other / all against the decoder inventory (+ axis drops)
  schedule   Windows part_schedule.csv: rows, rows with solids, build_path counts, id overlap with the decoder inventory
  lost       decoder parts with no solid in the Windows STEP, split by why: 'win_no_solid' (Windows listed the part, built
             no solid), 'win_not_listed' (the Windows reader never listed the id), by category / profile / decoder how
  extra      Windows solids for ids the decoder skipped (unresolved profile etc.) or does not know
"""
import os, sys, json, gzip, io, csv, time, collections, traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
import boto3, botocore
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import windows_join as wj

B = 'bim-proprietary-data'
DET = 'cad-disk-extract/zenitude-data-3/_state/conv/grade/detail'
OUT = os.environ.get('WJ_OUT', 'cad-disk-extract/zenitude-data-3/_state/agentwork/coverage-regression/wj')
LOC = os.path.join(HERE, 'out'); os.makedirs(LOC, exist_ok=True)


def s3c():
    return boto3.client('s3', region_name='ap-south-1', config=botocore.config.Config(retries={'max_attempts': 8, 'mode': 'standard'}))


def stream_lines(body, chunk=8 << 20):
    rest = b''
    while True:
        b = body.read(chunk)
        if not b:
            break
        b = rest + b
        parts = b.split(b'\n')
        rest = parts.pop()
        for p in parts:
            yield p.decode('latin-1') + '\n'
    if rest:
        yield rest.decode('latin-1')


def schedule_of(s3, step_key):
    k = step_key.rsplit('/', 1)[0] + '/part_schedule.csv'
    try:
        txt = s3.get_object(Bucket=B, Key=k)['Body'].read().decode('latin-1')
    except Exception as e:
        return None, f'{type(e).__name__}'
    rows = {}
    for r in csv.DictReader(io.StringIO(txt)):
        try:
            rows[int(r['part_id'])] = r
        except (KeyError, ValueError, TypeError):
            continue
    return rows, k


def one(job):
    sha = job['sha']; t0 = time.time(); s3 = s3c()
    out = {'sha': sha, 'step_key': job['step_key']}
    try:
        parts = json.load(gzip.open(io.BytesIO(s3.get_object(Bucket=B, Key=f'{DET}/db1-{sha}.decoded_parts.json.gz')['Body'].read()), 'rt'))
        body = s3.get_object(Bucket=B, Key=job['step_key'])['Body']
        sc = wj.scan(stream_lines(body))
        r = wj.join(sc, parts, job.get('axis_dropped') or 0)
        out['join'] = r
        out['scan'] = {k: v for k, v in sc.items() if k != 'by_id'}
        by_id = sc['by_id']
        present = {i for i, v in by_id.items() if v['solids'] > 0}
        dec = {}
        for p in parts:
            try:
                dec[int(p[0])] = p
            except (TypeError, ValueError):
                pass
        sched, sk = schedule_of(s3, job['step_key'])
        out['schedule_key'] = sk
        if sched is not None:
            bp = collections.Counter((x.get('build_path') or '?') for x in sched.values())
            with_sol = sum(1 for x in sched.values() if (x.get('solids') or '0').strip() not in ('', '0'))
            out['schedule'] = {'rows': len(sched), 'rows_with_solids': with_sol, 'build_path': dict(bp.most_common(20)),
                               'ids_in_decoder': sum(1 for i in sched if i in dec), 'ids_not_in_decoder': sum(1 for i in sched if i not in dec),
                               'decoder_ids_not_in_schedule': sum(1 for i in dec if i not in sched),
                               'decoder_ids_not_in_schedule_by_cat': dict(collections.Counter(dec[i][2] for i in dec if i not in sched))}
        # lost: decoder parts (written by the python decoder or not) with no solid in the Windows STEP
        lost = collections.Counter(); lost_prof = collections.Counter(); lost_how = collections.Counter()
        for i, p in dec.items():
            if i in present or p[2] == 'feature':
                continue
            if sched is None:
                why = 'no_schedule'
            elif i in sched:
                why = 'win_no_solid:' + (sched[i].get('build_path') or '?')
            else:
                why = 'win_not_listed'
            lost[(p[2], why)] += 1
            lost_prof[(p[2], why.split(':')[0], p[1])] += 1
            lost_how[(p[2], p[3], p[4])] += 1
        out['lost'] = {'by_cat_why': [[c, w, n] for (c, w), n in lost.most_common(30)],
                       'by_cat_why_profile': [[c, w, pr, n] for (c, w, pr), n in lost_prof.most_common(25)],
                       'by_decoder_status': [[c, s, h, n] for (c, s, h), n in lost_how.most_common(20)]}
        extra = collections.Counter()
        for i in present:
            p = dec.get(i)
            if p is None:
                extra[('unknown_to_decoder', '', '')] += 1
            elif p[3] != 'written':
                extra[(p[2], p[4], p[1])] += 1
        out['extra'] = [[c, h, pr, n] for (c, h, pr), n in extra.most_common(20)]
        out['status'] = 'ok'
    except Exception as e:
        out['status'] = 'error'; out['error'] = f'{type(e).__name__}: {str(e)[:300]}'; out['trace'] = traceback.format_exc()[-1500:]
    out['sec'] = round(time.time() - t0, 1)
    p = os.path.join(LOC, sha + '.json')
    json.dump(out, open(p, 'w'))
    try:
        s3.upload_file(p, B, f'{OUT}/{sha}.json')
    except Exception as e:
        out['upload_error'] = str(e)[:200]
    return sha, out.get('status'), out['sec'], (out.get('join') or {}).get('coverage')


if __name__ == '__main__':
    jobs = json.load(open(os.path.join(HERE, 'wj_jobs.json')))
    jobs.sort(key=lambda j: -(j.get('step_bytes') or 0))                 # biggest first
    par = int(os.environ.get('PAR', '10'))
    summ = {}
    with ProcessPoolExecutor(par) as ex:
        futs = [ex.submit(one, j) for j in jobs]
        for f in as_completed(futs):
            sha, st, sec, cov = f.result()
            summ[sha] = {'status': st, 'sec': sec, 'coverage': cov}
            print(sha[:12], st, sec, json.dumps(cov), flush=True)
            json.dump(summ, open(os.path.join(LOC, '_summary.json'), 'w'), indent=1)
            s3c().upload_file(os.path.join(LOC, '_summary.json'), B, f'{OUT}/_summary.json')
    print('DONE', len(summ), flush=True)
