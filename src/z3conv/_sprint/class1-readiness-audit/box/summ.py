"""summ.py TAG : compact per-model bolt summaries from the audit dumps in wk/<TAG>/<sha12>/dump.json.gz (+ stats from S3 keys).
Writes summ_<TAG>.json {sha: {path, n, rows: [[count, key...]], groups: [...] }} and uploads it next to the per-model outputs."""
import json, gzip, os, sys, glob, collections, boto3
TAG = sys.argv[1]
B = 'bim-proprietary-data'; OUT = f'cad-disk-extract/zenitude-data-3/_state/agentwork/class1-readiness-audit/{TAG}'
s3 = boto3.client('s3', region_name='ap-south-1')
ids = {j['sha256'][:12]: j['sha256'] for j in json.load(open('job/ids.json'))}
res = {}
K = ('standard', 'd_stored', 'd', 'src', 'tolraw', 'tol', 'wh', 'w2', 'wn', 'nuts', 'holes_only', 'washer_exact', 'axial_decoded', 'axial',
     'shifted', 'head_up', 'holed', 'family', 'washer_t', 'washer_od', 'nut_h', 'head_h', 'nutfam', 'slot12', 'wd', 'L')
for p in sorted(glob.glob(f'wk/{TAG}/*/dump.json.gz')):
    s12 = p.split('/')[-2]; sha = ids.get(s12, s12)
    try:
        d = json.load(gzip.open(p, 'rt'))
    except Exception as e:
        res[sha] = {'error': str(e)[:200]}; continue
    c = collections.Counter()
    for b in d['bolts']:
        pr = (b.get('prof') or '').split('/')
        fam = (b.get('family') or '')
        b['wd'] = tuple(b['washer_dims']) if b.get('washer_dims') else None
        key = (b.get('standard'), b.get('d_stored'), b.get('d'), b.get('src'), pr[3] if len(pr) > 3 else None, b.get('tol'), b.get('wh'), b.get('w2'),
               b.get('wn'), b.get('nuts'), bool(b.get('holes_only')), bool(b.get('washer_exact')), bool(b.get('axial_decoded')), b.get('axial'),
               bool(b.get('shift')), bool(b.get('head_up')), (b.get('holes') or 0) > 0, fam[:60], b.get('washer_t'), b.get('washer_od'),
               b.get('nut_h'), b.get('head_h'), ('nominal nut' in fam) or ('nut from' in fam),
               '/'.join(pr[1:3]) if len(pr) > 2 else None, b.get('wd'), b.get('L'))
        c[key] += 1
    # per group: the [approx: ...] tags db1step writes into the bolt-group name (old path: convert_old pass 2; v2: _convert)
    G = collections.defaultdict(list)
    for b in d['bolts']: G[b.get('g')].append(b)
    slot = {g.get('g'): g for g in (d.get('groups') or [])}
    gt = collections.Counter(); gtag = collections.Counter(); gho = 0
    for g, bl_all in G.items():
        bl = [b for b in bl_all if not b.get('holes_only')]
        if not bl: gho += 1; continue
        sg = bl[0].get('src'); tags = []
        if not sg: tags.append('head_nut_nominal')
        if any(b.get('tol') is None for b in bl): tags.append('hole_nominal')
        if d.get('path') == 'old':
            fitted = any(b.get('shift') for b in bl)
            if fitted: tags.append('axial_fitted')
            if any(not b.get('axial_decoded') for b in bl) and not fitted: tags.append('axial_as_recorded')
            if any(b.get('wh') or b.get('wn') or b.get('w2') for b in bl):
                if not all(b.get('washer_exact') for b in bl): tags.append('washer_nominal')
                if any(b.get('w2') for b in bl): tags.append('washer2_inferred')
        else:
            if any(b.get('head_up') and not b.get('axial_decoded') for b in bl): tags.append('axial_from_plies')
            if any(not b.get('head_up') for b in bl): tags.append('axial_unknown')
            fam = bl[0].get('family') or ''
            if any(b.get('wh') or b.get('wn') or b.get('w2') for b in bl) and not (sg and (bl[0].get('washer_t') or 'ISO' in fam)): tags.append('washer_nominal')
            gg = slot.get(g) or {}
            if (gg.get('slot_parts') or 0) and ((gg.get('slot_x') or 0) > 0 or (gg.get('slot_y') or 0) > 0): tags.append('slot_round')
        gt['groups_written'] += 1
        if tags: gt['groups_tagged'] += 1
        for t in tags: gtag[t] += 1
    gt['groups_holes_only'] = gho
    res[sha] = {'path': d.get('path'), 'n': len(d['bolts']), 'keys': K, 'rows': [[v] + list(k) for k, v in c.most_common()],
                'group_counts': dict(gt), 'group_tags': dict(gtag)}
json.dump(res, open(f'summ_{TAG}.json', 'w'), default=str)
s3.upload_file(f'summ_{TAG}.json', B, f'{OUT}/_summ.json')
print(len(res), 'models summarised')
