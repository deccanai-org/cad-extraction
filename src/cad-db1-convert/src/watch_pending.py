"""Watch the DB1 jobs that are not final under the strict rule (a g step_fail without the cut-snap writer
tag is still pending) + end-game markers. Prints one line per change. bim profile."""
import json, time, boto3, pickle, collections
s3 = boto3.Session(profile_name="bim").client("s3", region_name="ap-south-1"); B = "annotationprod"; R = "cad-disk-extract"
jobs, rs = pickle.load(open("/private/tmp/claude-501/-Users-dhiren-Downloads-Deccan/7c4aa40f-8a98-4322-9286-b3fa20c9602b/scratchpad/db1_snap.pkl", "rb"))
FINAL = "db1-2026-09-25g"
_K = {"empty_model", "no_member_layout", "no_resolvable_members", "bad_output", "deferred_layout"}
KEEP = {c: _K for c in ("db1-2026-09-25b", "db1-2026-09-25c", "db1-2026-09-25d", "db1-2026-09-25e")}
KEEP["db1-2026-09-25f"] = _K | {"ok", "suspect_orientation", "suspect_attr_link", "convert_error"}
def strict_final(r):
    if not r: return False
    if r.get("code") == FINAL and r.get("status") == "step_fail" and not r.get("writer"): return False
    return r.get("code") == FINAL or r.get("status") in KEEP.get(r.get("code"), ())
watch = [j for j, r in zip(jobs, rs) if j["engine"] != "None" and not strict_final(r)]
watch += [j for j, r in zip(jobs, rs) if r and r.get("code") == FINAL and r.get("status") == "step_fail"]
last = None; lastm = None
while True:
    st = collections.Counter(); w = 0
    for j in watch:
        try: r = json.loads(s3.get_object(Bucket=B, Key=f"{R}/_state/db1-v2/results/{j['sha']}.json")["Body"].read())
        except Exception: r = None
        if strict_final(r): st["final:" + r["status"]] += 1
        else: st["pending:" + str((r or {}).get("status")) + ":" + str((r or {}).get("code"))[-1:]] += 1
        if r and r.get("writer"): w += 1
    cur = f"watched {len(watch)} " + " ".join(f"{k}={v}" for k, v in sorted(st.items())) + f" | cut-snap results {w}"
    mk = sorted(o["Key"].rsplit("/", 1)[1] for o in s3.list_objects_v2(Bucket=B, Prefix=f"{R}/_control/packaging/endgame/").get("Contents", [])
                if not o["Key"].rsplit("/", 1)[1].startswith("log_") and not o["Key"].endswith((".py", ".sh")))
    if cur != last: print(time.strftime("%H:%MZ", time.gmtime()), cur, flush=True); last = cur
    if mk != lastm:
        if lastm is not None: print(time.strftime("%H:%MZ", time.gmtime()), "MARKERS", " ".join(sorted(set(mk) - set(lastm))), flush=True)
        lastm = mk
    time.sleep(120)
