"""Read-only corpus check of piece-table layout detection: v4 piece_table.slot_size() vs the patched rule, on the first
201 KiB of every job's subm/subm_idx (ranged GET) + its full size. usage: survey_slot_pick.py <out.jsonl>"""
import sys, os, json, gzip, re, boto3, concurrent.futures as cf
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'v4', 'sds2-step-pipeline', 'decode'))
import piece_table as PT
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'patched'))
s3 = boto3.Session(profile_name='bim').client('s3', region_name='ap-south-1')
B = 'bim-proprietary-data'
jobs = json.load(open('data/jobs.json'))
NAME = re.compile(rb"(W|M|S|HP|C|MC|L|WT|MT|ST|HSS|TS|PIPE|PL|FL|BAR|RD|SQ|BLT|HS|NS|WS|TWS|AB|RB|DBA|THD|STUD|Conc|GT|GR|PLG|WBX|WPS|BP|CP|SP|[0-9]+(K|LH|DLH|G|BG|VG))[0-9A-Za-z. /x-]")
def one(j):
    try:
        b = s3.get_object(Bucket=B, Key=j['files_key'])['Body'].read()
        try: b = gzip.decompress(b)
        except OSError: pass
        fs = {f['p'].replace('\\', '/').lower(): f for f in json.loads(b)}
        si = fs.get('subm/subm_idx')
        if not si or not si.get('key') or si['size'] < 2048: return dict(id=j['id'], skip='no subm_idx')
        head = s3.get_object(Bucket=B, Key=si['key'], Range=f'bytes=0-{1024 * 201 - 1}')['Body'].read()
        old = PT.slot_size(head)
        res = {}
        for key, L in PT.LAYOUTS.items():
            S, o = L['slot'], L['name']
            n = min(200, len(head) // S)
            res[str(key)] = dict(exact=(si['size'] - 256) % S == 0,
                                 filled=sum(bool(re.match(rb"[!-~]", head[k * S + o:k * S + o + 1])) for k in range(1, n)),
                                 plausible=sum(bool(NAME.match(head[k * S + o:k * S + o + 6])) for k in range(1, n)))
        return dict(id=j['id'], name=j['name'], size=si['size'], old=str(old), layouts=res)
    except Exception as e:
        return dict(id=j['id'], err=str(e)[:200])
with cf.ThreadPoolExecutor(32) as ex, open(sys.argv[1], 'w') as out:
    for r in ex.map(one, jobs):
        out.write(json.dumps(r) + '\n')
