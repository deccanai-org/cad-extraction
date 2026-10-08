#!/usr/bin/env python3
"""Re-run verification (and the cosmetic control) from saved results without new LLM calls."""
import json, os, sys, glob
import fitz
T = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, T)
from cadpii import verify as V, redact as R
from cadpii.detect import normtok
for f in sorted(glob.glob(os.path.join(T, "work", "results", "s*.json"))):
    r = json.load(open(f))
    if len(sys.argv) > 1 and r["id"] not in sys.argv[1:]:
        continue
    src = os.path.join(T, "in", r["file"]); out = os.path.join(T, "out", r["file"]); ctl = os.path.join(T, "work", "control", r["file"])
    pb = {p["page"]: [dict(b, rect_u=fitz.Rect(b["rect_u"]), ids=b.get("ids", [])) for b in p["boxes"]] for p in r["pagesinfo"]}
    vals = [b["text"] for p in pb.values() for b in p if b["src"] != "visual" and len(normtok(b["text"])) >= 4]
    shorts = [b["text"] for p in pb.values() for b in p if b["src"] != "visual" and len(normtok(b["text"])) < 4]
    vals += r.get("meta_values", [])
    c = fitz.open(src)
    for pno, boxes in pb.items():
        R.apply_boxes(c[pno], boxes, cosmetic=True)
    c.save(ctl, garbage=3, deflate=True, clean=False); c.close()
    r["verify_removed"] = V.removal_checks(out, pb, vals, shorts)
    r["verify_control"] = V.removal_checks(ctl, pb, vals, shorts)
    r["verify_collateral"] = V.collateral_checks(src, out, pb, selected={k: {i for b in v for i in b["ids"]} for k, v in pb.items()})
    r["control_fails_as_expected"] = not r["verify_control"]["removed_ok"]
    json.dump(r, open(f, "w"), indent=1, default=str)
    vr, vc = r["verify_removed"], r["verify_collateral"]
    print(r["id"], "removed", vr["removed_ok"], "coll", vc["collateral_ok"], "ctl_fails", r["control_fails_as_expected"],
          "glyph", vr["glyphs_in_boxes"], "rx", vr["regex_hits_remaining"], "vals", len(vr["values_remaining"]), "pix", vr["pixel_residual_boxes"],
          "strk", vr["stroke_residual_boxes"], "| wm", vc["words_missing_outside"], "wa", vc["words_added"], "dm", vc["drawings_missing_outside"],
          "dx", vc["drawings_extra_outside"], "px", vc["render_px_changed_outside"], "img", vc["images_equal"], vc.get("images_removed_inside_boxes"), flush=True)
