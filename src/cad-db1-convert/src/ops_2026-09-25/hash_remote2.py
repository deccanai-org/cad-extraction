import hashlib, json, subprocess
from concurrent.futures import ThreadPoolExecutor
P="s3://annotationprod/cad-disk-extract/_control/db1-v2/never_attempted/hash_keys.json"
keys=json.loads(subprocess.run(["aws","s3","cp","--region","ap-south-1",P,"-"],capture_output=True,check=True).stdout)
def h(k):
    x=hashlib.sha256(); n=0
    p=subprocess.Popen(["aws","s3","cp","--region","ap-south-1","s3://annotationprod/"+k,"-"],stdout=subprocess.PIPE)
    for c in iter(lambda: p.stdout.read(8<<20), b""): x.update(c); n+=len(c)
    rc=p.wait()
    return x.hexdigest() if rc==0 else "ERR%d"%rc, n
with ThreadPoolExecutor(16) as ex: out=list(ex.map(h,keys))
print("HASHES "+json.dumps(out))
