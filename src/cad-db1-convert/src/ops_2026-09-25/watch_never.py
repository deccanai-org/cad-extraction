import json, time, collections, boto3, sys
from concurrent.futures import ThreadPoolExecutor
from botocore.config import Config
ses=boto3.Session(profile_name="bim"); s3=ses.client("s3",region_name="ap-south-1",config=Config(max_pool_connections=48))
ec2={r:ses.client("ec2",region_name=r) for r in ("ap-south-1","ap-south-2")}
B="annotationprod"; R="cad-disk-extract"; W=sys.argv[1]
new=json.load(open(W+"never_jobs_added.json")); shas=[j["sha"] for j in new]+["865f3309e5d4b6e2bd93e1244094d596abecc4f429b2b8419133ff34f6e14ce6"]
def res(sha):
    try: r=json.loads(s3.get_object(Bucket=B,Key=f"{R}/_state/db1-v2/results/{sha}.json")["Body"].read()); return sha,(r.get("status"),r.get("code"))
    except Exception: pass
    try: s3.head_object(Bucket=B,Key=f"{R}/_state/db1-v2/claims/{sha}.json"); return sha,("running",None)
    except Exception: return sha,("queued",None)
prev=None; seen=None
while True:
    try:
        with ThreadPoolExecutor(32) as ex: rs=dict(ex.map(res,shas))
        c=collections.Counter(v[0] for k,v in rs.items() if k!=shas[-1])
        f865=rs[shas[-1]][0]
        mk=sorted(o["Key"].rsplit("/",1)[1] for o in s3.list_objects_v2(Bucket=B,Prefix=f"{R}/_control/packaging/endgame/").get("Contents",[]) if "/" not in o["Key"][len(f"{R}/_control/packaging/endgame/"):] and not o["Key"].rsplit("/",1)[1].startswith("log_") and not o["Key"].endswith((".py",".sh")))
        n=0
        for r,c2 in ec2.items():
            for rv in c2.describe_instances(Filters=[{"Name":"instance-state-name","Values":["pending","running","stopping","shutting-down"]},{"Name":"tag:Name","Values":["cad-db1-step*","cad-db1-re","cad-pkg-step*"]}])["Reservations"]: n+=len(rv["Instances"])
        cur=(tuple(sorted(c.items())),f865,n)
        if cur!=prev: print(time.strftime("%H:%MZ",time.gmtime()),"new40:",dict(c),"| 865f:",f865,"| cad instances:",n,flush=True); prev=cur
        if seen is not None and set(mk)-set(seen): print(time.strftime("%H:%MZ",time.gmtime()),"MARKER:",sorted(set(mk)-set(seen)),flush=True)
        seen=mk
        if c.get("queued",0)+c.get("running",0)==0 and f865 not in ("running","queued") and n<=3: print("ALL-SETTLED",flush=True); break
    except Exception as e: print("watch error",type(e).__name__,str(e)[:80],flush=True)
    time.sleep(120)
