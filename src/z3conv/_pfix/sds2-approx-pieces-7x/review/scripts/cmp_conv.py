"""cmp_conv.py OUTDIR BASEVAR CANDVAR -> JSON per job: placements / builders / class / read-back / steel, base vs cand."""
import sys, os, re, json, csv, collections, glob
O, B, C = sys.argv[1:4]
APPROX = {"plate_from_vertices", "rolled_profile_extrusion", "piece_table_standin", "vertex_box", "member_envelope"}
csv.field_size_limit(1 << 30)
def load(var, job):
    d = os.path.join(O, var, job)
    r = dict(dir=d)
    m = glob.glob(os.path.join(d, "*_manifest.json"))
    if not m: return None
    man = json.load(open(m[0])); r["man"] = man
    rows = {}
    pc = glob.glob(os.path.join(d, "*_pieces.csv"))
    if pc:
        for row in csv.DictReader(open(pc[0], newline="", errors="replace")):
            rows[(row["member"], row["piece"], row["inst"], row["builder"] == "member_envelope")] = row
    r["rows"] = rows
    rc = open(os.path.join(d, "rc.txt")).read() if os.path.exists(os.path.join(d, "rc.txt")) else ""
    r["rc"] = rc.split()[0] if rc else "?"; mw = re.search(r"wall=(\d+)", rc); r["wall"] = int(mw.group(1)) if mw else None
    lg = glob.glob(os.path.join(d, "*_stage2.log")); t = open(lg[0], errors="replace").read() if lg else ""
    r["log_tail"] = t[-1500:]
    mm = re.findall(r"manifest after read-back: class (\d) corpus (\w)", t); r["log_class"] = mm[-1] if mm else None
    return r
out = {}
for j in sorted(set(os.listdir(os.path.join(O, B))) & set(os.listdir(os.path.join(O, C)))):
    b, c = load(B, j), load(C, j)
    if not b or not c:
        out[j] = dict(incomplete=True, base=bool(b), cand=bool(c)); continue
    bm, cm = b["man"], c["man"]
    kb, kc = set(b["rows"]), set(c["rows"])
    trans = collections.Counter(); moved = []; label_changes = collections.Counter()
    for k in kb & kc:
        rb, rc_ = b["rows"][k], c["rows"][k]
        if rb["builder"] != rc_["builder"]:
            trans[f'{rb["builder"]} -> {rc_["builder"]}'] += 1
            label_changes[rc_.get("standin", "")[:80]] += 1
        dx = max(abs(float(rb[a] or 0) - float(rc_[a] or 0)) for a in ("ox", "oy", "oz"))
        if dx > 1e-3: moved.append((k, dx))
    nb = collections.Counter(r["builder"] for r in b["rows"].values()); nc = collections.Counter(r["builder"] for r in c["rows"].values())
    def appx(n): return sum(v for k, v in n.items() if k in APPROX or any(w in k for w in ("fallback", "standin", "envelope", "vertex_box", "extrusion", "from_vertices")))
    rbk, rck = bm.get("readback", {}), cm.get("readback", {})
    out[j] = dict(
        version=bm.get("version"), rc=[b["rc"], c["rc"]], wall=[b["wall"], c["wall"]],
        cls=[f'{bm.get("class")}{bm.get("corpus")}', f'{cm.get("class")}{cm.get("corpus")}'],
        class_reasons=[bm.get("class_reasons"), cm.get("class_reasons")],
        placements=[len(kb), len(kc)], lost_keys=len(kb - kc), new_keys=len(kc - kb),
        lost_examples=[list(k) for k in list(kb - kc)[:5]], new_examples=[list(k) for k in list(kc - kb)[:5]],
        approx=[appx(nb), appx(nc)], builders=[dict(nb), dict(nc)], transitions=dict(trans),
        exact_to_other=sum(v for k, v in trans.items() if k.startswith("exact_brep ->")),
        moved=len(moved), moved_examples=[[list(k), d] for k, d in moved[:5]],
        new_exact_labels=dict(label_changes.most_common(6)),
        readback=[{k: rbk.get(k) for k in ("top_level_shapes", "solids", "valid", "invalid", "load_errors")},
                  {k: rck.get(k) for k in ("top_level_shapes", "solids", "valid", "invalid", "load_errors")}],
        invalid_names=[rbk.get("invalid_names", [])[:10], rck.get("invalid_names", [])[:10]],
        steel=[bm.get("weight_check", {}).get("ratio"), cm.get("weight_check", {}).get("ratio")],
        by_family=[{k: v.get("ratio") for k, v in (bm.get("weight_check", {}).get("by_family") or {}).items()},
                   {k: v.get("ratio") for k, v in (cm.get("weight_check", {}).get("by_family") or {}).items()}],
        counts=[bm.get("counts"), cm.get("counts")],
        standins=[bm.get("standins", {}).get("by_type"), cm.get("standins", {}).get("by_type")],
        skipped=[bm.get("skipped", {}).get("total"), cm.get("skipped", {}).get("total")],
        brep_repairs={k: (v if not isinstance(v, dict) else {kk: vv for kk, vv in v.items() if kk != "parts"})
                      for k, v in (cm.get("brep_repairs") or {}).items() if k != "note"},
        identity_parts=((cm.get("brep_repairs") or {}).get("weight_unvalidated") or {}).get("parts", [])[:40],
        negwt_parts=((cm.get("brep_repairs") or {}).get("negative_weight") or {}).get("parts", [])[:20],
        log_class=[b["log_class"], c["log_class"]])
json.dump(out, open(sys.argv[4] if len(sys.argv) > 4 else "cmp.json", "w"), indent=1, default=str)
for j, r in out.items():
    if r.get("incomplete"): print(j, "incomplete"); continue
    print(f'{r["version"]} {j[:40]:40} cls {r["cls"]} approx {r["approx"]} plc {r["placements"]} lost {r["lost_keys"]} new {r["new_keys"]} '
          f'ex->x {r["exact_to_other"]} moved {r["moved"]} rb {r["readback"][0].get("valid")}/{r["readback"][0].get("top_level_shapes")} -> '
          f'{r["readback"][1].get("valid")}/{r["readback"][1].get("top_level_shapes")} steel {r["steel"]} wall {r["wall"]} rc {r["rc"]}')
