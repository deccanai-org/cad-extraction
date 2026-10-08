"""ssm.py REGION INSTANCE[,INSTANCE...] SCRIPTFILE [timeout_s] -> runs the shell script via SSM, prints output."""
import boto3, sys, time, json
region, ids, script = sys.argv[1], sys.argv[2].split(','), open(sys.argv[3]).read()
tmo = int(sys.argv[4]) if len(sys.argv) > 4 else 600
c = boto3.Session(profile_name=None if (__import__('os').environ.get('AWS_ACCESS_KEY_ID') or __import__('os').environ.get('AWS_PROFILE')) else 'annotationprod-publish').client('ssm', region_name=region)
cid = c.send_command(InstanceIds=ids, DocumentName='AWS-RunShellScript',
                     Parameters={'commands': [script], 'executionTimeout': [str(tmo)]})['Command']['CommandId']
t0 = time.time(); done = {}
while len(done) < len(ids) and time.time() - t0 < tmo + 60:
    time.sleep(4)
    for i in ids:
        if i in done: continue
        try:
            r = c.get_command_invocation(CommandId=cid, InstanceId=i)
        except Exception:
            continue
        if r['Status'] in ('Success', 'Failed', 'Cancelled', 'TimedOut'):
            done[i] = r
for i, r in done.items():
    print(f"== {i} {r['Status']}\n{r['StandardOutputContent'][-3000:]}{r['StandardErrorContent'][-1500:]}")
