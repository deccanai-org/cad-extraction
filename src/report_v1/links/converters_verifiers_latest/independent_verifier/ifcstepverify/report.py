"""Summaries from results.jsonl: summary.csv, summary.md (Slack-friendly table), report.html."""
import os, json, csv, html, collections, datetime

CODE_TEXT = {
 "F_EMPTY": "empty file", "F_COMPRESSED": "compressed file", "F_NOT_STEP": "not a STEP file", "F_TRUNCATED": "file cut off",
 "F_NOT_GEOMETRY": "CIS/2, no geometry", "F_SCHEMA": "no geometry schema", "F_NO_GEOMETRY": "no geometry entities",
 "F_SHA_MISMATCH": "checksum differs from manifest", "F_SIZE_MISMATCH": "size differs from manifest", "W_NOT_IN_MANIFEST": "not in manifest",
 "W_NO_SOURCE": "no source IFC", "W_WEAK_SOURCE": "weak source match", "W_MISSING_PIPELINE": "elements dropped by pipeline",
 "W_EXTRA_PARTS": "extra parts not in IFC", "W_SURFACES_ONLY": "surfaces only, no solids", "W_OPEN_SHELL_PIPELINE": "open shells (pipeline)",
 "W_OPEN_SHELL_SOURCE": "open shells (source)", "W_OPEN_SHELL_UNCLASSIFIED": "open shells (unclassified)",
 "W_BROKEN_SOLID_PIPELINE": "broken solids (pipeline)", "W_BROKEN_SOLID_SOURCE": "broken solids (source)", "W_BROKEN_SOLID_UNCLASSIFIED": "broken solids (unclassified)",
 "W_EMPTY_PART_PIPELINE": "empty parts", "W_EMPTY_PART_UNCLASSIFIED": "empty parts (unclassified)", "W_BREPCHECK": "solids fail BRepCheck",
 "W_SIZE": "size differs from IFC", "W_VOLUME": "volume differs from IFC", "W_GEOMETRY_ERROR": "geometry could not be analysed",
 "E_TIMEOUT": "verification timed out", "E_RUN": "verifier error", "E_PACKAGE": "package could not be prepared"}


def build(results_jsonl, out_dir):
    last = {}
    for l in open(results_jsonl, encoding="utf-8"):
        r = json.loads(l); last[r["step_key"]] = r
    rows = [last[k] for k in sorted(last)]
    V = collections.Counter(r["verdict"] for r in rows)
    pipe = sum(bool(r.get("pipeline_issue")) for r in rows)
    src_only = sum(1 for r in rows if r["verdict"] == "WARN" and not r.get("pipeline_issue"))
    codes = collections.Counter(c for r in rows for c in r.get("codes", []))
    csvp = os.path.join(out_dir, "summary.csv")
    with open(csvp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["verdict", "pipeline_issue", "codes", "info", "writer", "step_elements", "source", "overlap", "bytes", "step_key", "error"])
        for r in rows: w.writerow([r["verdict"], r.get("pipeline_issue"), " ".join(r.get("codes", [])), " ".join(r.get("info", [])), r.get("writer"),
                                   r.get("step_elements"), r.get("source"), r.get("overlap"), r.get("bytes"), r["step_key"], r.get("error", "")])
    table = [("PASS", V["PASS"]), ("WARN (pipeline issue)", sum(1 for r in rows if r["verdict"] == "WARN" and r.get("pipeline_issue"))),
             ("WARN (source issue only)", src_only), ("FAIL", V["FAIL"]), ("OUT OF SCOPE (not IFC->STEP)", V["OUT_OF_SCOPE"]), ("ERROR (not verified)", V["ERROR"])]
    table = [t for t in table if t[1] or t[0] in ("PASS", "FAIL")] + [("Total", len(rows))]
    wd = max(len(a) for a, _ in table) + 3
    md = ["```", "Result".ljust(wd) + "Count"] + [a.ljust(wd) + str(b).rjust(5) for a, b in table] + ["```", "",
          "```", "Issue".ljust(40) + "Files"] + [CODE_TEXT.get(c, c).ljust(40) + str(n).rjust(5) for c, n in codes.most_common()] + ["```"]
    mdp = os.path.join(out_dir, "summary.md"); open(mdp, "w", encoding="utf-8").write("\n".join(md) + "\n")
    E = lambda s: html.escape("" if s is None else str(s))
    H = ["<!DOCTYPE html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>IFC to STEP Verification</title>",
         "<style>:root{--bg:#f7f7f5;--p:#fff;--i:#1c1c1a;--m:#6a6862;--l:#e2e0da;--ok:#1f7a4d;--w:#a86412;--b:#b3261e}@media (prefers-color-scheme:dark){:root{--bg:#151618;--p:#1d1f22;--i:#e8e6e1;--m:#9b978f;--l:#32353a;--ok:#5cc28f;--w:#e0a45a;--b:#ef8a82}}"
         "body{margin:0;background:var(--bg);color:var(--i);font:14px/1.5 system-ui,sans-serif}.wrap{max-width:1300px;margin:0 auto;padding:28px 16px}table{border-collapse:collapse;width:100%;background:var(--p)}"
         "th,td{border-bottom:1px solid var(--l);padding:6px 8px;text-align:left;vertical-align:top}th{font-size:11px;text-transform:uppercase;color:var(--m)}.PASS{color:var(--ok);font-weight:700}.WARN{color:var(--w);font-weight:700}"
         ".FAIL,.ERROR{color:var(--b);font-weight:700}code{font-size:12px;word-break:break-all}.box{overflow-x:auto;border:1px solid var(--l);border-radius:8px}</style></head><body><div class=wrap>",
         f"<h1>IFC to STEP verification</h1><p>{len(rows)} STEP files, {datetime.datetime.utcnow():%Y-%m-%d %H:%M} UTC. {pipe} with a pipeline or packaging issue.</p>",
         "<div class=box><table><tr><th>result</th><th>count</th></tr>" + "".join(f"<tr><td>{E(a)}</td><td>{b}</td></tr>" for a, b in table) + "</table></div>",
         "<h2>Issues</h2><div class=box><table><tr><th>code</th><th>issue</th><th>files</th></tr>" + "".join(f"<tr><td>{E(c)}</td><td>{E(CODE_TEXT.get(c, c))}</td><td>{n}</td></tr>" for c, n in codes.most_common()) + "</table></div>",
         "<h2>Files</h2><div class=box><table><tr><th>result</th><th>pipeline</th><th>issues</th><th>writer</th><th>elements</th><th>source IFC</th><th>STEP</th></tr>"]
    for r in rows:
        H.append(f"<tr><td class={E(r['verdict'])}>{E(r['verdict'])}</td><td>{'YES' if r.get('pipeline_issue') else 'no'}</td><td>{E(', '.join(CODE_TEXT.get(c, c) for c in r.get('codes', [])) or r.get('error', '-'))}</td>"
                 f"<td>{E(r.get('writer'))}</td><td>{E(r.get('step_elements'))}</td><td><code>{E(r.get('source'))}</code></td><td><code>{E(r['step_key'])}</code></td></tr>")
    H.append("</table></div><p>Per-file detail: files/&lt;path&gt;/&lt;stem&gt;.json and _elements.csv in the output prefix.</p></div></body></html>")
    hp = os.path.join(out_dir, "report.html"); open(hp, "w", encoding="utf-8").write("\n".join(H))
    return [csvp, mdp, hp]
