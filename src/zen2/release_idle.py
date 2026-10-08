"""release_idle.py - terminate data-4 boxes that are idle (no archive running) twice in a row, only when no archive is
waiting unclaimed. Busy boxes and boxes with stale/no heartbeats are never touched (those are reported for a manual look)."""
import boto3, calendar, collections, datetime, json, sys, time
from concurrent.futures import ThreadPoolExecutor
ses = boto3.Session(profile_name='annotationprod-publish')
s3 = ses.client('s3', region_name='ap-south-1')
B, R = 'annotationprod', 'cad-disk-extract/zentitude-data-4'
DRY = '--dry' in sys.argv


def lst(prefix):
    out, tok = [], None
    while True:
        kw = dict(Bucket=B, Prefix=prefix)
        if tok: kw['ContinuationToken'] = tok
        r = s3.list_objects_v2(**kw); out += r.get('Contents', [])
        if not r.get('IsTruncated'): return out
        tok = r['NextContinuationToken']


def snapshot():
    hb_objs = [o for o in lst(f'{R}/_state/hosts/') if (datetime.datetime.now(datetime.timezone.utc) - o['LastModified']).total_seconds() < 120]
    with ThreadPoolExecutor(48) as ex:
        hbs = [json.loads(s3.get_object(Bucket=B, Key=o['Key'])['Body'].read()) for o in hb_objs]
    fresh = [h for h in hbs if time.time() - calendar.timegm(time.strptime(h['updated'], '%Y-%m-%dT%H:%M:%SZ')) < 120]
    running = collections.Counter(); alive = set()
    for h in fresh:
        ip = h['host'].split('.')[0].replace('ip-', '').replace('-', '.'); alive.add(ip)
        running[ip] += len(h.get('running', {}))
    jobs = json.loads(s3.get_object(Bucket=B, Key=f'{R}/_control/jobs.json')['Body'].read())
    done = {o['Key'].rsplit('/', 1)[-1][:-5] for o in lst(f'{R}/_state/results/')}
    claimed = {o['Key'].rsplit('/', 1)[-1][:-5] for o in lst(f'{R}/_state/claims/')}
    unclaimed = [j for j in jobs if j['id'] not in done and j['id'] not in claimed]
    return running, alive, unclaimed, len(jobs) - len(done)


def boxes():
    out = {}
    for region in ('ap-south-1', 'ap-south-2'):
        r = ses.client('ec2', region_name=region).describe_instances(Filters=[{'Name': 'tag:Name', 'Values': ['cad-z4-extract*']},
                                                                              {'Name': 'instance-state-name', 'Values': ['running']}])
        for res in r['Reservations']:
            for i in res['Instances']:
                out[i['PrivateIpAddress']] = (region, i['InstanceId'])
    return out


r1, a1, u1, rem1 = snapshot(); print('snapshot 1: remaining', rem1, 'unclaimed', len(u1), 'boxes alive', len(a1), 'busy', sum(1 for v in r1.values() if v))
time.sleep(120)
r2, a2, u2, rem2 = snapshot(); print('snapshot 2: remaining', rem2, 'unclaimed', len(u2), 'boxes alive', len(a2), 'busy', sum(1 for v in r2.values() if v))
bx = boxes()
if u1 or u2:
    print('archives still waiting unclaimed -> not releasing anything'); sys.exit(0)
idle = [ip for ip in bx if ip in a1 and ip in a2 and r1.get(ip, 0) == 0 and r2.get(ip, 0) == 0]
unknown = [ip for ip in bx if ip not in a2]
print('idle both times:', len(idle), '| no fresh heartbeat (left alone, check manually):', unknown)
for ip in idle:
    region, iid = bx[ip]
    if DRY:
        print('would terminate', region, iid, ip); continue
    ses.client('ec2', region_name=region).terminate_instances(InstanceIds=[iid])
    print('terminated', region, iid, ip)
