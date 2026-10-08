import os, sys, json, time, collections
os.environ["PKG_SOURCES"] = "db1"; sys.path.insert(0, "/opt/pkg")
import pkg_step as P
# accept any final-looking ok result for the dry run (f in progress): measure mapping coverage only
P.FINAL = {"db1-2026-09-25f": None, "db1-2026-09-25e": None, "db1-2026-09-25d": None, "db1-2026-09-25c": None, "db1-2026-09-25b": None}
t = time.time(); plan = P.build_plan_db1()
placed = collections.Counter(a["out_key"] for p in plan for a in p["adds"])
ok = {r["sha"] for r in P.results("cad-disk-extract/_state/db1-v2/results/") if r.get("status") == "ok" and r.get("code") in P.FINAL}
placed_sha = {k.rsplit("/", 1)[1][:-4] for k in placed}
out = {"projects": len(plan), "adds": sum(len(p["adds"]) for p in plan), "ok_shas": len(ok), "ok_shas_placed": len(ok & placed_sha),
       "ok_shas_not_placed": sorted(ok - placed_sha)[:3000], "secs": round(time.time() - t)}
P.s3().put_object(Bucket=P.B, Key="cad-disk-extract/_control/packaging/report/db1_plan_dry.json", Body=json.dumps(out).encode())
print({k: v for k, v in out.items() if k != "ok_shas_not_placed"}, "not placed:", len(out["ok_shas_not_placed"]))
