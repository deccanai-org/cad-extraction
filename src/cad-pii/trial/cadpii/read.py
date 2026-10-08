"""Readers for the CAD-PII trial.

Coordinate convention (measured, PyMuPDF 1.26.5):
  * get_text('words'), get_cdrawings(), annot.rect, get_image_info() bboxes and
    add_redact_annot() all use UNROTATED page space (mediabox space).
  * page.rect and get_pixmap(clip=...) use DISPLAYED (rotated) space.
So: everything is stored unrotated ("u") and converted to displayed ("d") with
page.rotation_matrix only for title-block geometry and rendering.
"""
import io
import math
import re
from collections import Counter

import fitz
import numpy as np

TB_ANCHORS = re.compile(
    r"^(DRAWN|DRN|DWN|DRAFTED|CHECKED|CHK|CHKD|CKD|CHK'D|CHECKER|APPROVED|APPR|APPD|APP|"
    r"DESIGNED|DSGN|DES|DETAILER|DETAILED|DET|DATE|SCALE|JOB|PROJECT|PROJ|SHEET|SHT|DWG|"
    r"DRAWING|REV|REVISION|REVISIONS|TITLE|CLIENT|OWNER|ENGINEER|ARCHITECT|CONTRACTOR|"
    r"FABRICATOR|ERECTOR|DESCRIPTION|CUSTOMER|SEAL|ISSUED|ISSUE|NO|NUMBER|BY|PLOT|FILE)"
    r"[:.#']*$", re.I)


def all_layers_on(doc):
    """In-memory only: switch every OCG on so text/drawings on hidden layers are read."""
    try:
        ocgs = doc.get_ocgs()
        if ocgs:
            doc.set_layer(-1, on=list(ocgs.keys()), off=[])
    except Exception:
        pass
    return doc


def to_d(page, r):
    return fitz.Rect(r) * page.rotation_matrix


def to_u(page, r):
    return fitz.Rect(r) * page.derotation_matrix


class Word:
    __slots__ = ("i", "text", "u", "d", "kind", "line", "conf", "xref", "ink")

    def __init__(self, i, text, u, d, kind, line=None, conf=1.0, xref=0):
        self.i, self.text, self.u, self.d, self.kind, self.line, self.conf, self.xref = i, text, u, d, kind, line, conf, xref
        self.ink = fitz.Rect(u)

    def as_dict(self):
        return {"i": self.i, "text": self.text, "u": [round(v, 2) for v in self.u],
                "kind": self.kind, "conf": round(self.conf, 3)}


# ---------------------------------------------------------------- OCR
_OCR = None


def ocr_engine():
    global _OCR
    if _OCR is None:
        from rapidocr_onnxruntime import RapidOCR
        _OCR = RapidOCR()
    return _OCR


def ocr_region(page, clip_d, dpi=300, tile=1800, overlap=120, tag="ocr"):
    """OCR a DISPLAYED-space region; returns [(text, rect_u, conf)] word-level
    (line results split proportionally by character count)."""
    zoom = dpi / 72.0
    clip_d = fitz.Rect(clip_d) & page.rect
    if clip_d.is_empty:
        return []
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip_d, alpha=False)
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w, pix.n)[..., :3].copy()
    H, W = img.shape[:2]
    eng = ocr_engine()
    out = []
    seen = []
    nline = 0
    ys = list(range(0, max(1, H - overlap), tile - overlap)) or [0]
    xs = list(range(0, max(1, W - overlap), tile - overlap)) or [0]
    for ty in ys:
        for tx in xs:
            sub = img[ty:ty + tile, tx:tx + tile]
            if sub.size == 0 or sub.min() > 245:
                continue
            res, _ = eng(sub)
            for box, text, conf in (res or []):
                conf = float(conf)
                if conf < 0.5 or not text.strip():
                    continue
                pts = np.array(box, dtype=float)
                x0, y0 = pts[:, 0].min() + tx, pts[:, 1].min() + ty
                x1, y1 = pts[:, 0].max() + tx, pts[:, 1].max() + ty
                key = (round(x0 / 8), round(y0 / 8), text)
                if any(abs(k[0] - key[0]) <= 2 and abs(k[1] - key[1]) <= 2 and k[2] == text for k in seen):
                    continue
                seen.append(key)
                nline += 1
                vertical = (y1 - y0) > 2.5 * (x1 - x0) and len(text) > 2
                toks = [x for t0 in text.split() for x in re.split(r"(?<=:)(?=\S)", t0) if x]
                n = max(1, sum(len(t) for t in toks) + len(toks) - 1)
                pos = 0
                for t in toks:
                    a, b = pos / n, (pos + len(t)) / n
                    pos += len(t) + 1
                    if vertical:  # text running bottom-to-top in displayed space
                        r = fitz.Rect(x0, y1 - b * (y1 - y0), x1, y1 - a * (y1 - y0))
                    else:
                        r = fitz.Rect(x0 + a * (x1 - x0), y0, x0 + b * (x1 - x0), y1)
                    rd = fitz.Rect(clip_d.x0 + r.x0 / zoom, clip_d.y0 + r.y0 / zoom,
                                   clip_d.x0 + r.x1 / zoom, clip_d.y0 + r.y1 / zoom)
                    out.append((t, to_u(page, rd), conf, (tag, nline)))
    return out


# ---------------------------------------------------------------- page model
class PageModel:
    def __init__(self, doc, pno, ocr=True):
        self.doc = doc
        self.page = page = doc[pno]
        self.pno = pno
        self.rect_d = page.rect
        self.words = []
        # MuPDF mirrors word bboxes about the baseline for upside-down text (dir = (-1, 0), e.g. on
        # /Rotate 180 sheets): keep the metric bbox (what apply_redactions tests) AND the true ink rect.
        flipped = []   # (line bbox, baseline y) for upside-down lines; matched to words by geometry
        try:
            for b in page.get_text("rawdict")["blocks"]:
                for l in b.get("lines", []):
                    sp = [s_ for s_ in l["spans"] if s_["chars"]]
                    if sp and l["dir"][0] < -0.9:
                        flipped.append((fitz.Rect(l["bbox"]), sp[0]["chars"][0]["origin"][1]))
        except Exception:
            pass
        for w in page.get_text("words"):
            u = fitz.Rect(w[:4])
            wd = Word(len(self.words), w[4], u, to_d(page, u), "text", line=(w[5], w[6]))
            if flipped:
                c = fitz.Point((u.x0 + u.x1) / 2, (u.y0 + u.y1) / 2)
                for lb, base in flipped:
                    if lb.contains(c):
                        wd.ink = fitz.Rect(u.x0, 2 * base - u.y1, u.x1, 2 * base - u.y0)
                        break
            self.words.append(wd)
        self.n_text_words = len(self.words)
        # AutoCAD SHX Text comments: invisible annots whose /Contents is the stroked text
        self.annots = []
        for a in page.annots() or []:
            info = a.info or {}
            self.annots.append({"xref": a.xref, "type": a.type[1], "rect": fitz.Rect(a.rect),
                                "title": info.get("title", ""), "content": info.get("content", ""),
                                "subject": info.get("subject", "")})
            if (info.get("title") or "").strip().lower() == "autocad shx text" and (info.get("content") or "").strip():
                u = fitz.Rect(a.rect)
                self.words.append(Word(len(self.words), info["content"].strip(), u, to_d(page, u), "shx",
                                       line=("shx", a.xref), xref=a.xref))
        # images
        self.images = []
        for im in page.get_image_info(xrefs=True):
            u = fitz.Rect(im["bbox"])
            if u.is_empty:
                continue
            self.images.append({"xref": im.get("xref", 0), "u": u, "d": to_d(page, u),
                                "w": im.get("width"), "h": im.get("height")})
        pa = self.rect_d.width * self.rect_d.height
        self.raster = any(im["d"].width * im["d"].height > 0.5 * pa for im in self.images)
        # drawings -> axis-aligned segments in displayed space
        self.paths = page.get_cdrawings()
        self.hsegs, self.vsegs = [], []
        rm = page.rotation_matrix
        for p in self.paths:
            for it in p["items"]:
                pts = []
                if it[0] == "l":
                    pts = [(it[1], it[2])]
                elif it[0] == "re":
                    r = fitz.Rect(it[1])
                    pts = [((r.x0, r.y0), (r.x1, r.y0)), ((r.x1, r.y0), (r.x1, r.y1)),
                           ((r.x0, r.y1), (r.x1, r.y1)), ((r.x0, r.y0), (r.x0, r.y1))]
                elif it[0] == "qu":
                    q = it[1]
                    pts = [(q[0], q[1]), (q[1], q[3]), (q[3], q[2]), (q[2], q[0])]
                for a, b in pts:
                    pa_ = fitz.Point(a) * rm
                    pb_ = fitz.Point(b) * rm
                    if abs(pa_.y - pb_.y) < 0.6 and abs(pa_.x - pb_.x) > 4:
                        self.hsegs.append((min(pa_.x, pb_.x), max(pa_.x, pb_.x), (pa_.y + pb_.y) / 2))
                    elif abs(pa_.x - pb_.x) < 0.6 and abs(pa_.y - pb_.y) > 4:
                        self.vsegs.append((min(pa_.y, pb_.y), max(pa_.y, pb_.y), (pa_.x + pb_.x) / 2))
        self.ocr_done = []
        if ocr and (self.raster or self.n_text_words < 20):
            # raster or vector-text page: OCR the whole page (150 dpi, tiled)
            for t, u, c, ln in ocr_region(page, self.rect_d, dpi=150, tag="ocrp"):
                self._add_ocr(t, u, c, ln)
            self.ocr_done.append("page@150")
        self.tb = self.detect_title_block()
        self.zones = [self.tb] + self.revision_zones()
        if ocr:
            tbw = [w for w in self.words if w.kind == "text" and self.in_zones(w.d)]
            if self.raster or len(tbw) < 8:
                # replace page-level OCR words inside the TB with a 300 dpi pass
                keep = [w for w in self.words if not (w.kind.startswith("ocr") and any(z.intersects(w.d) for z in self.zones))]
                self.words = keep
                for zi, z in enumerate(self.zones):
                    for t, u, c, ln in ocr_region(page, z, dpi=300, tag=f"ocrz{zi}"):
                        self._add_ocr(t, u, c, ln)
                self.ocr_done.append("tb@300")
        for k, w in enumerate(self.words):
            w.i = k
        self.vis = self.visual_candidates()

    def _add_ocr(self, t, u, c, ln=None):
        d = to_d(self.page, u)
        on_img = any(im["u"].intersects(u) for im in self.images)
        # skip OCR words that duplicate an existing text-layer word
        for w in self.words:
            if w.kind == "text" and w.u.intersects(u):
                inter = w.u & u
                if inter.width * inter.height > 0.4 * min(u.width * u.height, w.u.width * w.u.height):
                    return
        self.words.append(Word(len(self.words), t, u, d, "ocr_raster" if on_img else "ocr_vector", line=ln, conf=c))

    # ------------------------------------------------------------ title block
    def detect_title_block(self):
        R = self.rect_d
        W, H = R.width, R.height
        words = [(w.d, w.text) for w in self.words]
        linelen = Counter(w.line for w in self.words if w.line is not None)
        labelish = [w for w in self.words if w.line is None or linelen[w.line] <= 5]
        anchors = [(w.d, w.text.strip().upper().rstrip(":.#'")) for w in labelish if TB_ANCHORS.match(w.text.strip())]

        def merged(segs, lo, hi, minlen):
            acc = {}
            for (a, b, c) in segs:
                if lo < c < hi:
                    acc.setdefault(round(c), []).append((a, b))
            out = []
            for c, iv in acc.items():
                iv.sort()
                tot, cur = 0.0, None
                for a, b in iv:
                    if cur is None or a > cur[1] + 2:
                        if cur:
                            tot += cur[1] - cur[0]
                        cur = [a, b]
                    else:
                        cur[1] = max(cur[1], b)
                if cur:
                    tot += cur[1] - cur[0]
                if tot >= minlen:
                    out.append(float(c))
            return sorted(out)
        longv = sorted({round(x, 1) for (y0, y1, x) in self.vsegs if y1 - y0 > 0.30 * H and 0.55 * W < x < 0.985 * W})
        longh = sorted({round(y, 1) for (x0, x1, y) in self.hsegs if x1 - x0 > 0.25 * W and 0.55 * H < y < 0.985 * H})
        longv = sorted(set(longv) | set(merged(self.vsegs, 0.6 * W, 0.985 * W, 0.12 * H)))
        longh = sorted(set(longh) | set(merged(self.hsegs, 0.6 * H, 0.985 * H, 0.15 * W)))
        # frame (inner border) estimate
        fx1 = max([x for (y0, y1, x) in self.vsegs if y1 - y0 > 0.5 * H and x > 0.9 * W] or [W])
        fy1 = max([y for (x0, x1, y) in self.hsegs if x1 - x0 > 0.5 * W and y > 0.9 * H] or [H])
        fx0 = min([x for (y0, y1, x) in self.vsegs if y1 - y0 > 0.5 * H and x < 0.1 * W] or [0])
        fy0 = min([y for (x0, x1, y) in self.hsegs if x1 - x0 > 0.5 * W and y < 0.1 * H] or [0])
        cands = []
        for x in set(longv) | {fx1 - f * W for f in (0.12, 0.18, 0.25)}:
            cands.append(("right", fitz.Rect(x, fy0, fx1, fy1)))
        for y in set(longh) | {fy1 - f * H for f in (0.12, 0.18, 0.25)}:
            cands.append(("bottom", fitz.Rect(fx0, y, fx1, fy1)))
        cv = [x for (y0, y1, x) in self.vsegs if y1 > fy1 - 3 and y1 - y0 > 0.08 * H and 0.35 * W < x < 0.95 * W]
        ch = [y for (x0, x1, y) in self.hsegs if x1 > fx1 - 3 and x1 - x0 > 0.08 * W and 0.45 * H < y < 0.95 * H]
        cvs = sorted({round(x) for x in cv})[:40] + [fx1 - 0.3 * W, fx1 - 0.4 * W]
        chs = sorted({round(y) for y in ch})[:40] + [fy1 - 0.25 * H, fy1 - 0.35 * H]
        for x in cvs:
            for y in chs:
                cands.append(("corner", fitz.Rect(x, y, fx1, fy1)))
        best, bs = None, -1e9
        pa = W * H
        strong = re.compile(r"^(DRAWN|DRN|DWN|CHECKED|CHK|CHKD|CKD|APPROVED|APPD|DESIGNED|DETAILER|DETAILED|CHECKER|"
                            r"SCALE|JOB|PROJECT|SHEET|DWG|DRAWING|TITLE|CLIENT|OWNER|ENGINEER|ARCHITECT|CONTRACTOR|"
                            r"FABRICATOR|CUSTOMER|REVISIONS?|SEAL)[:.#']*$", re.I)
        strong_a = [(w.d, w.text.strip().upper().rstrip(":.#'")) for w in labelish if strong.match(w.text.strip())]
        self.tb_debug = []
        for kind, r in cands:
            if r.is_empty or r.width < 20 or r.height < 20:
                continue
            af = r.width * r.height / pa
            if af > 0.40:
                continue
            na = len({t for d, t in anchors if r.contains(d.tl) and r.contains(d.br)})
            ns = len({t for d, t in strong_a if r.contains(d.tl) and r.contains(d.br)})
            # cell dividers: segments spanning (almost) the full short side of the candidate
            if kind == "right":
                div = {round(y) for (x0, x1, y) in self.hsegs if r.y0 - 1 <= y <= r.y1 + 1 and x0 <= r.x0 + 0.15 * r.width and x1 >= r.x1 - 0.15 * r.width}
            elif kind == "bottom":
                div = {round(x) for (y0, y1, x) in self.vsegs if r.x0 - 1 <= x <= r.x1 + 1 and y0 <= r.y0 + 0.15 * r.height and y1 >= r.y1 - 0.15 * r.height}
            else:
                div = {round(y) for (x0, x1, y) in self.hsegs if r.y0 - 1 <= y <= r.y1 + 1 and x0 >= r.x0 - 2 and x1 <= r.x1 + 2 and x1 - x0 > 0.3 * r.width}
                div |= {round(x) + 100000 for (y0, y1, x) in self.vsegs if r.x0 - 1 <= x <= r.x1 + 1 and y0 >= r.y0 - 2 and y1 <= r.y1 + 2 and y1 - y0 > 0.3 * r.height}
            nw = sum(1 for d, t in words if r.contains(d.tl))
            edge = 0 if (kind != "right" or any(abs(r.x0 - x) < 1.6 for x in longv)) else -4
            if kind == "bottom" and not any(abs(r.y0 - y) < 1.6 for y in longh):
                edge = -4
            s = 4 * ns + 1.0 * na + 1.2 * min(len(div), 30) + min(nw, 60) / 20 - 90 * af + edge
            self.tb_debug.append((round(s, 1), kind, [round(v) for v in r], ns, na, len(div), nw, round(af, 3)))
            if s > bs:
                best, bs = (kind, r), s
        if best is not None and sum(1 for d, t in words if best[1].contains(d.tl)) < 3:
            alt = [(sum(1 for d, t in words if r.contains(d.tl)), kind, r) for kind, r in cands
                   if kind in ("right", "bottom") and not r.is_empty and r.width * r.height / pa <= 0.35]
            alt = [a for a in alt if a[0] >= 3]
            if alt:
                a = max(alt, key=lambda a: a[0] - 400 * a[2].width * a[2].height / pa)
                best = (a[1] + "-mostwords", a[2])
        if best is None:
            best = ("fallback", fitz.Rect(fx1 - 0.35 * W, fy1 - 0.30 * H, fx1, fy1))
        self.tb_kind, self.tb_score = best[0], bs
        return best[1] & R

    def in_zones(self, r_d, full=False):
        for z in self.zones:
            if (z.contains(r_d) if full else z.contains(fitz.Point((r_d.x0 + r_d.x1) / 2, (r_d.y0 + r_d.y1) / 2))):
                return True
        return False

    def revision_zones(self):
        lab = re.compile(r"^(REV|REV\.|REVISION|REVISIONS|NO|NO\.|DATE|DESCRIPTION|DESC|BY|CHK|CHK'D|CHKD|CKD|"
                         r"APP|APP'D|APPD|ISSUE|MARK|ECO)[:.]?$", re.I)
        hw = [w for w in self.words if lab.match(w.text.strip())]
        zones = []
        used = set()
        for w in hw:
            if w.i in used:
                continue
            cy = (w.d.y0 + w.d.y1) / 2
            row = [v for v in hw if abs((v.d.y0 + v.d.y1) / 2 - cy) < 3.5 and abs(v.d.x0 - w.d.x0) < 520]
            labels = {v.text.strip().upper().rstrip(':.').replace("'", "") for v in row}
            if len(labels) < 3 or "DATE" not in labels or not (labels & {"DESCRIPTION", "DESC", "BY", "CHK", "CHKD", "APP", "APPD"}):
                continue
            for v in row:
                used.add(v.i)
            x0 = min(v.d.x0 for v in row) - 25
            x1 = max(v.d.x1 for v in row) + 40
            hy0 = min(v.d.y0 for v in row)
            hy1 = max(v.d.y1 for v in row)
            col = sorted([v for v in self.words if v.d.x0 >= x0 and v.d.x1 <= x1 + 60], key=lambda v: v.d.y0)
            top, bot = hy0, hy1
            for direction in (1, -1):
                edge = hy1 if direction == 1 else hy0
                seq = [v for v in col if (v.d.y0 >= hy1 - 0.5) == (direction == 1)]
                seq = seq if direction == 1 else seq[::-1]
                for v in seq:
                    gap = (v.d.y0 - edge) if direction == 1 else (edge - v.d.y1)
                    if gap > 28 or abs(v.d.y0 - hy0) > 320:
                        break
                    edge = max(edge, v.d.y1) if direction == 1 else min(edge, v.d.y0)
                if direction == 1:
                    bot = edge
                else:
                    top = edge
            z = fitz.Rect(x0, top - 4, x1, bot + 4) & self.rect_d
            inter = z & self.tb
            if not z.is_empty and (inter.is_empty or inter.width * inter.height < 0.7 * z.width * z.height):
                zones.append(z)
        return zones[:3]

    # ------------------------------------------------------------ visuals
    def visual_candidates(self):
        """Images and curve-heavy vector clusters inside the title block (displayed space)."""
        tb = self.tb
        out = []
        tba = tb.width * tb.height
        zs = self.zones
        for im in self.images:
            d = fitz.Rect()
            for z in zs:
                d |= (im["d"] & z)
            if d.is_empty or d.width < 6 or d.height < 6:
                continue
            if im["d"].width * im["d"].height > 0.6 * tba and self.raster:
                continue  # the scan itself
            out.append({"kind": "image", "d": d, "u": to_u(self.page, d), "xref": im["xref"]})
        rm = self.page.rotation_matrix
        small = []
        for p in self.paths:
            r = fitz.Rect(p["rect"]) * rm
            if not any(z.contains(r) for z in zs) or r.width > 0.6 * tb.width or r.height > 0.6 * tb.height:
                continue
            nc = sum(1 for it in p["items"] if it[0] == "c")
            small.append([r, nc, len(p["items"]), p.get("type", "")])
        # union-find by proximity
        n = len(small)
        if n > 6000:
            small = small[:6000]
            n = 6000
        parent = list(range(n))

        def f(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        order = sorted(range(n), key=lambda k: small[k][0].x0)
        for a_i in range(n):
            a = order[a_i]
            ra = small[a][0]
            for b_i in range(a_i + 1, n):
                b = order[b_i]
                rb = small[b][0]
                if rb.x0 > ra.x1 + 4:
                    break
                if rb.y0 <= ra.y1 + 4 and ra.y0 <= rb.y1 + 4:
                    parent[f(b)] = f(a)
        groups = {}
        for k in range(n):
            groups.setdefault(f(k), []).append(small[k])
        for g in groups.values():
            r = fitz.Rect(g[0][0])
            for x in g[1:]:
                r |= x[0]
            nc = sum(x[1] for x in g)
            ni = sum(x[2] for x in g)
            fills = sum(1 for x in g if "f" in x[3])
            fill_area = sum(x[0].width * x[0].height for x in g if "f" in x[3])
            if r.width < 12 or r.height < 12:
                continue
            if ni < 20 and not (fills >= 1 and fill_area >= 150):
                continue
            if r.width > 0.7 * tb.width and r.height > 0.5 * tb.height:
                continue
            curve_share = nc / max(ni, 1)
            nw = sum(1 for w in self.words if w.kind == "text" and r.contains(w.d))
            square = 0.6 < r.width / max(r.height, 1e-3) < 1.6
            seal_like = square and 50 < r.width < 220 and nc >= 4
            if curve_share >= 0.25 or fills >= 5 or seal_like or (fills >= 1 and fill_area >= 150 and nw == 0 and r.width * r.height < 0.3 * tba):
                if nw > 25 and not seal_like:
                    continue
                out.append({"kind": "vector", "d": r, "u": to_u(self.page, r),
                            "curves": nc, "items": ni, "seal_like": seal_like})
        for k, v in enumerate(out, 1):
            v["id"] = f"V{k}"
        return out

    # ------------------------------------------------------------ rendering
    def render_d(self, clip_d, dpi):
        zoom = dpi / 72.0
        pix = self.page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=fitz.Rect(clip_d) & self.rect_d, alpha=False)
        return pix

    def zone_tiles(self, **kw):
        tiles = []
        for zi, z in enumerate(self.zones):
            for t in self.tb_tiles(z, **kw):
                t["zone"] = zi
                tiles.append(t)
        return tiles

    def tb_tiles(self, zone=None, max_side=2000, max_dpi=200, min_dpi=110):
        """Title-block crop as 1..3 PNG tiles split along the long axis."""
        tb = fitz.Rect(zone if zone is not None else self.tb) + (-4, -4, 4, 4)
        tb &= self.rect_d
        long_side = max(tb.width, tb.height)
        short = min(tb.width, tb.height)
        k = 1
        if long_side / max(short, 1) > 2.6:
            k = 2 if long_side / short < 5.5 else 3
        tiles = []
        for j in range(k):
            if tb.height >= tb.width:
                h = tb.height / k
                r = fitz.Rect(tb.x0, tb.y0 + j * h - (8 if j else 0), tb.x1, tb.y0 + (j + 1) * h + (8 if j < k - 1 else 0))
            else:
                w = tb.width / k
                r = fitz.Rect(tb.x0 + j * w - (8 if j else 0), tb.y0, tb.x0 + (j + 1) * w + (8 if j < k - 1 else 0), tb.y1)
            dpi = min(max_dpi, max_side * 72.0 / max(r.width, r.height))
            dpi = max(dpi, min_dpi)
            pix = self.render_d(r, dpi)
            tiles.append({"clip_d": r, "dpi": dpi, "png": pix.tobytes("png"), "w": pix.width, "h": pix.height})
        return tiles
