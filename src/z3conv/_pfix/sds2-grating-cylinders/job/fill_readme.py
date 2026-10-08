#!/usr/bin/env python3
"""fill_readme.py: README.tmpl.md + data/gr4f + data/conv/cmp_*.json -> README.md"""
import json, glob, os, re, collections
os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/..")
NAMES = {"1504_EQUADOR_f90185": "1504 EQUADOR", "1510_-_LAREDO_CONVENT_JOB_ce9a53": "1510 LAREDO CONVENT",
         "18011_PNW_Freezer_J_438d3c": "18011 PNW Freezer", "DSCC_JOB_ef345b": "DSCC",
         "F35_FLIGHT_SIMULATION_TEMP_70dbbe": "F35 FLIGHT SIM", "One_Light_Tower_JOB_-Model_700bd1": "One Light Tower",
         "PSU_BNR_JOB_mallesh_4e9908": "PSU BNR", "SHERIFFS_OFFICE_JOB_e730aa": "SHERIFFS OFFICE",
         "SLC4_DATABANK_JOB_2d968e": "SLC4 DATABANK", "TEMP_Wayne_Farms_Job_61d687": "TEMP Wayne Farms",
         "UOM_Union_bldg_Job_040519_633e54": "UOM Union", "FMI_SAFFORD_SULFUR_TANK_JOB_948ebd": "FMI SAFFORD",
         "1530_-_Forsyth_County_Job_7d138e": "1530 Forsyth County", "CLAYTON_JOB_075ea0": "CLAYTON",
         "SUSQUEHANNOCK_HS_JOB_87316d": "SUSQUEHANNOCK HS", "TEMP_JOB_RGK_3adae7": "TEMP JOB RGK",
         "THERMOFISHER_JOB_bff8f8": "THERMOFISHER", "VALLEY_GROVE_1_JOB_b70519": "VALLEY GROVE 1"}
def nm(j): return NAMES.get(j, j)
def short_why(w):
    w = re.sub(r"built grating ([\d.]+)x SDS2's weight \(outside 1 \+- 0.03, not a cut of its W x L stock(: [^)]*)?\)",
               lambda m: "weight " + ("high" if float(m.group(1)) > 1 else "low") + (m.group(2) or "").replace(": ", ", "), w)
    return w
rows = ["| job | SDS2 | grating pieces | built: exact weight / cut panel | not built (reason: pieces) | placements built | built / SDS2 lb (uncut) | cross bars |",
        "|---|---|---:|---|---|---:|---|---:|"]
T = collections.Counter()
for f in sorted(glob.glob("data/gr4f/*.json")):
    d = json.load(open(f)); P = d["pieces"]; j = os.path.basename(f)[:-5]
    ok = [p for p in P if p.get("ok")]; cut = [p for p in ok if p.get("cut_from_stock")]
    why = collections.Counter(short_why(p.get("why", "?")) for p in P if not p.get("ok"))
    r = [p["weight_ratio"] for p in ok if not p.get("cut_from_stock") and p.get("weight_ratio")]
    pl, plok = sum(p["placed"] for p in P), sum(p["placed"] for p in ok)
    rows.append(f"| {nm(j)} | {d['version']} | {len(P)} | {len(ok) - len(cut)} / {len(cut)} | "
                f"{'; '.join(f'{w}: {c}' for w, c in why.most_common()) or '-'} | {plok} / {pl} | "
                f"{(f'{min(r):.3f}-{max(r):.3f}' if r else '-')} | {sum(p.get('cross_bars', 0) for p in ok):,} |")
    T["p"] += len(P); T["ok"] += len(ok); T["cut"] += len(cut); T["pl"] += pl; T["plok"] += plok
    T["cb"] += sum(p.get("cross_bars", 0) for p in ok)
rows.append(f"| **total** | | **{T['p']}** | **{T['ok'] - T['cut']} / {T['cut']}** | {T['p'] - T['ok']} | **{T['plok']:,} / {T['pl']:,}** | | {T['cb']:,} |")
t1 = "\n".join(rows)
def conv_table(fn, note):
    if not os.path.exists(fn):
        return "(pending)"
    R = json.load(open(fn))
    vb, vn = re.match(r".*cmp_(\w+?)_(\w+)\.json", fn).groups()
    sizes = {}
    if os.path.exists("data/conv/step_sizes.txt"):
        for l in open("data/conv/step_sizes.txt"):
            if len(l.split()) != 3: continue
            v, j, b = l.split()
            if b.isdigit(): sizes[(v, j)] = int(b) / 1e6
    def wall(rc):
        m = re.search(r"wall=(\d+)", rc or ""); c = re.search(r"rc=(\d+)", rc or "")
        return (m.group(1) + ("" if c and c.group(1) == "0" else f" (rc {c.group(1)})")) if m else "-"
    def mb(v, j):
        return f"{sizes[(v, j)]:,.0f}" if (v, j) in sizes else "-"
    out = ["| job | class | mesh_cylinder stand-ins | grating stand-ins | exact pieces | stand-ins total | skipped | read-back solids / valid | steel ratio | wall s | STEP MB |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in R:
        a, b = (r["rc"].split(" | ") + [""])[:2]
        out.append(f"| {nm(r['job'])} | {r['cls']} | {r['mesh_cyl']} | {r['grating']} | {r['exact']} | {r['standins']} | "
                   f"{r['skipped']} | {r['readback']} | {r['steel']} | {wall(a)} -> {wall(b)} | "
                   f"{mb(vb, r['job'])} -> {mb(vn, r['job'])} |")
    return "\n".join(out) + ("\n\n" + note if note else "")
tm = open("job/README.tmpl.md").read()
n3 = open("data/conv/note_v54.md").read().strip() if os.path.exists("data/conv/note_v54.md") else ""
n4 = open("data/conv/note_v553.md").read().strip() if os.path.exists("data/conv/note_v553.md") else ""
tm = tm.replace("__T1__", t1).replace("__T3__", conv_table("data/conv/cmp_base54_v55.json", n3)) \
       .replace("__T4__", conv_table("data/conv/cmp_v553_v553h.json", n4))
open("README.md", "w").write(tm)
print("README.md written")
