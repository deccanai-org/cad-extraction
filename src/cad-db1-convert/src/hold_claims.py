"""keep claims on a few jobs fresh so no worker (old or new code) can finish the run while the
fleet switches code; results of these jobs are removed so they stay 'not done'.
  hold_claims.py start|refresh|release"""
import sys, json, time, boto3
s3 = boto3.Session().client('s3', region_name='ap-south-1'); B = 'annotationprod'; ST = 'cad-disk-extract/_state/db1-v2'
J = json.load(open('db1_jobs.json')); J = J['jobs'] if isinstance(J, dict) else J
shas = [l.strip() for l in open('/tmp/holdjobs.txt') if l.strip()]
full = [j['sha'] for j in J if any(j['sha'].startswith(s) for s in shas)]
mode = sys.argv[1]
body = json.dumps({"host": "hold-for-redeploy", "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}).encode()
for sha in full:
    if mode == 'start':
        s3.delete_object(Bucket=B, Key=f"{ST}/results/{sha}.json")
        s3.delete_object(Bucket=B, Key=f"cad-disk-extract/conversions/db1-step/{sha}.stp")
    if mode in ('start', 'refresh'):
        s3.put_object(Bucket=B, Key=f"{ST}/claims/{sha}.json", Body=body)
    if mode == 'release':
        s3.delete_object(Bucket=B, Key=f"{ST}/claims/{sha}.json")
print(mode, len(full), 'jobs', time.strftime('%H:%M:%SZ', time.gmtime()))
