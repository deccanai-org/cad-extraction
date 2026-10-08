"""Summaries over a run folder: summary.md (Slack-ready), summary.csv, report.html (with the renders)."""
import os, json, glob, csv, collections, html, datetime


def load(out_dir):
    rows = []
    for f in sorted(glob.glob(os.path.join(out_dir, "*.json"))):
        if f.endswith(("_vlm.json", "_vlm_request.json")) or os.path.basename(f).startswith(("sample", "summary")): continue
        d = json.load(open(f))
        if "result" in d: rows.append(d["result"])
    return rows


def _row(r):
    g = r.get("geometry") or {}; t = r.get("truth") or {}; m = t.get("match") or {}; rp = (r.get("reproduce") or {}).get("match") or {}
    rec = r.get("record") or {}; v = r.get("vlm") or {}
    return dict(sha=r["sha"][:16], verdict=r.get("verdict"), evidence=r.get("evidence"), engine=rec.get("engine"),
                step_mb=round((r.get("step") or {}).get("bytes", 0) / 1e6, 1), parts=(r.get("step") or {}).get("products"),
                solids=(g.get("kinds") or {}).get("solid"), extent_m="x".join(str(round(x / 1000)) for x in g.get("extent_mm", [])) if g.get("extent_mm") else "",
                input_ok=bool((r.get("input") or {}).get("sha256") == r["sha"]),
                repro=round(rp["precision_a"], 4) if rp else "", tekla_recall=round(m["recall_b"], 4) if m else "",
                tekla_prec_inside=round(m["precision_a_inside"], 4) if m else "", tekla_elements=m.get("b", "") if m else "",
                truth=t.get("status", ""), vlm=v.get("overall", "queued" if v.get("queued") else ""),
                codes=" ".join(c for c in r.get("codes", []) if not c.startswith("I_")), model=(rec.get("key") or "").split("/")[-1][:60])


def write(out_dir, suffix=""):
    rows = load(out_dir)
    if not rows: return None
    T = [_row(r) for r in rows]
    with open(os.path.join(out_dir, f"summary{suffix}.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, list(T[0])); w.writeheader(); w.writerows(T)
    vc = collections.Counter(t["verdict"] for t in T); ev = collections.Counter(t["evidence"] for t in T)
    codes = collections.Counter(c for r in rows for c in r.get("codes", []))
    cause = {}
    for r in rows:
        for fnd in r.get("findings", []): cause.setdefault(fnd["code"], (fnd["level"], fnd["cause"], fnd["message"]))
    L = [f"# db1 -> STEP verification ({len(rows)} files, {datetime.date.today()})", "",
         "| verdict | files |", "|---|---|"] + [f"| {k} | {v} |" for k, v in sorted(vc.items())] + [
         "", "| evidence level | files |", "|---|---|"] + [f"| {k} | {v} |" for k, v in sorted(ev.items())] + [
         "", f"Input .db1 present and sha256 = STEP name: {sum(t['input_ok'] for t in T)}/{len(T)}",
         f"Reproduced from the input (>= 98% parts): {sum(1 for t in T if t['repro'] != '' and t['repro'] >= 0.98)}/{sum(1 for t in T if t['repro'] != '')} run",
         f"Tekla export found and aligned: {sum(1 for t in T if t['truth'] == 'matched')}, recall >= 90%: {sum(1 for t in T if t['tekla_recall'] != '' and t['tekla_recall'] >= 0.9)}",
         "", "| code | level | cause | files | example |", "|---|---|---|---|---|"] + [
         f"| {c} | {cause[c][0]} | {cause[c][1]} | {n} | {cause[c][2][:110]} |" for c, n in sorted(codes.items(), key=lambda x: ("FWI".index(x[0][0]), -x[1]))] + [
         "", "| sha | verdict | engine | parts | repro | tekla recall | vlm | codes |", "|---|---|---|---|---|---|---|---|"] + [
         f"| {t['sha']} | {t['verdict']} | {t['engine']} | {t['parts']} | {t['repro']} | {t['tekla_recall']} | {t['vlm']} | {t['codes']} |" for t in T]
    open(os.path.join(out_dir, f"summary{suffix}.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    # html
    col = {"PASS": "#1f7a3a", "WARN": "#a86b00", "FAIL": "#b3261e"}
    cards = []
    for r, t in zip(rows, T):
        imgs = "".join(f'<a href="{html.escape(p)}"><img src="{html.escape(p)}" loading="lazy"></a>' for p in r.get("renders", []))
        fnd = "".join(f'<li class="{f["level"]}"><b>{f["code"]}</b> <span class="cause">{f["cause"]}</span> {html.escape(f["message"])}</li>'
                      for f in sorted(r.get("findings", []), key=lambda f: "FWI".index(f["level"][0])))
        cards.append(f'<section class="card"><h2><span class="v" style="background:{col.get(t["verdict"], "#555")}">{t["verdict"]}</span> '
                     f'{t["sha"]} <small>Xsteel {t["engine"]} · {t["parts"]} parts · {t["step_mb"]} MB · evidence: {t["evidence"]}</small></h2>'
                     f'<p class="k">{html.escape((r.get("record") or {}).get("key") or "")}</p><div class="imgs">{imgs}</div><ul>{fnd}</ul></section>')
    page = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>db1 STEP verification</title><style>
:root{{--bg:#fafafa;--fg:#1b1b1b;--card:#fff;--mut:#666;--line:#ddd}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151515;--fg:#eee;--card:#1f1f1f;--mut:#aaa;--line:#333}}}}
body{{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;margin:0;padding:16px;max-width:1500px;margin:auto}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 16px;margin:14px 0}}
h2{{font-size:16px;margin:4px 0}} small{{color:var(--mut);font-weight:400}} .k{{color:var(--mut);font-size:12px;word-break:break-all;margin:2px 0 8px}}
.v{{color:#fff;border-radius:4px;padding:1px 7px;font-size:13px}} .imgs{{display:flex;gap:8px;flex-wrap:wrap}}
.imgs img{{max-width:min(100%,720px);border:1px solid var(--line);border-radius:4px}} li.FAIL b{{color:#b3261e}} li.WARN b{{color:#a86b00}}
li.INFO{{color:var(--mut)}} .cause{{font-size:11px;border:1px solid var(--line);border-radius:3px;padding:0 4px}}
pre{{white-space:pre-wrap}}</style></head><body><h1>db1 → STEP verification</h1><pre>{html.escape(chr(10).join(L[:20]))}</pre>{''.join(cards)}</body></html>"""
    open(os.path.join(out_dir, f"report{suffix}.html"), "w", encoding="utf-8").write(page)
    return os.path.join(out_dir, f"summary{suffix}.md")
