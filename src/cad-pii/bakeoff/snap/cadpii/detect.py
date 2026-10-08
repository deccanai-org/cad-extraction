"""Detection: regex (whole page), LLM on title-block zones, visuals, metadata,
annotations, propagation. Geometry ALWAYS comes from word boxes."""
import json
import re
from collections import defaultdict

import fitz

from . import llm
from .read import to_u

CATS = ["person", "org", "address", "phone", "email", "url", "license", "account_id", "username",
        "project_name", "logo", "seal", "signature"]

# ------------------------------------------------------------------ regex
RX = {
    "phone": re.compile(r"(?<![\w/.-])(?:\+?1[\s.-])?(?:\(\d{3}\)\s?|\d{3}[\s.-])\d{3}[\s.-]\d{4}(?![\w/-])"),
    "phone_lbl": re.compile(r"\b(?:PH|PHONE|TEL|FAX|CELL|MOBILE|OFFICE|P|F|C|M|T)\s*[.:#]?\s*(\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4})\b", re.I),
    "email": re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.I),
    "url": re.compile(r"(?:https?://|www\.)[\w.-]+(?:/\S*)?|\b[\w-]{3,}\.(?:com|net|org|biz|info|us)\b(?:/\S*)?", re.I),
    "license": re.compile(r"\b(?:P\.?\s?E\.?|S\.?\s?E\.?|R\.?\s?A\.?|LICEN[SC]E|LIC|REG(?:ISTRATION)?|CERT(?:IFICATION|IFICATE)?|FIRM\s+REG(?:ISTRATION)?)"
                          r"\s*(?:NO\.?|NUMBER|#)?\s*[:#.]?\s*(?:[A-Z]{1,2}-?)?\d{4,}\b|\bF-\d{3,6}\b", re.I),
    "address": re.compile(r"\b\d{1,6}\s+(?:[NSEW]\.?\s+)?(?:[A-Za-z0-9][\w.'-]*\s+){0,4}?(?:STREET|ST|AVENUE|AVE|ROAD|RD|BOULEVARD|BLVD|DRIVE|DR|LANE|LN|"
                          r"PARKWAY|PKWY|HIGHWAY|HWY|SUITE|STE|CIRCLE|CIR|TERRACE|TRAIL|TRL|PIKE|PLAZA|COURT|CT|WAY)\b\.?(?:,?\s*(?:SUITE|STE|UNIT|#)\s*\w+)?", re.I),
    "cityzip": re.compile(r"\b[A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){0,3},\s*(?:[A-Z]{2}|Texas|Massachusetts|Connecticut|Georgia|California|Florida)\s*,?\s+\d{5}(?:-\d{4})?\b"),
    "pobox": re.compile(r"\bP\.?\s?O\.?\s+BOX\s+\d+\b", re.I),
    "username": re.compile(r"\b[A-Z0-9][A-Z0-9_-]{1,20}\\[A-Za-z][A-Za-z0-9._-]{1,30}\b|[A-Za-z]:\\(?:Users|Documents and Settings)\\[^\\\s]+", re.I),
}
RX_CAT = {"phone": "phone", "phone_lbl": "phone", "email": "email", "url": "url", "license": "license",
          "address": "address", "cityzip": "address", "pobox": "address", "username": "username"}
# things the url regex must not fire on
URL_FP = re.compile(r"\.(?:dwg|pdf|dxf|db1|rvt|tif|png|jpg)$", re.I)


def line_groups(words):
    g = defaultdict(list)
    for w in words:
        g[w.line if w.line is not None else ("solo", w.i)].append(w)
    out = []
    for k, ws in g.items():
        if k and k[0] == "shx":
            out.append(ws)
            continue
        out.append(ws)  # text-layer order is reading order already
    return out


def regex_hits(words):
    """-> [{cat, ids, text, rule}] over line-joined text, mapped back to word ids."""
    hits = []
    for ws in line_groups(words):
        if ws[0].kind.startswith("ocr"):
            ws = sorted(ws, key=lambda w: (w.d.x0 if w.d.width >= w.d.height else -w.d.y1))
        s, spans = "", []
        for w in ws:
            if s:
                s += " "
            spans.append((len(s), len(s) + len(w.text), w))
            s += w.text
        for rule, rx in RX.items():
            for m in rx.finditer(s):
                txt = m.group(0)
                if rule == "url" and (URL_FP.search(txt) or "@" in txt):
                    continue
                a, b = m.span()
                ids = [w.i for (x, y, w) in spans if x < b and y > a]
                if ids:
                    hits.append({"cat": RX_CAT[rule], "ids": ids, "text": txt, "rule": rule})
    return hits


def regex_text(s):
    out = []
    for rule, rx in RX.items():
        for m in rx.finditer(s or ""):
            if rule == "url" and (URL_FP.search(m.group(0)) or "@" in m.group(0)):
                continue
            out.append((RX_CAT[rule], m.group(0)))
    return out


# ------------------------------------------------------------------ LLM packet
ORG_CUE = re.compile(r"\b(INC|LLC|L\.L\.C|LLP|PLLC|P\.?C|CO|CORP|CORPORATION|COMPANY|ASSOCIATES|ENGINEERS?|ENGINEERING|"
                     r"ARCHITECTS?|ARCHITECTURE|GROUP|CONSTRUCTION|CONTRACTORS?|BUILDERS|PARTNERS|LTD|STEEL|FABRICATORS?|"
                     r"DEVELOPMENT|PROPERTIES|CONSULTING|CONSULTANTS|STUDIO|DESIGN)\b\.?", re.I)
PERSON_CUE = re.compile(r"\b(CONTACT|ATTN|ATTENTION|MR|MRS|MS|DR|PREPARED BY|DRAWN BY|CHECKED BY|APPROVED BY|SUBMITTED BY|"
                        r"ENGINEER OF RECORD|EOR|OWNER|CLIENT|ARCHITECT|CONTRACTOR|FABRICATOR|DETAILER|ERECTOR|GC)\b", re.I)

SYSTEM = """You detect personal and party-identifying information (PII) in CAD / engineering drawings for redaction.
You receive crop image(s) of the drawing's title block (and revision table), plus a numbered word list.
Word list format: id<TAB>text<TAB>x<TAB>y, where x,y are the word centre on the page in 0-999 units.
You only choose ids; geometry comes from the ids. Never invent ids.

REDACT (strict owner policy):
- person: every person name or initials (DRAWN / CHECKED / DETAILER / CHECKER / APPROVED / DESIGNED / ENGINEER cells,
  revision-table BY / CHK / APP columns, notes, markups, seal/stamp names, typed signatures).
- org: every company / organisation name of the parties (owner/client, architect, engineer, fabricator, detailer,
  contractor, consultants), including inside project titles (e.g. "AMAZON BOSTON") and logo text.
- address: all addresses, personal AND commercial, including the project site address and city/state/zip lines.
- phone, email, url: phone / fax / mobile numbers, e-mails, websites.
- license: licence / PE / registration / certification numbers, personal AND firm (e.g. "TX FIRM REG NO F-1234").
- account_id: account / PO / contract / permit IDs.
- username: Windows usernames, DOMAIN\\user, file paths containing a user name.
- project_name: non-generic project names (named buildings, sites, developments, e.g. "LUBBOCK FIRE STATION 20").
KEEP (never select): field labels themselves ("DRAWN BY:", "CHECKED", "DATE", "SCALE", "JOB NO.", "CLIENT:"),
drawing / sheet numbers, revision numbers, revision dates and descriptions (minus party names), job / project NUMBERS,
scale, dates, generic sheet titles ("FOUNDATION PLAN", "GENERAL NOTES"), dimensions, technical notes / specs, schedules,
standards (AISC, ASTM, AWS, ACI, IBC) and product / manufacturer references (HILTI, SIMPSON) unless that company is a
party, software names, piece marks, quantities, status stamps ("FOR APPROVAL").
Select only the value words, never the label. Select EVERY word of a multi-word value (all words of a company name incl.
INC / LLC / CO., all words of an address line). If unsure whether a name or company is a party, REDACT it.

VISUAL candidates (V ids, with kind and bbox on the page in 0-999 units) are images or vector clusters in the title block:
mark company logos, engineer seals / stamps, and signatures. META ids are document metadata fields and ANN ids are
annotation texts: mark them if they contain any PII per the policy.

Return ONLY a JSON object:
{"redact":[{"ids":[int,...],"cat":"person|org|address|phone|email|url|license|account_id|username|project_name","text":"<the words>"}],
 "visual":[{"id":"V1","cat":"logo|seal|signature"}],
 "meta":[{"id":"META1","cat":"..."}],
 "ann":[{"id":"ANN1","cat":"..."}],
 "missed":"<PII you can SEE in the image that has no id; empty string if none>"}"""


def norm1000(page, r_d):
    R = page.rect
    return (int(999 * ((r_d.x0 + r_d.x1) / 2 - R.x0) / R.width), int(999 * ((r_d.y0 + r_d.y1) / 2 - R.y0) / R.height))


def build_packet(pm, doc, regex):
    page = pm.page
    zone_ids = [w.i for w in pm.words if pm.in_zones(w.d)]
    zs = set(zone_ids)
    # candidate lines outside the zones
    rx_ids = {i for h in regex for i in h["ids"]}
    extra = []
    for ws in line_groups(pm.words):
        if all(w.i in zs for w in ws):
            continue
        txt = " ".join(w.text for w in ws)
        if any(w.i in rx_ids for w in ws) or ORG_CUE.search(txt) or PERSON_CUE.search(txt):
            extra.append([w.i for w in ws if w.i not in zs])
    extra = extra[:80]
    lines = ["TITLE BLOCK / REVISION TABLE WORDS:"]
    for i in zone_ids:
        w = pm.words[i]
        x, y = norm1000(page, w.d)
        lines.append(f"{i}\t{w.text}\t{x}\t{y}")
    if extra:
        lines.append("\nOTHER CANDIDATE LINES ELSEWHERE ON THE SHEET (same format):")
        for ids in extra:
            for i in ids:
                w = pm.words[i]
                x, y = norm1000(page, w.d)
                lines.append(f"{i}\t{w.text}\t{x}\t{y}")
            lines.append("")
    vis = []
    if pm.vis:
        lines.append("\nVISUAL CANDIDATES (id, kind, bbox x0,y0,x1,y1 in 0-999 page units):")
        R = page.rect
        for v in pm.vis:
            d = v["d"]
            bb = [int(999 * (d.x0 - R.x0) / R.width), int(999 * (d.y0 - R.y0) / R.height),
                  int(999 * (d.x1 - R.x0) / R.width), int(999 * (d.y1 - R.y0) / R.height)]
            lines.append(f"{v['id']}\t{v['kind']}{' (circle-like)' if v.get('seal_like') else ''}\t{bb}")
            vis.append(v["id"])
    meta = {}
    md = doc.metadata or {}
    for k in ("title", "author", "subject", "keywords", "creator", "producer"):
        if md.get(k):
            meta[f"META{len(meta) + 1}"] = (k, md[k])
    if meta:
        lines.append("\nMETADATA:")
        for mid, (k, v) in meta.items():
            lines.append(f"{mid}\t{k}\t{v}")
    ann = {}
    for a in pm.annots:
        if a["title"].strip().lower() == "autocad shx text":
            continue
        txt = " | ".join(x for x in (a["content"], a["subject"]) if x)
        if txt.strip():
            ann[f"ANN{len(ann) + 1}"] = (a["xref"], txt[:300])
    if ann:
        lines.append("\nANNOTATIONS (id, text):")
        for aid, (x, t) in ann.items():
            lines.append(f"{aid}\t{t}")
    return {"text": "\n".join(lines), "zone_ids": zone_ids, "extra_ids": [i for ids in extra for i in ids],
            "vis_ids": vis, "meta": meta, "ann": ann}


def run_llm(pm, doc, packet, model, tiles, tag=""):
    imgs = [t["png"] for t in tiles]
    hdr = (f"Drawing page {pm.rect_d.width:.0f}x{pm.rect_d.height:.0f} pt. {len(imgs)} crop image(s) follow "
           f"(title block{' split into tiles' if len(imgs) > 1 else ''}"
           f"{'; plus revision-table crop(s)' if len(pm.zones) > 1 else ''}).\n\n")
    res = llm.chat(model, SYSTEM, hdr + packet["text"], images=imgs, tag=tag)
    if (res.get("error") or not res.get("parsed")) and model in FALLBACK:
        res2 = llm.chat(FALLBACK[model], SYSTEM, hdr + packet["text"], images=imgs, tag=tag + ":fallback")
        res2["fallback_from"] = model
        res2["first_error"] = res.get("error") or "unparsable"
        return res2
    return res


FALLBACK = {"qwen/qwen3.8-max-prime": "qwen/qwen3.8-max-0902"}


LABEL_PART = re.compile(r"^(ARCH|ARCHITECT|ENG|ENGR|ENGINEER|STRUCT|STRUCTURAL|MEP|CIVIL|LANDSCAPE|CLIENT|OWNER|CONTRACTOR|GC|"
                        r"FABRICATOR|FAB|DETAILER|ERECTOR|DRAWN|DRN|DWN|CHECKED|CHK|CHKD|CKD|APPROVED|APP|APPD|DESIGNED|DES|BY|"
                        r"DATE|PROJECT|PROJ|JOB|TITLE|ADDRESS|ADDR|PHONE|PH|FAX|TEL|EMAIL|E-MAIL|WEB|CUSTOMER|LOCATION|SITE|"
                        r"SEAL|CONSULTANT|CONSULTANTS|PREPARED|FOR|NO|NUMBER|LIC|LICENSE|REG|DESCRIPTION|DESC|REV|SHEET|"
                        r"DRAWING|DWG|SCALE|ISSUED|CHECKER|SUBMITTED)$", re.I)


def is_label(text):
    """A pure field label such as 'ARCH./ENG.', 'DRAWN BY:', 'CLIENT:' -- never redact it."""
    t = text.strip()
    if not t or not re.search(r"[:./]$|/", t) and not t.endswith(":"):
        return False
    parts = [x for x in re.split(r"[\s/.:&-]+", t) if x]
    return bool(parts) and all(LABEL_PART.match(x) for x in parts)


def parse_llm(res, packet, pm):
    """-> dict(groups=[{ids,cat,text}], visual=[{id,cat}], meta=[...], ann=[...], invalid=n, total=n)"""
    p = res.get("parsed") or {}
    valid = set(packet["zone_ids"]) | set(packet["extra_ids"])
    groups, inval, tot = [], 0, 0
    for g in (p.get("redact") or []):
        if not isinstance(g, dict):
            continue
        ids = []
        for x in g.get("ids") or []:
            tot += 1
            try:
                x = int(x)
            except Exception:
                inval += 1
                continue
            if x in valid:
                if is_label(pm.words[x].text):
                    continue   # label filter: keep field labels visible
                ids.append(x)
            else:
                inval += 1
        cat = str(g.get("cat", "person")).lower()
        if cat not in CATS:
            cat = "person"
        if ids:
            groups.append({"ids": ids, "cat": cat, "text": g.get("text", "")})
    vis = [v for v in (p.get("visual") or []) if isinstance(v, dict) and v.get("id") in packet["vis_ids"]]
    meta = [m for m in (p.get("meta") or []) if isinstance(m, dict) and m.get("id") in packet["meta"]]
    ann = [m for m in (p.get("ann") or []) if isinstance(m, dict) and m.get("id") in packet["ann"]]
    return {"groups": groups, "visual": vis, "meta": meta, "ann": ann, "invalid": inval, "total_ids": tot,
            "missed": p.get("missed", ""), "parsed_ok": bool(res.get("parsed"))}


# ------------------------------------------------------------------ propagation
STOP = set("""THE AND FOR WITH FROM THIS THAT STEEL BEAM COLUMN PLATE BOLT BOLTS WELD NOTE NOTES PLAN DETAIL DETAILS SECTION
ELEVATION SHEET DRAWING DATE SCALE CHECKED DRAWN APPROVED REVISION REVISIONS PROJECT JOB CLIENT OWNER ENGINEER ARCHITECT
CONTRACTOR GENERAL STRUCTURAL FRAMING FOUNDATION ROOF FLOOR LEVEL TYPICAL TYP NORTH SOUTH EAST WEST STREET ROAD AVENUE
INC LLC CO CORP COMPANY GROUP ASSOCIATES ENGINEERS ENGINEERING ARCHITECTS DESIGN CONSTRUCTION ISSUED APPROVAL FIELD SHOP
ERECTION CONNECTION CONNECTIONS DESCRIPTION NUMBER BUILDING STATION CENTER CENTRE OFFICE SUITE STATE CITY COUNTY""".split())


def normtok(t):
    return re.sub(r"[^A-Z0-9&]", "", t.upper())


def propagate(pm, values, zone_only_short=True):
    """values: [(cat, text)] learned in TB -> extra [{cat, ids, text, rule}] exact-token matches page-wide."""
    toks = [normtok(w.text) for w in pm.words]
    out = []
    for cat, text in values:
        if cat not in ("person", "org", "project_name", "username", "email", "phone", "license", "address"):
            continue
        vt = [normtok(t) for t in re.split(r"[\s,]+", text or "") if normtok(t)]
        if not vt:
            continue
        n = len(vt)
        for i in range(len(toks) - n + 1):
            if toks[i:i + n] != vt:
                continue
            ws = pm.words[i:i + n]
            if n == 1:
                t = vt[0]
                if t in STOP or t.isdigit() and len(t) < 5:
                    continue
                if len(t) <= 3 and not pm.in_zones(ws[0].d):
                    continue  # initials only inside title-block zones
            out.append({"cat": cat, "ids": [w.i for w in ws], "text": text, "rule": "propagate"})
    return out
