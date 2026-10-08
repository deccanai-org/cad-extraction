import csv, glob, json, collections, sys, os
W='/work/agentwork/sds2-weights-failures-review'
out={}
for jid in [l.strip() for l in open(f'{W}/ids_nx.txt') if l.strip()]:
    a=glob.glob(f'{W}/out/w553/{jid}/*_stage2_pieces.csv'); b=glob.glob(f'{W}/out/w553nx/{jid}/*_stage2_pieces.csv')
    if not a or not b: out[jid]='missing'; continue
    A=list(csv.DictReader(open(a[0]))); Bv=list(csv.DictReader(open(b[0])))
    key=lambda r:(r['member'], r['piece'], round(float(r['ox'] or 0),2), round(float(r['oy'] or 0),2), round(float(r['oz'] or 0),2))
    pa=collections.Counter(key(r) for r in A if r.get('kind') not in ('member',) and r.get('builder') not in ('member_envelope','joist_openweb_standin','joist_envelope_approx'))
    pb=collections.Counter(key(r) for r in Bv if r.get('builder')=='unindexed_brep')
    ba=collections.Counter(r.get('builder') for r in A); bb=collections.Counter(r.get('builder') for r in Bv)
    only_a=pa-pb; only_b=pb-pa; both=pa&pb
    # names of pieces present in normal but not placed unindexed
    nm={(r['member'],r['piece']):r['name'] for r in A}
    oa=collections.Counter(nm.get((k[0],k[1]),'?').split()[0] if nm.get((k[0],k[1])) else '?' for k in only_a.elements())
    sk=glob.glob(f'{W}/out/w553nx/{jid}/*_stage2_skipped.csv')
    skr=collections.Counter(r.get('reason') for r in csv.DictReader(open(sk[0]))) if sk else {}
    ma=json.load(open(glob.glob(f'{W}/out/w553/{jid}/*_manifest.json')[0])); mb=json.load(open(glob.glob(f'{W}/out/w553nx/{jid}/*_manifest.json')[0]))
    out[jid]=dict(normal_piece_rows=sum(pa.values()), unindexed_rows=sum(pb.values()), matched=sum(both.values()),
                  only_normal=sum(only_a.values()), only_unindexed=sum(only_b.values()), only_normal_by_family=dict(oa.most_common(12)),
                  only_unindexed_examples=[list(k) for k in list(only_b)[:8]], builders_normal=dict(ba), builders_nx=dict(bb), skipped_nx=dict(skr),
                  dup_normal=(ma.get('counts') or {}).get('converter_duplicates_skipped'),
                  readback_normal=ma.get('readback'), readback_nx=mb.get('readback'), class_nx=[mb.get('class'), mb.get('corpus'), mb.get('class_reasons')],
                  counts_nx={k: (mb.get('counts') or {}).get(k) for k in ('placed_pieces','pieces_written','skipped','solids_written','member_envelopes','piece_table_absent','subm_piece_files','bolts_sds2')},
                  counts_normal={k: (ma.get('counts') or {}).get(k) for k in ('placed_pieces','pieces_written','skipped','solids_written','member_envelopes','bolts_sds2')})
json.dump(out, open(f'{W}/nxcmp.json','w'), indent=1, default=str)
print(json.dumps(out, indent=1, default=str)[:6000])
