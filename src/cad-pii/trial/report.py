#!/usr/bin/env python3
"""Build trial/report.html + trial/report.json from work/results/*.json. LOCAL ONLY (contains PII)."""
import glob
import html
import json
import os
from collections import Counter

T = os.path.dirname(os.path.abspath(__file__))


def esc(x):
    return html.escape(str(x))


def ok(b):
    return f'<span class="{"ok" if b else "bad"}">{"PASS" if b else "FAIL"}</span>'


def main():
    recs = [json.load(open(f)) for f in sorted(glob.glob(os.path.join(T, "work", "results", "s*.json")))]
    cat_tot = Counter()
    src_tot = Counter()
    rows = []
    total_cost = total_pt = total_ct = 0
    for r in recs:
        boxes = [b for p in r["pagesinfo"] for b in p["boxes"]]
        cats = Counter(b["cat"] for b in boxes)
        cat_tot.update(cats)
        src_tot.update(b["src"].split(":")[0] for b in boxes)
        cost = sum((x.get("cost") or 0) for x in r["llm"])
        pt = sum((x.get("prompt_tokens") or 0) for x in r["llm"])
        ct = sum((x.get("completion_tokens") or 0) for x in r["llm"])
        total_cost += cost; total_pt += pt; total_ct += ct
        rows.append((r, boxes, cats, cost, pt, ct))
    n = len(recs)
    rem_ok = sum(r["verify_removed"]["removed_ok"] for r in recs)
    col_ok = sum(r["verify_collateral"]["collateral_ok"] for r in recs)
    ctl_ok = sum(r["control_fails_as_expected"] for r in recs)
    summary = {"files": n, "boxes_total": sum(len(b) for _, b, *_ in rows), "boxes_by_category": dict(cat_tot),
               "boxes_by_source": dict(src_tot), "removed_ok": rem_ok, "collateral_ok": col_ok,
               "negative_control_failed_as_expected": ctl_ok, "llm_cost_usd": round(total_cost, 4),
               "prompt_tokens": total_pt, "completion_tokens": total_ct,
               "model": sorted({m for r in recs for m in r["models"]})}
    json.dump({"summary": summary, "files": recs}, open(os.path.join(T, "report.json"), "w"), indent=1, default=str)

    css = """body{font-family:-apple-system,Helvetica,Arial,sans-serif;margin:24px;color:#222;max-width:1500px}
    table{border-collapse:collapse;font-size:12px;margin:8px 0}td,th{border:1px solid #ccc;padding:3px 6px;vertical-align:top}
    th{background:#f2f2f2}.ok{color:#0a7d24;font-weight:600}.bad{color:#c0161b;font-weight:700}
    .warn{background:#fff4d6;border:1px solid #e8c547;padding:8px;margin:8px 0}
    img{max-width:100%;border:1px solid #999}.file{border-top:3px solid #333;margin-top:36px;padding-top:8px}
    code{font-size:11px}.small{font-size:11px;color:#555}"""
    h = [f"<html><head><meta charset='utf-8'><title>CAD PII trial (LOCAL ONLY)</title><style>{css}</style></head><body>"]
    h.append("<div class='warn'><b>LOCAL ONLY — this report contains PII (before images and detected values). Never publish or upload.</b></div>")
    h.append("<h1>CAD-PDF PII redaction trial — 20 samples</h1>")
    h.append(f"<p>Model: <code>{esc(', '.join(summary['model']))}</code> (served only by Alibaba Cloud on OpenRouter; "
             f"<b>title-block crops and word lists were processed by Alibaba Cloud without a confirmed zero-retention (ZDR) policy</b> — "
             f"owner's explicit choice for this trial; requests carried data_collection=deny, no zdr flag). Total LLM cost ${total_cost:.3f}, {total_pt:,} prompt / {total_ct:,} completion tokens.</p>")
    h.append("<h2>Summary</h2><table><tr><th>files</th><th>boxes</th><th>PII removed (verify)</th><th>collateral clean</th>"
             "<th>negative control fails</th><th>LLM $</th></tr>")
    h.append(f"<tr><td>{n}</td><td>{summary['boxes_total']}</td><td>{rem_ok}/{n}</td><td>{col_ok}/{n}</td><td>{ctl_ok}/{n}</td><td>{total_cost:.3f}</td></tr></table>")
    h.append("<p>Boxes by category: " + ", ".join(f"{k} {v}" for k, v in cat_tot.most_common()) + "<br>Boxes by source: " +
             ", ".join(f"{k} {v}" for k, v in src_tot.most_common()) + "</p>")
    h.append("<table><tr><th>id</th><th>disk</th><th>producer</th><th>words (kinds)</th><th>TB</th><th>boxes</th><th>categories</th>"
             "<th>removed</th><th>glyphs in box</th><th>regex left</th><th>values left</th><th>pix resid.</th><th>stroke resid.</th>"
             "<th>collateral</th><th>words miss/add</th><th>drawings miss/extra</th><th>px changed</th><th>imgs</th><th>control fails</th>"
             "<th>LLM s</th><th>$</th></tr>")
    for r, boxes, cats, cost, pt, ct in rows:
        vr, vc = r["verify_removed"], r["verify_collateral"]
        p0 = r["pagesinfo"][0]
        lat = sum((x.get("latency_s") or 0) for x in r["llm"])
        h.append(f"<tr><td><a href='#{r['id']}'>{r['id']}</a></td><td>{esc(r['disk'])}</td><td>{esc(r['producer'][:28])}</td>"
                 f"<td>{esc(p0['word_kinds'])}</td><td>{esc(p0['tb_kind'])}</td><td>{len(boxes)}</td>"
                 f"<td>{esc(', '.join(f'{k} {v}' for k, v in cats.most_common()))}</td><td>{ok(vr['removed_ok'])}</td>"
                 f"<td>{vr['glyphs_in_boxes']}</td><td>{vr['regex_hits_remaining']}</td><td>{len(vr['values_remaining'])}</td>"
                 f"<td>{vr['pixel_residual_boxes']}</td><td>{vr['stroke_residual_boxes']}</td><td>{ok(vc['collateral_ok'])}</td>"
                 f"<td>{vc['words_missing_outside']}/{vc['words_added']}</td><td>{vc['drawings_missing_outside']}/{vc['drawings_extra_outside']}</td>"
                 f"<td>{vc['render_px_changed_outside']}</td><td>{ok(vc['images_equal'])}</td><td>{ok(r['control_fails_as_expected'])}</td>"
                 f"<td>{lat:.0f}</td><td>{cost:.3f}</td></tr>")
    h.append("</table>")
    for r, boxes, cats, cost, pt, ct in rows:
        name = r["file"][:-4]
        vr, vc, cc = r["verify_removed"], r["verify_collateral"], r["verify_control"]
        h.append(f"<div class='file' id='{r['id']}'><h2>{r['id']} — {esc(r['file'])}</h2>")
        h.append(f"<p class='small'>source: <code>s3://bim-proprietary-data/{esc(r['key'])}</code><br>disk: {esc(r['disk'])} | producer: "
                 f"{esc(r['producer'])} | creator: {esc(r['creator'])} | pages: {r['pages']}</p>")
        for p in r["pagesinfo"]:
            h.append(f"<p class='small'>page {p['page']}: TB detection <b>{esc(p['tb_kind'])}</b>, zones {esc(p['zones'])}, words {esc(p['word_kinds'])}, "
                     f"raster={p['raster']}, OCR={esc(p['ocr'])}, visual candidates {p['n_vis']}, regex hits {p['n_regex']}, propagated {p['n_prop']}</p>")
        h.append(f"<p><b>Before | after — title block</b> (<a href='compare/{esc(name)}/before.pdf'>before.pdf</a>, "
                 f"<a href='compare/{esc(name)}/after.pdf'>after.pdf</a>)<br><img src='compare/{esc(name)}/titleblock_before_after.png'></p>")
        h.append(f"<p><b>Full page before | after</b><br><img style='max-width:1100px' src='compare/{esc(name)}/page_before_after.png'></p>")
        h.append("<table><tr><th>category</th><th>count</th></tr>" + "".join(f"<tr><td>{esc(k)}</td><td>{v}</td></tr>" for k, v in cats.most_common()) + "</table>")
        h.append("<details><summary>boxes (value, category, source, mode)</summary><table><tr><th>text</th><th>cat</th><th>src</th><th>mode</th><th>kinds</th></tr>")
        for b in boxes:
            h.append(f"<tr><td>{esc(b['text'][:80])}</td><td>{esc(b['cat'])}</td><td>{esc(b['src'])}</td><td>{esc(b['mode'])}{' +img' if b['img'] else ''}</td><td>{esc(b['kinds'])}</td></tr>")
        h.append("</table></details>")
        h.append(f"<p>Metadata blanked: {esc(r['metadata_blanked'])} ({esc(r['meta_changes'])}); annotation authors blanked: {r['annot_authors_blanked']}; "
                 f"annotation contents blanked: {r['annot_contents_blanked']}</p>")
        h.append("<table><tr><th>check</th><th>result</th><th>detail</th></tr>")
        h.append(f"<tr><td>PII removed (overall)</td><td>{ok(vr['removed_ok'])}</td><td></td></tr>")
        h.append(f"<tr><td>no glyph inside any box</td><td>{ok(vr['glyphs_in_boxes'] == 0)}</td><td>{vr['glyphs_in_boxes']}</td></tr>")
        h.append(f"<tr><td>regex hits remaining (text layer)</td><td>{ok(vr['regex_hits_remaining'] == 0)}</td><td>{vr['regex_hits_remaining']} {esc(vr['regex_examples'])} (text-layer words: {vr['text_layer_words']})</td></tr>")
        h.append(f"<tr><td>redacted values absent from page text / metadata / annots</td><td>{ok(not vr['values_remaining'])}</td><td>{esc([(x['value'][:40], x['where']) for x in vr['values_remaining']][:8])}</td></tr>")
        h.append(f"<tr><td>image pixels uniform in raster boxes</td><td>{ok(vr['pixel_residual_boxes'] == 0)}</td><td>{vr['pixel_residual_boxes']}</td></tr>")
        h.append(f"<tr><td>(info) vector strokes left inside stroke boxes</td><td>{'—' if vr['stroke_residual_boxes'] == 0 else '<span class=bad>' + str(vr['stroke_residual_boxes']) + '</span>'}</td><td>SHX / vector text that sits inside a larger path is not removed by REMOVE_IF_COVERED</td></tr>")
        h.append(f"<tr><td>(info) short values (≤3 chars) still present as tokens</td><td>{len(vr.get('short_values_remaining', []))}</td><td>{esc(vr.get('short_values_remaining', [])[:10])}</td></tr>")
        h.append(f"<tr><td>(a) words outside boxes unchanged</td><td>{ok(vc['words_missing_outside'] == 0 and vc['words_added'] == 0)}</td><td>missing {vc['words_missing_outside']}, added {vc['words_added']}</td></tr>")
        h.append(f"<tr><td>(b) drawings outside boxes unchanged</td><td>{ok(vc['drawings_missing_outside'] == 0 and vc['drawings_extra_outside'] == 0)}</td><td>missing {vc['drawings_missing_outside']}, extra {vc['drawings_extra_outside']}</td></tr>")
        h.append(f"<tr><td>(c) 60 dpi render outside boxes (+2pt)</td><td>{ok(vc['render_px_changed_outside'] == 0)}</td><td>{vc['render_px_changed_outside']} px changed (&gt;24/255); {vc['render_px_anydiff_outside']} px with any difference</td></tr>")
        h.append(f"<tr><td>(d) image count and dims</td><td>{ok(vc['images_equal'])}</td><td></td></tr>")
        e = all(vc[k] for k in ("pages_equal", "rotation_equal", "annots_equal", "ocgs_equal", "toc_equal", "embedded_equal", "widgets_equal"))
        h.append(f"<tr><td>(e) pages, rotation, annots, OCGs, TOC, embedded, widgets</td><td>{ok(e)}</td><td>{esc({k: vc[k] for k in ('pages_equal', 'rotation_equal', 'annots_equal', 'ocgs_equal', 'toc_equal', 'embedded_equal', 'widgets_equal')})}</td></tr>")
        h.append(f"<tr><td>negative control (cosmetic rectangles) must FAIL removal</td><td>{ok(r['control_fails_as_expected'])}</td><td>control: glyphs {cc['glyphs_in_boxes']}, regex {cc['regex_hits_remaining']}, values {len(cc['values_remaining'])}, pix {cc['pixel_residual_boxes']}</td></tr>")
        if vc.get("examples"):
            h.append(f"<tr><td>collateral examples</td><td></td><td>{esc(vc['examples'])}</td></tr>")
        h.append("</table>")
        for x in r["llm"]:
            h.append(f"<p class='small'>LLM <code>{esc(x['model'])}</code> via {esc(x.get('provider'))}: {x.get('latency_s')} s, "
                     f"{x.get('prompt_tokens')} prompt + {x.get('completion_tokens')} completion tokens, ${(x.get('cost') or 0):.4f}; "
                     f"ids returned {x['total_ids']}, invalid {x['invalid_ids']}; parsed={x['parsed_ok']}"
                     f"{'; error: ' + esc(x['error']) if x.get('error') else ''}; model note on missed PII: {esc(x.get('missed') or '')}</p>")
        h.append("</div>")
    h.append("</body></html>")
    open(os.path.join(T, "report.html"), "w").write("\n".join(h))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
