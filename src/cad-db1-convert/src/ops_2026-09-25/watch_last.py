import json, time, boto3
from botocore.config import Config
ses=boto3.Session(profile_name="bim"); s3=ses.client("s3",region_name="ap-south-1")
ec2={r:ses.client("ec2",region_name=r) for r in ("ap-south-1","ap-south-2")}
B="annotationprod"; R="cad-disk-extract"
J={"865f":"865f3309e5d4b6e2bd93e1244094d596abecc4f429b2b8419133ff34f6e14ce6","ESC(unknown)":"8e59d534531291ace8aa43c97fbd0b5573fc624017689efbdb3e8cdfc912cf40"}
def st(sha):
    try:
        r=json.loads(s3.get_object(Bucket=B,Key=f"{R}/_state/db1-v2/results/{sha}.json")["Body"].read())
        return f"{r.get('status')}{'/rescue='+str((r.get('rescue') or {}).get('result')) if r.get('rescue') else ''}{'/excluded='+str(len(r.get('excluded_elements') or [])) if r.get('excluded_elements') else ''}"
    except Exception: return "none"
prev=None
while True:
    try:
        s={k:st(v) for k,v in J.items()}
        n=0
        for r,c in ec2.items():
            for rv in c.describe_instances(Filters=[{"Name":"instance-state-name","Values":["pending","running","stopping","shutting-down"]},{"Name":"tag:Name","Values":["cad-db1-step","cad-db1-step-mum","cad-db1-re","cad-pkg-step*"]}])["Reservations"]: n+=len(rv["Instances"])
        cur=(tuple(sorted(s.items())),n)
        if cur!=prev: print(time.strftime("%H:%MZ",time.gmtime()),s,"| fleet boxes up:",n,flush=True); prev=cur
        if n==0: print("FLEET-GONE",flush=True); break
    except Exception as e: print("watch error",type(e).__name__,str(e)[:80],flush=True)
    time.sleep(120)
