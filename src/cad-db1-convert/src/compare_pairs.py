"""No-fabrication check: for every model that exists both as a Tekla DB1 file and as Tekla's own IFC export
(pairs.json), compare the DB1-derived STEP with the IFC-derived STEP part by part.
A DB1 part is 'matched' when an IFC part's centroid lies within 30 mm (after a single translation that
aligns the two exports) and its sorted bounding-box extents agree within max(10 mm, 5 %).
Unmatched DB1 parts are candidates for invented geometry. READ-ONLY (bim).
  compare_pairs.py WORKDIR  -> WORKDIR/pairs_report.json + one line per pair"""
import collections, json, os, re, sys, time
import boto3, numpy as np
from scipy.spatial import cKDTree

W = sys.argv[1]; os.makedirs(W, exist_ok=True)
s3 = boto3.Session(profile_name="bim").client("s3", region_name="ap-south-1"); B = "annotationprod"; R = "cad-disk-extract"
pairs = json.loads(s3.get_object(Bucket=B, Key=f"{R}/_control/db1-v2/pairs.json")["Body"].read())
MAXB = 600 << 20
FINAL = {"db1-2026-09-25g", "db1-2026-09-25f"}
RX_PT = re.compile(rb"^#\d+\s*=\s*CARTESIAN_POINT\('[^']*',\(([^)]*)\)\)")
RX_PR = re.compile(rb"^#\d+\s*=\s*PRODUCT\(")
RX_NM = re.compile(rb"^#\d+\s*=\s*PRODUCT\('([^']*)'")
RX_IFCPROF = re.compile(rb"=\s*IFC(?:BEAM|COLUMN|PLATE|MEMBER)\s*\('[^']*',[^,]*,(?:'[^']*'|\$),(?:'([^']*)'|\$),(?:'([^']*)'|\$)")

def getj(k):
    try: return json.loads(s3.get_object(Bucket=B, Key=k)["Body"].read())
    except Exception: return None

def parts(path):
    """per part (closed by its PRODUCT line): AABB centre, sorted AABB extents, sorted principal-axis extents
    (placement independent), name. The header's global origin point (0,0,0) precedes the first part's
    geometry and is not a part vertex."""
    cents, exts, pcas, names, cur = [], [], [], [], []
    first = True
    with open(path, "rb") as fh:
        for ln in fh:
            m = RX_PT.match(ln)
            if m:
                try: cur.append([float(v) for v in m.group(1).split(b",")])
                except ValueError: pass
                continue
            pm = RX_NM.match(ln)
            if pm:
                if first:
                    cur = [q for q in cur if any(abs(v) > 1e-9 for v in q)]; first = False
                if cur:
                    a = np.asarray(cur); lo, hi = a.min(0), a.max(0)
                    cents.append((lo + hi) / 2); exts.append(np.sort(hi - lo))
                    bb = a - a.mean(0)
                    try:
                        v = np.linalg.svd(bb, full_matrices=False)[2]; pr = bb @ v.T
                        pcas.append(np.sort(pr.max(0) - pr.min(0)))
                    except Exception: pcas.append(np.sort(hi - lo))
                    names.append(pm.group(1).decode(errors="replace"))
                cur = []
    return np.asarray(cents), np.asarray(exts), np.asarray(pcas), names

def match(c1, e1, c2, e2):
    tree = cKDTree(c2); off = np.median(c2, 0) - np.median(c1, 0)
    for _ in range(4):                                   # refine the single translation between the exports
        d, j = tree.query(c1 + off, k=1); off = off + np.median(c2[j] - (c1 + off), 0)
    cand = tree.query_ball_point(c1 + off, r=30.0)
    ok1 = np.zeros(len(c1), bool); used = np.zeros(len(c2), bool)
    for i, js in enumerate(cand):
        for jj in js:
            if np.all(np.abs(e1[i] - e2[jj]) <= np.maximum(10.0, 0.05 * e2[jj])):
                ok1[i] = True; used[jj] = True; break
    return ok1, used, off

out = []
for p in pairs:
    row = {"sha": p["sha"], "engine": p["engine"], "db1": p["db1"].rsplit("/", 1)[-1]}
    r = getj(f"{R}/_state/db1-v2/results/{p['sha']}.json")
    if not r or r.get("status") != "ok" or r.get("code") not in FINAL:
        row["skip"] = f"db1 not converted ({(r or {}).get('status')})"; out.append(row); print(json.dumps(row), flush=True); continue
    ikey = p["ifc"][0]
    try: h = s3.head_object(Bucket=B, Key=ikey); iid = f"{h['ETag'].strip(chr(34)).replace('-', 'm')}_{h['ContentLength']}"
    except Exception: row["skip"] = "ifc source not found"; out.append(row); print(json.dumps(row), flush=True); continue
    ir = getj(f"{R}/_state/ifc-step/results/{iid}.json")
    if not ir or ir.get("status") != "ok":
        row["skip"] = f"ifc not converted ({(ir or {}).get('status')})"; out.append(row); print(json.dumps(row), flush=True); continue
    try:
        sizes = (s3.head_object(Bucket=B, Key=r["out_key"])["ContentLength"], s3.head_object(Bucket=B, Key=ir["out_key"])["ContentLength"])
        if max(sizes) > MAXB or h["ContentLength"] > MAXB: row["skip"] = f"STEP too large for this check {sizes}"; out.append(row); print(json.dumps(row), flush=True); continue
        f1, f2, f3 = os.path.join(W, "db1.stp"), os.path.join(W, "ifc.stp"), os.path.join(W, "src.ifc")
        s3.download_file(B, r["out_key"], f1); s3.download_file(B, ir["out_key"], f2); s3.download_file(B, ikey, f3)
        c1, e1, p1, n1 = parts(f1); c2, e2, p2, n2 = parts(f2)
        # same model? profile inventory of the DB1 decode vs the IFC export's own profile names
        norm = lambda t: re.sub(r"\s+", "", t.upper())
        ip = collections.Counter()
        with open(f3, "rb") as fh: txt = fh.read()
        for m in RX_IFCPROF.finditer(txt): ip[norm((m.group(2) or m.group(1) or b"").decode(errors="replace"))] += 1
        dp = collections.Counter(norm(x) for x in n1)
        inter = sum(min(v, ip[k]) for k, v in dp.items()); union = sum((dp | ip).values())
        ident = inter / union if union else 0.0
        head = txt[:4000].decode(errors="replace"); fn = re.search(r"FILE_NAME\s*\(\s*(?:/\*[^*]*\*/\s*)?'([^']*)'", head)
        ok1, used, off = match(c1, e1, c2, e2)
        tp = cKDTree(p2); sh = np.zeros(len(p1), bool)
        for i, js in enumerate(tp.query_ball_point(p1, r=60.0)):
            for jj in js:
                if np.all(np.abs(p1[i] - p2[jj]) <= np.maximum(10.0, 0.03 * p2[jj])): sh[i] = True; break
        row.update(db1_parts=len(c1), ifc_parts=len(c2), same_model_profile_overlap=round(ident, 3),
                   ifc_file_name=(fn.group(1)[-80:] if fn else None), shape_match_frac=round(float(sh.mean()), 4) if len(p1) else None,
                   db1_matched=int(ok1.sum()), db1_match_frac=round(float(ok1.mean()), 4) if len(c1) else None,
                   ifc_covered_frac=round(float(used.mean()), 4) if len(c2) else None, offset_mm=[round(float(x), 1) for x in off])
        if len(c1) and ok1.mean() < 1:
            um = np.where(~ok1)[0][:5]
            row["unmatched_examples"] = [{"centre": [round(float(x)) for x in c1[i]], "extents": [round(float(x)) for x in e1[i]]} for i in um]
    except Exception as ex:
        row["error"] = f"{type(ex).__name__}: {str(ex)[:160]}"
    finally:
        for f in ("db1.stp", "ifc.stp", "src.ifc"):
            try: os.remove(os.path.join(W, f))
            except OSError: pass
    out.append(row); print(json.dumps(row), flush=True)
json.dump(out, open(os.path.join(W, "pairs_report.json"), "w"), indent=1)
done = [x for x in out if "db1_parts" in x]
same = [x for x in done if x["same_model_profile_overlap"] >= 0.5]
print("PAIRS", len(pairs), "compared", len(done), "same-model pairs", len(same),
      "| DB1 parts", sum(x["db1_parts"] for x in same), "shape-matched", round(sum(x["shape_match_frac"] * x["db1_parts"] for x in same)),
      "position-matched", sum(x["db1_matched"] for x in same), flush=True)
