"""Zero-loss redactor.

Rounds per page (apply_redactions options are per call, so boxes are grouped):
  A  text glyph boxes not touching an image   images=NONE   graphics=LINE_ART_NONE        text=REMOVE
  B  boxes touching an image (scan/OCR-layer)  images=PIXELS  graphics=LINE_ART_NONE        text=REMOVE
  C  stroke boxes (SHX/OCR-on-vector, vector   images=PIXELS* graphics=REMOVE_IF_COVERED   text=REMOVE
     logo/seal clusters)                       (*only if the box touches an image, else NONE)
REMOVE_IF_COVERED only deletes paths whose bbox lies entirely inside the box, so
nothing outside a box can change. Never rewrite_images, never delete widgets,
never scrub(), never set_toc([]), never clean=True.
"""
import re

import fitz

BLACK = (0, 0, 0)


def _clip_to_neighbours(word_rects, r, target):
    """(from the reference actions.py) padding must stop at the neighbouring line."""
    top, bot = r.y0, r.y1
    for wr in word_rects:
        if wr.x1 <= r.x0 or wr.x0 >= r.x1:
            continue
        if wr.y1 > target.y0 and wr.y0 < target.y1:
            continue
        if wr.y1 <= target.y0:
            top = max(top, min(wr.y1 + 0.05, target.y0))
        elif wr.y0 >= target.y1:
            bot = min(bot, max(wr.y0 - 0.05, target.y1))
    left, right = r.x0, r.x1
    for wr in word_rects:
        if wr.y1 <= r.y0 or wr.y0 >= r.y1:
            continue
        if wr.x1 > target.x0 and wr.x0 < target.x1:
            continue
        if wr.x1 <= target.x0:
            left = max(left, min(wr.x1 + 0.05, target.x0))
        elif wr.x0 >= target.x1:
            right = min(right, max(wr.x0 - 0.05, target.x1))
    if bot - top < 0.5 or right - left < 0.5:
        return fitz.Rect(target)
    return fitz.Rect(left, top, right, bot)


def trim_against(r, others, target, max_loss=0.45):
    """MuPDF removes any glyph whose bbox the redaction rect covers by more than ~10%, so a box
    must not overlap an unselected neighbour at all (tight CAD line spacing makes bboxes overlap
    by ~1 pt). For each overlapping neighbour cut the side that loses the least box area."""
    r = fitz.Rect(r)
    for _ in range(4):
        hit = None
        for o in others:
            if o.x0 < r.x1 - 0.01 and o.x1 > r.x0 + 0.01 and o.y0 < r.y1 - 0.01 and o.y1 > r.y0 + 0.01:
                hit = o
                break
        if hit is None:
            return r
        opts = [fitz.Rect(r.x0, max(r.y0, hit.y1 + 0.05), r.x1, r.y1),   # cut top
                fitz.Rect(r.x0, r.y0, r.x1, min(r.y1, hit.y0 - 0.05)),   # cut bottom
                fitz.Rect(max(r.x0, hit.x1 + 0.05), r.y0, r.x1, r.y1),   # cut left
                fitz.Rect(r.x0, r.y0, min(r.x1, hit.x0 - 0.05), r.y1)]   # cut right
        area = max(r.width * r.height, 1e-6)
        opts = [o_ for o_ in opts if not o_.is_empty and o_.width > 0.5 and o_.height > 0.5]
        if not opts:
            return r
        best = max(opts, key=lambda o_: o_.width * o_.height)
        if 1 - best.width * best.height / area > max_loss:
            return r      # would lose too much of the target: keep (verifier will report the neighbour)
        r = best
    return r


def build_boxes(pm, findings):
    """findings: [{cat, ids, text, rule}] + visuals -> [{rect_u, mode, cat, src, text}]
    Consecutive selected words on the same line are merged into one bar."""
    words = pm.words
    sel = {}
    for f in findings:
        for i in f.get("ids", []):
            sel.setdefault(i, f)
    # group by line, merge horizontally adjacent (displayed space)
    byline = {}
    for i, f in sel.items():
        w = words[i]
        byline.setdefault((w.line if w.line is not None else ("solo", i), w.kind), []).append(w)
    unsel_text = [w.u for w in words if w.i not in sel and w.kind == "text"]
    boxes = []
    for (ln, kind), ws in byline.items():
        vert = all(w.d.height > 1.5 * w.d.width for w in ws) and len(ws[0].text) > 1
        ws.sort(key=lambda w: (w.d.y0 if vert else w.d.x0))
        runs = [[ws[0]]]
        for w in ws[1:]:
            p = runs[-1][-1]
            gap = (w.d.y0 - p.d.y1) if vert else (w.d.x0 - p.d.x1)
            size = max(p.d.width, w.d.width) if vert else max(p.d.height, w.d.height)
            between = [x for x in words if x.i not in sel and x.line == ln and
                       ((p.d.y1 <= x.d.y0 <= w.d.y0) if vert else (p.d.x1 <= x.d.x0 <= w.d.x0))]
            if gap <= 1.6 * size and not between:
                runs[-1].append(w)
            else:
                runs.append([w])
        for run in runs:
            u = fitz.Rect(run[0].u) | run[0].ink
            for w in run[1:]:
                u |= w.u
                u |= w.ink
            f = sel[run[0].i]
            if kind == "text":
                pad = 0.6
            else:
                pad = 1.5
            r = fitz.Rect(u.x0 - pad, u.y0 - pad, u.x1 + pad, u.y1 + pad)
            if kind == "text":
                r = _clip_to_neighbours(unsel_text, r, u)
                r = trim_against(r, unsel_text, u)
            touches_img = any(im["u"].intersects(r) for im in pm.images)
            if kind == "text":
                mode = "B" if touches_img else "A"
            elif kind == "ocr_raster":
                mode = "B"
            else:
                mode = "C"
            boxes.append({"rect_u": r, "mode": mode, "img": touches_img, "cat": f["cat"], "src": f.get("rule", "llm"),
                          "text": " ".join(w.text for w in run), "ids": [w.i for w in run],
                          "kinds": sorted({w.kind for w in run})})
    return boxes


def visual_boxes(pm, picks):
    out = []
    byid = {v["id"]: v for v in pm.vis}
    for p in picks:
        v = byid.get(p["id"])
        if not v:
            continue
        r = fitz.Rect(v["u"]) + (-1, -1, 1, 1)
        inside, partial = [], []
        for w in pm.words:
            if w.kind != "text" or not w.u.intersects(r):
                continue
            inter = w.u & r
            frac = inter.width * inter.height / max(w.u.width * w.u.height, 1e-6)
            (inside if frac >= 0.25 else partial).append(w)
        for w in inside:
            r |= w.u      # seal / logo text that mostly sits in the graphic goes with it
        r = trim_against(r, [w.u for w in partial], r)
        touches_img = any(im["u"].intersects(r) for im in pm.images)
        out.append({"rect_u": r, "mode": "B" if v["kind"] == "image" else "C", "img": touches_img,
                    "cat": p.get("cat", "logo"), "src": "visual", "text": f"[{v['kind']} {v['id']}]",
                    "ids": [w.i for w in inside],
                    "kinds": [v["kind"]]})
    return out


def apply_boxes(page, boxes, cosmetic=False):
    if cosmetic:
        for b in boxes:
            page.draw_rect(b["rect_u"] * page.rotation_matrix if False else b["rect_u"], color=BLACK, fill=BLACK, overlay=True)
        return
    rounds = [
        ("A", dict(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE, text=fitz.PDF_REDACT_TEXT_REMOVE)),
        ("B", dict(images=fitz.PDF_REDACT_IMAGE_PIXELS, graphics=fitz.PDF_REDACT_LINE_ART_NONE, text=fitz.PDF_REDACT_TEXT_REMOVE)),
        ("C0", dict(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED, text=fitz.PDF_REDACT_TEXT_REMOVE)),
        ("C1", dict(images=fitz.PDF_REDACT_IMAGE_PIXELS, graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED, text=fitz.PDF_REDACT_TEXT_REMOVE)),
    ]
    for name, opts in rounds:
        sel = [b for b in boxes if (b["mode"] if b["mode"] != "C" else ("C1" if b["img"] else "C0")) == name]
        if not sel:
            continue
        for b in sel:
            page.add_redact_annot(b["rect_u"], fill=BLACK, cross_out=False)
        page.apply_redactions(**opts)


def _pdfstr(s):
    return fitz.get_pdf_str(s)


def edit_metadata(doc, blank_keys, values):
    """Per-key edits on the Info dict; XMP edited in place. Returns list of changes."""
    changes = []
    t, v = doc.xref_get_key(-1, "Info")
    if t == "xref":
        ix = int(v.split()[0])
        for k in blank_keys:
            kk = k[0].upper() + k[1:]
            tt, vv = doc.xref_get_key(ix, kk)
            if tt != "null":
                doc.xref_set_key(ix, kk, "()")
                changes.append(f"Info/{kk}")
    xmp = doc.get_xml_metadata() or ""
    if xmp:
        new = xmp
        new = re.sub(r"(<dc:creator>).*?(</dc:creator>)", r"\1<rdf:Seq><rdf:li></rdf:li></rdf:Seq>\2", new, flags=re.S)
        new = re.sub(r'(pdf:Author=")[^"]*(")', r"\1\2", new)
        new = re.sub(r"(<pdf:Author>).*?(</pdf:Author>)", r"\1\2", new, flags=re.S)
        for k in blank_keys:
            if k == "title":
                new = re.sub(r"(<dc:title>).*?(</dc:title>)", r"\1<rdf:Alt><rdf:li xml:lang=\"x-default\"></rdf:li></rdf:Alt>\2", new, flags=re.S)
            if k == "subject":
                new = re.sub(r"(<dc:description>).*?(</dc:description>)", r"\1<rdf:Alt><rdf:li xml:lang=\"x-default\"></rdf:li></rdf:Alt>\2", new, flags=re.S)
            if k == "keywords":
                new = re.sub(r'(pdf:Keywords=")[^"]*(")', r"\1\2", new)
                new = re.sub(r"(<pdf:Keywords>).*?(</pdf:Keywords>)", r"\1\2", new, flags=re.S)
        for val in sorted({x for x in values if x and len(x) >= 4}, key=len, reverse=True):
            new = new.replace(val, "")
        if new != xmp:
            doc.set_xml_metadata(new)
            changes.append("XMP")
    return changes


def edit_annots(doc, page, blank_contents_xrefs):
    """Blank /T (author) on every annotation; blank /Contents and /RC only where PII was found.
    Low-level key edits: no appearance regeneration, annotation objects kept."""
    n = 0
    for a in list(page.annots() or []):
        x = a.xref
        tt, vv = doc.xref_get_key(x, "T")
        if tt == "string" and vv not in ("", "()"):
            doc.xref_set_key(x, "T", "()")
            n += 1
        if x in blank_contents_xrefs:
            for k in ("Contents", "RC"):
                tt, vv = doc.xref_get_key(x, k)
                if tt != "null":
                    doc.xref_set_key(x, k, "()")
        # popup / reply objects carry /T too
        tp, vp = doc.xref_get_key(x, "Popup")
        if tp == "xref":
            px = int(vp.split()[0])
            tt, vv = doc.xref_get_key(px, "T")
            if tt == "string":
                doc.xref_set_key(px, "T", "()")
    return n


def save(doc, path):
    doc.save(path, garbage=3, deflate=True, clean=False)
