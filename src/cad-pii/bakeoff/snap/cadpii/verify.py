"""Verification: PII removed + nothing lost (collateral) + negative control."""
import re
from collections import Counter

import fitz
import numpy as np

from .detect import RX, regex_text, normtok
from .read import all_layers_on


def _boxes(boxes, pad=0.0):
    return [fitz.Rect(b["rect_u"]) + (-pad, -pad, pad, pad) for b in boxes]


def _ov(r, b):
    """closed-interval overlap: works for zero-width / zero-height rects (pure H/V lines)."""
    return r.x0 <= b.x1 and r.x1 >= b.x0 and r.y0 <= b.y1 and r.y1 >= b.y0


def _hit(r, boxes):
    return any(_ov(r, b) for b in boxes)


def _norm(s):
    return re.sub(r"[^A-Z0-9@]", "", (s or "").upper())


def _img_std_in_box(doc, page, box):
    best, seen = 0.0, False
    for im in page.get_image_info(xrefs=True):
        pr = fitz.Rect(im["bbox"])
        inter = box & pr
        if inter.is_empty or inter.width < 1 or inter.height < 1 or not im.get("xref"):
            continue
        try:
            pix = fitz.Pixmap(doc, im["xref"])
            if pix.n - pix.alpha > 3 or pix.colorspace is None or pix.colorspace.n not in (1, 3):
                pix = fitz.Pixmap(fitz.csRGB, pix)
            a = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w, pix.n)
        except Exception:
            continue
        # exact mapping: page point -> image unit square via the inverse placement matrix
        M = fitz.Matrix(im.get("transform") or (pr.width, 0, 0, pr.height, pr.x0, pr.y0))
        try:
            Mi = ~M
        except Exception:
            continue
        us, vs = [], []
        for q in (inter.tl, inter.tr, inter.bl, inter.br):
            pt = fitz.Point(q) * Mi
            us.append(pt.x); vs.append(pt.y)
        W, H = pix.w, pix.h
        x0, x1 = int(max(0, min(us)) * W), int(min(1, max(us)) * W)
        y0, y1 = int(max(0, min(vs)) * H), int(min(1, max(vs)) * H)
        x1, y1 = max(x1, x0 + 1), max(y1, y0 + 1)
        sub = a[max(y0, 0):y1, max(x0, 0):x1, :min(3, a.shape[2])]
        # shrink by 15% each side to stay off the box edge
        if sub.shape[0] > 6 and sub.shape[1] > 6:
            dy, dx = int(sub.shape[0] * 0.15), int(sub.shape[1] * 0.15)
            sub = sub[dy:sub.shape[0] - dy, dx:sub.shape[1] - dx]
        if sub.size == 0:
            continue
        seen = True
        best = max(best, float(sub.std()))
    return best, seen


def _stroke_residual(page, box, fill_rects):
    """Line-art segments with both endpoints inside the (shrunk) box, excluding our own black fills."""
    inner = fitz.Rect(box) + (1.2, 1.2, -1.2, -1.2)
    if inner.is_empty:
        return 0
    n = 0
    for p in page.get_cdrawings():
        r = fitz.Rect(p["rect"])
        if not _ov(r, inner):
            continue
        if p.get("type") == "f" and p.get("fill") in ((0.0, 0.0, 0.0), (0, 0, 0)) and any(abs(r.x0 - f.x0) < 0.6 and abs(r.y1 - f.y1) < 0.6 for f in fill_rects):
            continue
        for it in p["items"]:
            pts = []
            if it[0] == "l":
                pts = [it[1], it[2]]
            elif it[0] == "c":
                pts = [it[1], it[4]]
            if len(pts) == 2 and all(inner.contains(fitz.Point(q)) for q in pts):
                n += 1
    return n


def removal_checks(out_path, page_boxes, values, short_values):
    """page_boxes: {pno: [box]}. values: strings that must be gone. -> dict"""
    doc = all_layers_on(fitz.open(out_path))
    res = {"glyphs_in_boxes": 0, "regex_hits_remaining": 0, "values_remaining": [], "pixel_residual_boxes": 0,
           "stroke_residual_boxes": 0, "boxes": 0, "text_layer_words": 0, "regex_examples": []}
    alltext = ""
    for pno in range(doc.page_count):
        page = doc[pno]
        bx = page_boxes.get(pno, [])
        res["boxes"] += len(bx)
        rects = _boxes(bx, -0.3)
        raw = page.get_text("rawdict")
        chars = []
        for b in raw["blocks"]:
            for l in b.get("lines", []):
                for s in l["spans"]:
                    for c in s["chars"]:
                        chars.append(c)
        for c in chars:
            cr = fitz.Rect(c["bbox"])
            ctr = fitz.Point((cr.x0 + cr.x1) / 2, (cr.y0 + cr.y1) / 2)
            if c["c"].strip() and any(r.contains(ctr) for r in rects):
                res["glyphs_in_boxes"] += 1
        words = page.get_text("words")
        res["text_layer_words"] += len(words)
        txt = page.get_text()
        alltext += txt
        lines = {}
        for w in words:
            lines.setdefault((w[5], w[6]), []).append(w[4])
        for ln in lines.values():
            for cat, m in regex_text(" ".join(ln)):
                res["regex_hits_remaining"] += 1
                if len(res["regex_examples"]) < 5:
                    res["regex_examples"].append((cat, m))
        fills = [fitz.Rect(b["rect_u"]) for b in bx]
        for b in bx:
            r = fitz.Rect(b["rect_u"])
            if b.get("img"):
                std, seen = _img_std_in_box(doc, page, r)
                if seen and std > 12:
                    res["pixel_residual_boxes"] += 1
            if b["mode"] == "C":
                if _stroke_residual(page, r, fills) > 0:
                    res["stroke_residual_boxes"] += 1
        # values on the page as exact tokens (short ones) checked only inside zones by caller
    md = doc.metadata or {}
    meta_blob = " ".join(str(v) for v in md.values()) + " " + (doc.get_xml_metadata() or "")
    ann_blob = ""
    for p in doc:
        for a in p.annots() or []:
            ann_blob += " " + (a.info.get("title") or "") + " " + (a.info.get("content") or "")
    nt, nm, na = _norm(alltext), _norm(meta_blob), _norm(ann_blob)
    for v in sorted(set(values)):
        nv = _norm(v)
        if len(nv) < 4:
            continue
        where = [k for k, blob in (("page", nt), ("meta", nm), ("annot", na)) if nv in blob]
        if where:
            res["values_remaining"].append({"len": len(v), "where": where, "value": v})
    toks = Counter(normtok(w) for p in doc for w in (x[4] for x in p.get_text("words")))
    res["short_values_remaining"] = [v for v in sorted(set(short_values)) if toks.get(normtok(v))]
    doc.close()
    res["removed_ok"] = (res["glyphs_in_boxes"] == 0 and res["regex_hits_remaining"] == 0 and
                         not res["values_remaining"] and res["pixel_residual_boxes"] == 0 and
                         res["stroke_residual_boxes"] == 0)
    return res


def _snap(path, layers_on=True):
    doc = fitz.open(path)
    if layers_on:
        all_layers_on(doc)
    pages = []
    for p in doc:
        words = [(w[4], fitz.Rect(w[:4])) for w in p.get_text("words")]
        dr = []   # segment level: (kind, rounded points, type, colour, fill, width)
        for d in p.get_cdrawings():
            props = (d.get("type"), tuple(round(c, 2) for c in (d.get("color") or ())),
                     tuple(round(c, 2) for c in (d.get("fill") or ())), round(d.get("width") or 0, 2))
            for it in d["items"]:
                if it[0] == "re":
                    rr = fitz.Rect(it[1]); pts = (rr.tl, rr.br)
                elif it[0] == "qu":
                    pts = tuple(it[1])
                else:
                    pts = it[1:]
                pts = tuple((round(fitz.Point(q).x, 1), round(fitz.Point(q).y, 1)) for q in pts)
                xs = [q[0] for q in pts]; ys = [q[1] for q in pts]
                dr.append(((min(xs), min(ys), max(xs), max(ys)), it[0], pts) + props)
        imgs = sorted((im["width"], im["height"], tuple(round(v, 1) for v in im["bbox"])) for im in p.get_image_info())
        ann = Counter(a.type[1] for a in p.annots() or [])
        pages.append({"words": words, "dr": dr, "imgs": imgs, "ann": ann, "rot": p.rotation,
                      "nimg": len(p.get_images(full=True)), "widgets": len(list(p.widgets() or []))})
    info = {"pages": pages, "n": doc.page_count, "ocgs": doc.get_ocgs(), "toc": len(doc.get_toc()),
            "emb": doc.embfile_count(), "layer_ui": len(doc.layer_ui_configs() or [])}
    doc.close()
    return info


def _render(path, dpi=60):
    doc = fitz.open(path)
    out = []
    for p in doc:
        pix = p.get_pixmap(dpi=dpi, alpha=False, annots=True)
        out.append((np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w, pix.n).astype(np.int16),
                    p.rotation_matrix, p.rect))
    doc.close()
    return out


def collateral_checks(src, out, page_boxes, pad=1.0):
    A, B = _snap(src), _snap(out)
    res = {}
    res["pages_equal"] = A["n"] == B["n"]
    res["rotation_equal"] = [p["rot"] for p in A["pages"]] == [p["rot"] for p in B["pages"]]
    res["annots_equal"] = [p["ann"] for p in A["pages"]] == [p["ann"] for p in B["pages"]]
    res["ocgs_equal"] = A["ocgs"] == B["ocgs"]
    res["toc_equal"] = A["toc"] == B["toc"]
    res["embedded_equal"] = A["emb"] == B["emb"]
    res["widgets_equal"] = [p["widgets"] for p in A["pages"]] == [p["widgets"] for p in B["pages"]]
    img_ok, img_removed = True, 0
    for pno, (a, b) in enumerate(zip(A["pages"], B["pages"])):
        bx = _boxes(page_boxes.get(pno, []), 1.0)
        # an image placement lying entirely inside a redaction box is an expected removal (logo / seal)
        ka = [im for im in a["imgs"] if not any(fitz.Rect(bb).contains(fitz.Rect(im[2])) for bb in bx)]
        kb = [im for im in b["imgs"] if not any(fitz.Rect(bb).contains(fitz.Rect(im[2])) for bb in bx)]
        img_removed += len(a["imgs"]) - len(b["imgs"])
        if [(w, h) for w, h, _ in ka] != [(w, h) for w, h, _ in kb]:
            img_ok = False
    res["images_equal"] = img_ok
    res["images_removed_inside_boxes"] = img_removed
    miss_w = added_w = miss_d = extra_d = 0
    examples = []
    for pno, (a, b) in enumerate(zip(A["pages"], B["pages"])):
        bx = _boxes(page_boxes.get(pno, []), pad)
        # (a) words outside boxes still present (text + position), and nothing new appears
        outw = [(t, r) for t, r in b["words"]]
        idx = Counter((t, round(r.x0), round(r.y0)) for t, r in outw)
        for t, r in a["words"]:
            if _hit(r, bx):
                continue
            k = (t, round(r.x0), round(r.y0))
            if idx.get(k, 0) > 0:
                idx[k] -= 1
            else:
                # tolerate 1-unit rounding jitter
                alt = [kk for kk in idx if kk[0] == t and abs(kk[1] - k[1]) <= 1 and abs(kk[2] - k[2]) <= 1 and idx[kk] > 0]
                if alt:
                    idx[alt[0]] -= 1
                else:
                    miss_w += 1
                    if len(examples) < 5:
                        examples.append(("missing_word", t))
        srcset = Counter((t, round(r.x0), round(r.y0)) for t, r in a["words"])
        for t, r in outw:
            if _hit(r, bx):
                continue   # remnant of a partly redacted word, inside a box
            k = (t, round(r.x0), round(r.y0))
            if not any(kk[0] == t and abs(kk[1] - k[1]) <= 1 and abs(kk[2] - k[2]) <= 1 for kk in srcset):
                added_w += 1
                if len(examples) < 8:
                    examples.append(("added_word", t))
        # (b) drawings outside boxes unchanged (multiset of rounded rect/type/colour/width/items)
        da = Counter(d for d in a["dr"] if not _hit(fitz.Rect(d[0]), bx))
        db = Counter(d for d in b["dr"] if not _hit(fitz.Rect(d[0]), bx))
        miss_d += sum((da - db).values())
        extra_d += sum((db - da).values())
        if (da - db) and len(examples) < 10:
            examples.append(("missing_drawing", list((da - db).keys())[:2]))
        if (db - da) and len(examples) < 12:
            examples.append(("extra_drawing", list((db - da).keys())[:2]))
    res["words_missing_outside"] = miss_w
    res["words_added"] = added_w
    res["drawings_missing_outside"] = miss_d
    res["drawings_extra_outside"] = extra_d
    # (c) 60 dpi render diff outside boxes dilated by 2 pt
    RA, RB = _render(src), _render(out)
    px_changed = px_any = 0
    for pno, ((ia, rm, prect), (ib, _, _)) in enumerate(zip(RA, RB)):
        if ia.shape != ib.shape:
            px_changed += ia.size
            continue
        z = ia.shape[1] / prect.width
        mask = np.zeros(ia.shape[:2], bool)
        for b in page_boxes.get(pno, []):
            d = (fitz.Rect(b["rect_u"]) * rm) + (-2, -2, 2, 2)
            x0, y0 = max(0, int(d.x0 * z) - 1), max(0, int(d.y0 * z) - 1)
            x1, y1 = int(d.x1 * z) + 2, int(d.y1 * z) + 2
            mask[y0:y1, x0:x1] = True
        diff = np.abs(ia - ib).max(axis=2)
        ch = (diff > 24) & ~mask
        if ch.any():
            ys, xs = np.nonzero(ch)
            res.setdefault("px_changed_bbox_pt", []).append([round(xs.min() / z), round(ys.min() / z), round(xs.max() / z), round(ys.max() / z)])
        px_changed += int(ch.sum())
        px_any += int(((diff > 0) & ~mask).sum())
    res["render_px_changed_outside"] = px_changed
    res["render_px_anydiff_outside"] = px_any
    res["examples"] = examples
    res["collateral_ok"] = (res["pages_equal"] and res["rotation_equal"] and res["annots_equal"] and res["ocgs_equal"]
                            and res["toc_equal"] and res["embedded_equal"] and res["widgets_equal"] and res["images_equal"]
                            and miss_w == 0 and added_w == 0 and miss_d == 0 and extra_d == 0 and px_changed == 0)
    return res
