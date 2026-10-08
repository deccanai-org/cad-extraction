#!/usr/bin/env python3
"""CAD-PDF PII redaction TRIAL — local only. Reads trial/in, writes trial/out, trial/compare, trial/work.
usage: run.py --models qwen/qwen3.8-max-prime [--models other] [--only s01 s02] [--tag pass1]
"""
import argparse
import io
import json
import os
import shutil
import sys
import time
import traceback
from multiprocessing import Pool

import fitz

T = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, T)
from cadpii import detect as D  # noqa: E402
from cadpii import redact as R  # noqa: E402
from cadpii import verify as V  # noqa: E402
from cadpii.read import PageModel, all_layers_on, to_d  # noqa: E402


def side_by_side(src, out, zones_by_page, path, dpi=110):
    from PIL import Image
    a, b = fitz.open(src), fitz.open(out)
    ims = []
    for pno, zones in zones_by_page.items():
        for z in zones[:2]:
            z = fitz.Rect(z) + (-6, -6, 6, 6)
            d = min(dpi, 2600 * 72 / max(z.width, z.height))
            M = fitz.Matrix(d / 72, d / 72)
            pa = a[pno].get_pixmap(matrix=M, clip=z & a[pno].rect, alpha=False)
            pb = b[pno].get_pixmap(matrix=M, clip=z & b[pno].rect, alpha=False)
            ia = Image.open(io.BytesIO(pa.tobytes("png"))).convert("RGB")
            ib = Image.open(io.BytesIO(pb.tobytes("png"))).convert("RGB")
            if z.height > z.width * 1.3:   # tall strip: put before|after side by side
                im = Image.new("RGB", (ia.width * 2 + 20, ia.height), (255, 0, 0))
                im.paste(ia, (0, 0)); im.paste(ib, (ia.width + 20, 0))
            else:                           # wide block: before above after
                im = Image.new("RGB", (ia.width, ia.height * 2 + 20), (255, 0, 0))
                im.paste(ia, (0, 0)); im.paste(ib, (0, ia.height + 20))
            ims.append(im)
    if not ims:
        return
    W = max(i.width for i in ims); H = sum(i.height for i in ims) + 20 * (len(ims) - 1)
    canvas = Image.new("RGB", (W, H), (255, 255, 255))
    y = 0
    for i in ims:
        canvas.paste(i, (0, y)); y += i.height + 20
    canvas.save(path)


def thumbs(src, out, path, px=900):
    from PIL import Image
    a, b = fitz.open(src), fitz.open(out)
    p = a[0]
    d = px * 72 / max(p.rect.width, p.rect.height)
    M = fitz.Matrix(d / 72, d / 72)
    ia = Image.open(io.BytesIO(a[0].get_pixmap(matrix=M, alpha=False).tobytes("png"))).convert("RGB")
    ib = Image.open(io.BytesIO(b[0].get_pixmap(matrix=M, alpha=False).tobytes("png"))).convert("RGB")
    im = Image.new("RGB", (ia.width * 2 + 16, ia.height), (255, 0, 0))
    im.paste(ia, (0, 0)); im.paste(ib, (ia.width + 16, 0))
    im.save(path)


def prepare(sample):
    """Read + packets (cached in work/packets/<id>/)."""
    src = os.path.join(T, "in", sample["file"])
    pdir = os.path.join(T, "work", "packets", sample["id"])
    os.makedirs(pdir, exist_ok=True)
    doc = all_layers_on(fitz.open(src))
    pages = []
    for pno in range(doc.page_count):
        t0 = time.time()
        pm = PageModel(doc, pno)
        rx = D.regex_hits(pm.words)
        pk = D.build_packet(pm, doc, rx)
        tiles = pm.zone_tiles()
        for k, t in enumerate(tiles):
            open(os.path.join(pdir, f"p{pno}_tile{k}.png"), "wb").write(t["png"])
        pages.append((pm, rx, pk, tiles, time.time() - t0))
    return doc, pages


def process(args):
    sample, models, tag = args
    try:
        return _process(sample, models, tag)
    except Exception:
        return {"id": sample["id"], "error": traceback.format_exc()}


def _process(sample, models, tag):
    t_start = time.time()
    src = os.path.join(T, "in", sample["file"])
    out = os.path.join(T, "out", sample["file"])
    ctl = os.path.join(T, "work", "control", sample["file"])
    os.makedirs(os.path.dirname(ctl), exist_ok=True)
    rdoc, pages = prepare(sample)
    md = rdoc.metadata or {}
    rec = {"id": sample["id"], "file": sample["file"], "disk": sample["disk"], "key": sample["key"],
           "producer": md.get("producer", ""), "creator": md.get("creator", ""), "pages": rdoc.page_count,
           "models": models, "llm": [], "pagesinfo": []}
    page_boxes, values, short_values = {}, [], []
    blank_meta, blank_ann = set(), set()
    zones_by_page = {}
    for pno, (pm, rx, pk, tiles, t_read) in enumerate(pages):
        json.dump({"text": pk["text"], "zone_ids": pk["zone_ids"], "extra_ids": pk["extra_ids"], "vis_ids": pk["vis_ids"],
                   "meta": pk["meta"], "ann": {k: v for k, v in pk["ann"].items()}, "n_tiles": len(tiles),
                   "words": [w.as_dict() for w in pm.words]},
                  open(os.path.join(T, "work", "packets", sample["id"], f"p{pno}_packet.json"), "w"))
        groups, vis, metas, anns = [], [], [], []
        for m in models:
            res = D.run_llm(pm, rdoc, pk, m, tiles, tag=f"{tag}:{sample['id']}:p{pno}")
            pr = D.parse_llm(res, pk, pm)
            rec["llm"].append({"model": res.get("model", m), "requested_model": m, "fallback_from": res.get("fallback_from"),
                               "first_error": res.get("first_error"), "page": pno, "latency_s": res.get("latency_s"), "cost": res.get("cost"),
                               "prompt_tokens": res.get("prompt_tokens"), "completion_tokens": res.get("completion_tokens"),
                               "provider": res.get("provider"), "error": res.get("error"), "invalid_ids": pr["invalid"],
                               "total_ids": pr["total_ids"], "parsed_ok": pr["parsed_ok"], "missed": pr["missed"],
                               "groups": pr["groups"], "visual": pr["visual"], "meta": pr["meta"], "ann": pr["ann"]})
            json.dump(res, open(os.path.join(T, "work", "packets", sample["id"], f"p{pno}_{tag}_{m.replace('/', '_')}.json"), "w"))
            groups += [dict(g, rule="llm:" + m) for g in pr["groups"]]
            vis += pr["visual"]; metas += pr["meta"]; anns += pr["ann"]
        learned = [(g["cat"], " ".join(pm.words[i].text for i in g["ids"])) for g in groups]
        learned += [(h["cat"], h["text"]) for h in rx]
        # split learned multi-line groups into per-line values for propagation
        prop = D.propagate(pm, learned)
        findings = rx + groups + prop
        boxes = R.build_boxes(pm, findings)
        seen = set()
        vb = []
        for v in vis:
            if v["id"] not in seen:
                seen.add(v["id"]); vb.append(v)
        boxes += R.visual_boxes(pm, vb)
        page_boxes[pno] = boxes
        zones_by_page[pno] = [list(z) for z in pm.zones]
        for b in boxes:
            if b["src"] == "visual":
                continue
            (values if len(D.normtok(b["text"])) >= 4 else short_values).append(b["text"])
        for h in rx:
            values.append(h["text"])
        # metadata decisions
        for mid, (k, v) in pk["meta"].items():
            flagged = any(m["id"] == mid for m in metas)
            rxhit = bool(D.regex_text(v))
            learned_hit = any(len(D.normtok(t)) >= 4 and D.normtok(t) in D.normtok(v) for _, t in learned)
            if k == "author" or flagged or rxhit or learned_hit:
                if k in ("creator", "producer") and not (flagged or rxhit):
                    continue
                blank_meta.add(k)
                values.append(v)
        for aid, (x, t) in pk["ann"].items():
            if any(a["id"] == aid for a in anns) or D.regex_text(t) or any(
                    len(D.normtok(v)) >= 4 and D.normtok(v) in D.normtok(t) for _, v in learned):
                blank_ann.add(x)
        for b in boxes:
            for i in b["ids"]:
                if pm.words[i].kind == "shx" and pm.words[i].xref:
                    blank_ann.add(pm.words[i].xref)
        rec["pagesinfo"].append({"page": pno, "tb_kind": pm.tb_kind, "zones": zones_by_page[pno], "n_words": len(pm.words),
                                 "word_kinds": dict(__import__("collections").Counter(w.kind for w in pm.words)),
                                 "raster": pm.raster, "ocr": pm.ocr_done, "n_vis": len(pm.vis), "read_s": round(t_read, 1),
                                 "n_regex": len(rx), "n_prop": len(prop),
                                 "boxes": [{"rect_u": [round(v, 2) for v in b["rect_u"]], "mode": b["mode"], "img": b["img"],
                                            "cat": b["cat"], "src": b["src"], "text": b["text"], "kinds": b["kinds"],
                                            "ids": b["ids"]}
                                           for b in boxes]})
    rdoc.close()
    # ---------------- redact (fresh doc: OCG config untouched)
    doc = fitz.open(src)
    for pno, boxes in page_boxes.items():
        R.apply_boxes(doc[pno], boxes)
    ann_changes = sum(R.edit_annots(doc, doc[p], blank_ann) for p in range(doc.page_count))
    meta_changes = R.edit_metadata(doc, sorted(blank_meta), values)
    R.save(doc, out)
    doc.close()
    # ---------------- negative control: cosmetic rectangles only
    cdoc = fitz.open(src)
    for pno, boxes in page_boxes.items():
        R.apply_boxes(cdoc[pno], boxes, cosmetic=True)
    cdoc.save(ctl, garbage=3, deflate=True, clean=False)
    cdoc.close()
    # ---------------- verify
    rec["metadata_blanked"] = sorted(blank_meta)
    rec["meta_changes"] = meta_changes
    rec["annot_authors_blanked"] = ann_changes
    rec["annot_contents_blanked"] = len(blank_ann)
    rec["verify_removed"] = V.removal_checks(out, page_boxes, values, short_values)
    rec["verify_control"] = V.removal_checks(ctl, page_boxes, values, short_values)
    selected = {pno: {i for b in bx for i in b["ids"]} for pno, bx in page_boxes.items()}
    rec["verify_collateral"] = V.collateral_checks(src, out, page_boxes, selected=selected)
    rec["control_fails_as_expected"] = not rec["verify_control"]["removed_ok"]
    # ---------------- compare folder
    cdir = os.path.join(T, "compare", sample["file"][:-4])
    os.makedirs(cdir, exist_ok=True)
    shutil.copy(src, os.path.join(cdir, "before.pdf"))
    shutil.copy(out, os.path.join(cdir, "after.pdf"))
    side_by_side(src, out, zones_by_page, os.path.join(cdir, "titleblock_before_after.png"))
    thumbs(src, out, os.path.join(cdir, "page_before_after.png"))
    rec["seconds"] = round(time.time() - t_start, 1)
    json.dump(rec, open(os.path.join(T, "work", "results", sample["id"] + ".json"), "w"), indent=1, default=str)
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", action="append", default=[])
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--tag", default="pass1")
    ap.add_argument("--procs", type=int, default=6)
    a = ap.parse_args()
    os.makedirs(os.path.join(T, "work", "results"), exist_ok=True)
    S = json.load(open(os.path.join(T, "samples.json")))
    if a.only:
        S = [s for s in S if s["id"] in a.only]
    # OCR-heavy samples first so they overlap with the LLM-bound ones
    S.sort(key=lambda s: s["id"] not in ("s01", "s04", "s18", "s11"))
    with Pool(a.procs) as pool:
        for rec in pool.imap_unordered(process, [(s, a.models, a.tag) for s in S]):
            if rec.get("error"):
                print(rec["id"], "ERROR", rec["error"][-1500:], flush=True)
                continue
            vr, vc, cc = rec["verify_removed"], rec["verify_collateral"], rec["verify_control"]
            nb = sum(len(p["boxes"]) for p in rec["pagesinfo"])
            cost = sum((x.get("cost") or 0) for x in rec["llm"])
            print(f"{rec['id']} boxes={nb:3d} removed_ok={vr['removed_ok']} collateral_ok={vc['collateral_ok']} "
                  f"control_fails={rec['control_fails_as_expected']} glyphs={vr['glyphs_in_boxes']} rx={vr['regex_hits_remaining']} "
                  f"vals={len(vr['values_remaining'])} pix={vr['pixel_residual_boxes']} strokes={vr['stroke_residual_boxes']} "
                  f"| wmiss={vc['words_missing_outside']} wadd={vc['words_added']} dmiss={vc['drawings_missing_outside']} "
                  f"dextra={vc['drawings_extra_outside']} px={vc['render_px_changed_outside']} imgs={vc['images_equal']} "
                  f"| ${cost:.3f} {rec['seconds']}s", flush=True)


if __name__ == "__main__":
    main()
