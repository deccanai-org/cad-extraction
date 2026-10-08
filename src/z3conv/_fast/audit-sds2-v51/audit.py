#!/usr/bin/env python3
"""SDS2 v5.1 swap regression audit (data-3 fleet). Read-only on S3.

usage: AWS_PROFILE=bim python3 audit.py [--sync]
  --sync   refresh the local snapshot under ./s3/ (results, logs, deferred, claims, redo list, non-STEP outputs)
Writes ./out/{per_job.csv, regressions.json, fleet_by_code.json, bestof.json, summary.json}

Per job and converter label (v4 / v5 / v5.1) it merges four sources:
  1. results/<id>.json        current record (its 'converter.label' = whose STEP is stored; 'code' = last code that ran)
  2. alternatives{}           the other version of the last best-of comparison (status, est, solids, manifest class)
  3. conversions/sds2-step/<id>/[v5|v5.1]/job.json + *_manifest.json   every published version's own counts
  4. host logs                every run line of every worker process (status, reason, seconds) incl. memory kills
"""
import os, sys, re, json, glob, csv, gzip, subprocess, collections, statistics

HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE)
B = 's3://bim-proprietary-data/cad-disk-extract/zenitude-data-3'
ST = f'{B}/_state/conv/sds2'
LABELS = ('v4', 'v5', 'v5.1')
CLASS_RANK = {1: 1, 2: 2, 3: 3, 0: 4, None: 5}          # manifest class: 1 best ... 0 (broken) worst


def sync():
    cmds = [['aws', 's3', 'sync', '--only-show-errors', f'{ST}/{d}/', f's3/sds2/{d}/'] for d in ('results', 'logs', 'deferred', 'claims')]
    cmds += [['aws', 's3', 'cp', '--quiet', f'{ST}/{f}', f's3/sds2/{f}'] for f in ('jobs.json', 'redo.json', 'jobs_reconvert.json')]
    cmds += [['aws', 's3', 'sync', '--only-show-errors', f'{B}/conversions/sds2-step/', 's3/out/', '--exclude', '*.step']]
    cmds += [['aws', 's3', 'cp', '--quiet', f'{B}/_state/conv/index.jsonl.gz', 's3/conv/index.jsonl.gz'],
             ['aws', 's3', 'cp', '--quiet', f'{B}/_state/conv_status.json', 's3/conv_status.json']]
    ps = [subprocess.Popen(c) for c in cmds]
    for p in ps: p.wait()


def lab(code):
    m = re.match(r'z3-sds2-(v[\d.]+?)-2026', str(code or ''))
    return m.group(1) if m else None


def load_logs():
    runs = collections.defaultdict(list); kills = collections.defaultdict(list); procs = {}
    for f in glob.glob('s3/sds2/logs/*.log'):
        t = open(f, errors='replace').read()
        m = re.search(r'worker code=(\S+)', t); code = lab(m.group(1)) if m else None
        hp = os.path.basename(f)[:-4]; procs[hp] = code
        for mm in re.finditer(r'^(\d\d:\d\d:\d\d) WATCHDOG killed (\w+) rss=(\d+)GB avail=(\d+)GB', t, re.M):
            kills[mm.group(2)].append({'code': code, 't': mm.group(1), 'rss_gb': int(mm.group(3)), 'proc': hp})
        for mm in re.finditer(r'^(\d\d:\d\d:\d\d)\s+(ok_stage1|ok|fail|deferred)\s+(\S*)\s+(\d+)MB\s+([\d.]+)s\s+(\w+)', t, re.M):
            runs[mm.group(6)].append({'code': code, 't': mm.group(1), 'status': mm.group(2), 'reason': mm.group(3) or None,
                                      'sec': float(mm.group(5)), 'proc': hp})
    return runs, kills, procs


def manifest_of(d):
    g = glob.glob(f'{d}/*_stage2_manifest.json')
    if not g: return None
    try: return json.load(open(g[0]))
    except Exception: return None


def out_versions(jid):
    """published (and not-accepted) outputs per label from conversions/sds2-step"""
    res = {}
    for label in LABELS:
        for base, acc in ((f's3/out/{jid}', True), (f's3/out/_not_accepted/{jid}', False)):
            d = base if label == 'v4' else f'{base}/{label}'
            jj = f'{d}/job.json'
            if not os.path.exists(jj): continue
            try: j = json.load(open(jj))
            except Exception: continue
            if lab(j.get('code')) != label: continue
            s2 = j.get('stage2') or {}; v = j.get('validate') or {}; m = manifest_of(d) or {}
            c = m.get('counts') or {}; sk = m.get('skipped') or {}
            res.setdefault(label, []).append({
                'accepted': acc, 'published': j.get('published'), 'stage': 1 if j.get('published') == 'stage1' else 2,
                'solids': v.get('solids'), 'invalid': v.get('invalid'), 'steel_ratio': s2.get('steel_ratio'),
                'wall_s': s2.get('wall_s'), 'step_mb': s2.get('step_mb'), 'rc': s2.get('rc'),
                'm_class': m.get('class'), 'm_corpus': m.get('corpus'), 'm_reasons': m.get('class_reasons'),
                'skipped': sk.get('total') if isinstance(sk, dict) else (len(sk) if isinstance(sk, list) else None),
                'skipped_by_reason': sk.get('by_reason') if isinstance(sk, dict) else None,
                'reference_parts': c.get('reference_parts'), 'solids_written': c.get('solids_written'),
                'standins_total': (m.get('standins') or {}).get('total') if m else None,
                'ratio_m': (m.get('weight_check') or {}).get('ratio') if m else None,
                'readback_top': (m.get('readback') or {}).get('top_level_shapes') if m else None,
                'converted': j.get('converted'), 'dir': d})
    return res


def est_tuple(a):
    return tuple(a) if isinstance(a, list) else None


def main():
    if '--sync' in sys.argv: sync()
    os.makedirs('out', exist_ok=True)
    jobs = {j['id']: j for j in json.load(open('s3/sds2/jobs.json'))}
    by16 = {i[:16]: i for i in jobs}
    R = {}
    for f in glob.glob('s3/sds2/results/*.json'):
        try: r = json.load(open(f))
        except Exception: continue
        R[r['id']] = r
    runs16, kills16, procs = load_logs()
    runs = collections.defaultdict(list); kills = collections.defaultdict(list)
    for k, v in runs16.items(): runs[by16.get(k, k)] += v
    for k, v in kills16.items(): kills[by16.get(k, k)] += v
    D = {}
    for f in glob.glob('s3/sds2/deferred/*.json'):
        try: d = json.load(open(f)); D[d['id']] = d
        except Exception: pass
    redo = set(json.load(open('s3/sds2/redo.json'))) if os.path.exists('s3/sds2/redo.json') else set()
    claims = {}
    for f in glob.glob('s3/sds2/claims/*.json'):
        try: c = json.load(open(f)); claims[os.path.basename(f)[:-5]] = lab(c.get('code'))
        except Exception: pass

    ids = set(R) | set(runs) | {os.path.basename(p) for p in glob.glob('s3/out/*') if len(os.path.basename(p)) == 24}
    rows = []; regress = []; bestof = []
    for jid in sorted(ids):
        j = jobs.get(jid, {}); r = R.get(jid) or {}
        V = {lb: {'runs': [], 'outputs': [], 'alt': None, 'stored': None} for lb in LABELS}
        for x in runs.get(jid, []):
            if x['code'] in V: V[x['code']]['runs'].append(x)
        for lb, outs in out_versions(jid).items(): V[lb]['outputs'] = outs
        if r:
            sl = (r.get('converter') or {}).get('label') or lab(r.get('code'))
            if sl in V:
                v = r.get('validate') or {}; m = r.get('manifest') or {}
                V[sl]['stored'] = {'status': r.get('status'), 'reason': r.get('reason'), 'solids': v.get('solids'),
                                   'invalid': v.get('invalid'), 'm_class': m.get('class'), 'm_corpus': m.get('corpus'),
                                   'reference_parts': (m.get('counts') or {}).get('reference_parts'),
                                   'skipped': sum(x for x in (m.get('skipped_by_reason') or {}).values() if isinstance(x, int)) if m else None,
                                   'wall_s': (r.get('stage2') or {}).get('wall_s'), 'sec': r.get('sec')}
            for lb, a in (r.get('alternatives') or {}).items():
                if lb in V:
                    V[lb]['alt'] = {'status': a.get('status'), 'reason': a.get('reason'), 'est': a.get('est'),
                                    'solids': (a.get('step') or {}).get('solids'), 'm_class': a.get('manifest_class'), 'ratio': a.get('ratio')}

        def outcome(lb):
            """best evidence of what label lb did on this job: ok / ok_stage1 / fail:<reason> / deferred / None"""
            v = V[lb]; st = set()
            if v['stored']: st.add(v['stored']['status'] if v['stored']['status'] != 'fail' else f"fail:{v['stored']['reason']}")
            if v['alt']: st.add(v['alt']['status'] if v['alt']['status'] != 'fail' else f"fail:{v['alt']['reason']}")
            for o in v['outputs']:
                if o['accepted'] and o['published'] is True: st.add('ok')
                elif o['published'] == 'stage1': st.add('ok_stage1')
            for x in v['runs']:
                st.add(x['status'] if x['status'] != 'fail' else f"fail:{x['reason']}")
            for s in ('ok', 'ok_stage1'):
                if s in st: return s
            f = sorted(s for s in st if s.startswith('fail'))
            if f: return f[0]
            return 'deferred' if 'deferred' in st else None

        def best_counts(lb):
            v = V[lb]; c = {}
            for o in v['outputs']:
                if o['accepted'] and o['published'] is True:
                    c = dict(o); break
            if not c and v['stored'] and v['stored']['status'] == 'ok': c = dict(v['stored'])
            if not c and v['alt'] and v['alt']['status'] == 'ok': c = dict(v['alt'])
            return c

        oc = {lb: outcome(lb) for lb in LABELS}
        cn = {lb: best_counts(lb) for lb in LABELS}
        nkill = {lb: sum(1 for x in V[lb]['runs'] if x['status'] == 'deferred') for lb in LABELS}
        secs = {lb: max([x['sec'] for x in V[lb]['runs'] if x['status'] in ('ok', 'ok_stage1')] or [0]) or None for lb in LABELS}
        walls = {lb: cn[lb].get('wall_s') for lb in LABELS}
        row = {'id': jid, 'name': j.get('name') or r.get('name'), 'model_mb': round((j.get('model_bytes') or r.get('model_bytes') or 0) / 2 ** 20),
               'version': r.get('version') or next((o.get('version') for o in []), None), 'in_redo': jid in redo,
               'claimed_by': claims.get(jid), 'current_code': lab(r.get('code')), 'stored_label': (r.get('converter') or {}).get('label'),
               'status_now': r.get('status'), 'reason_now': r.get('reason'), 'chosen': r.get('chosen'), 'best_of_note': r.get('best_of_note')}
        for lb in LABELS:
            row[f'{lb}_outcome'] = oc[lb]; row[f'{lb}_kills'] = nkill[lb]
            row[f'{lb}_solids'] = cn[lb].get('solids'); row[f'{lb}_invalid'] = cn[lb].get('invalid')
            row[f'{lb}_class'] = cn[lb].get('m_class'); row[f'{lb}_skipped'] = cn[lb].get('skipped')
            row[f'{lb}_ref_parts'] = cn[lb].get('reference_parts'); row[f'{lb}_wall_s'] = walls[lb]; row[f'{lb}_job_s'] = secs[lb]
        rows.append(row)

        # ---------------- regression rules: v5.1 vs every earlier label with evidence
        rank = lambda o: {'ok': 0, 'ok_stage1': 1}.get(o, 3 if o == 'deferred' else (2 if o and o.startswith('fail') else 9))
        new = oc['v5.1']
        for old in ('v4', 'v5'):
            if oc[old] is None or new is None: continue
            reasons = []
            if rank(new) > rank(oc[old]) and rank(new) < 9:
                reasons.append(f'outcome {oc[old]} -> {new}')
            if new == 'ok' and oc[old] == 'ok':
                a, b = cn['v5.1'], cn[old]
                if a.get('solids') is not None and b.get('solids') and a['solids'] < 0.99 * b['solids']:
                    reasons.append(f"solids {b['solids']} -> {a['solids']}")
                if (a.get('invalid') or 0) > (b.get('invalid') or 0):
                    reasons.append(f"invalid {b.get('invalid')} -> {a.get('invalid')}")
                if a.get('skipped') is not None and b.get('skipped') is not None and a['skipped'] > b['skipped']:
                    reasons.append(f"skipped {b['skipped']} -> {a['skipped']}")
                if a.get('m_class') is not None and b.get('m_class') is not None and CLASS_RANK[a['m_class']] > CLASS_RANK[b['m_class']]:
                    reasons.append(f"manifest class {b['m_class']} -> {a['m_class']}")
                if walls['v5.1'] and walls[old] and walls['v5.1'] > 1.5 * walls[old] and walls['v5.1'] - walls[old] > 120:
                    reasons.append(f"converter wall {walls[old]}s -> {walls['v5.1']}s")
            if nkill['v5.1'] and rank(oc[old]) <= 1 and new not in ('ok', 'ok_stage1'):
                reasons.append(f'v5.1 memory-killed {nkill["v5.1"]}x (no v5.1 result yet) where {old} finished')
            if reasons:
                regress.append({'id': jid, 'name': row['name'], 'vs': old, 'reasons': reasons, 'row': row})
        # v5 vs v4 too (context: v5 was live for ~50 min)
        if oc['v4'] and oc['v5'] and rank(oc['v5']) > rank(oc['v4']) and rank(oc['v5']) < 9:
            regress.append({'id': jid, 'name': row['name'], 'vs': 'v4', 'new': 'v5', 'reasons': [f"v5 outcome {oc['v4']} -> {oc['v5']}"], 'row': row})

        # ---------------- best-of audit
        if r.get('chosen') or r.get('alternatives'):
            ch = r.get('chosen'); cur = lab(r.get('code'))
            for lb, a in (r.get('alternatives') or {}).items():
                if a.get('status') not in ('ok', 'ok_stage1') and r.get('status') in ('ok', 'ok_stage1'): continue
                stored = (r.get('converter') or {}).get('label')
                e_alt = est_tuple(a.get('est'))
                ent = {'id': jid, 'name': row['name'], 'stored_label': stored, 'code': cur, 'chosen': ch, 'alt_label': lb,
                       'alt_est': a.get('est'), 'note': r.get('best_of_note'), 'stored_solids': (r.get('validate') or {}).get('solids'),
                       'alt_solids': (a.get('step') or {}).get('solids'), 'stored_ratio': (r.get('stage2') or {}).get('steel_ratio'),
                       'alt_ratio': a.get('ratio'), 'alt_manifest_class': a.get('manifest_class'),
                       'stored_has_manifest': bool(r.get('manifest'))}
                flags = []
                if ch and ch != cur and ent['stored_solids'] == ent['alt_solids']:
                    flags.append('kept_older_with_equal_solid_count')
                if ch and ch != cur and not ent['stored_has_manifest'] and a.get('manifest_class') is not None:
                    flags.append('kept_untagged_v4_over_tagged_new_output')
                if r.get('best_of_note') and e_alt:
                    m = re.search(r'\(\[(.*?)\] vs \[(.*?)\]\)', r['best_of_note'])
                    if m:
                        x = [float(t) for t in m.group(1).split(',')]; y = [float(t) for t in m.group(2).split(',')]
                        if x[:3] == y[:3] and abs(x[3] - y[3]) < 0.0011:
                            flags.append('decided_by_ratio_rounding_only (<0.0011)')
                        if x[0] == y[0] and x[1] == y[1] and x[2] != y[2]:
                            flags.append('decided_by_skipped_count')
                # phantom skipped: v5-era manifest summary counted the keys total/by_reason/parts
                for src in (r.get('manifest') or {},):
                    sbr = src.get('skipped_by_reason') or {}
                    if 'by_reason' in sbr or 'parts' in sbr:
                        flags.append('stored_manifest_summary_has_phantom_skipped_keys')
                ent['flags'] = flags
                bestof.append(ent)

    # ---------------- fleet stats per code (from host logs; every run, not only final results)
    fleet = {}
    for lb in LABELS:
        rr = [x for v in runs.values() for x in v if x['code'] == lb]
        kk = [x for v in kills.values() for x in v if x['code'] == lb]
        oks = [x['sec'] for x in rr if x['status'] in ('ok', 'ok_stage1')]
        fleet[lb] = {'runs': len(rr), 'by_status': dict(collections.Counter(x['status'] for x in rr)),
                     'fail_reasons': dict(collections.Counter(x['reason'] for x in rr if x['status'] == 'fail').most_common()),
                     'kills': len(kk), 'kills_rss0': sum(1 for x in kk if x['rss_gb'] == 0),
                     'kills_rss_ge16': sum(1 for x in kk if x['rss_gb'] >= 16),
                     'killed_rss_gb_median': statistics.median([x['rss_gb'] for x in kk]) if kk else None,
                     'ok_job_s_median': statistics.median(oks) if oks else None,
                     'first': min((x['t'] for x in rr), default=None), 'last': max((x['t'] for x in rr), default=None),
                     'processes': sum(1 for p, c in procs.items() if c == lb)}
    final = collections.Counter((lab(r.get('code')), (r.get('converter') or {}).get('label'), r.get('status')) for r in R.values())
    summ = {'snapshot_results': len(R), 'jobs_total': len(jobs), 'final_by_code_storedlabel_status': {f'{a}|{b}|{c}': n for (a, b, c), n in sorted(final.items(), key=str)},
            'deferred_records': len(D), 'claims_by_code': dict(collections.Counter(claims.values())), 'redo_list': len(redo),
            'regressions': len(regress), 'bestof_entries': len(bestof),
            'bestof_flagged': sum(1 for b in bestof if b['flags'])}
    json.dump(fleet, open('out/fleet_by_code.json', 'w'), indent=1)
    json.dump(regress, open('out/regressions.json', 'w'), indent=1, default=str)
    json.dump(bestof, open('out/bestof.json', 'w'), indent=1, default=str)
    json.dump(summ, open('out/summary.json', 'w'), indent=1)
    keys = list(rows[0].keys()) if rows else []
    with open('out/per_job.csv', 'w', newline='') as f:
        w = csv.DictWriter(f, keys); w.writeheader(); [w.writerow(x) for x in rows]
    print(json.dumps(summ, indent=1)); print(json.dumps(fleet, indent=1))


if __name__ == '__main__':
    main()
