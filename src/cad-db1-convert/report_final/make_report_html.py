"""Render the private completion report (HTML) from ./out: summary.json, db1_not_converted.csv,
ifc_not_converted.csv, extraction_*.csv, leftovers_extraction.json, extra.json (notes, repairs, fleet)."""
import csv, html, json, os, collections
HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, "out")
S = json.load(open(os.path.join(OUT, "summary.json")))
PUB = json.load(open(os.path.join(OUT, "conversions.json")))
X = json.load(open(os.path.join(OUT, "extra.json"))) if os.path.exists(os.path.join(OUT, "extra.json")) else {}
def rows(name):
    p = os.path.join(OUT, name)
    return list(csv.DictReader(open(p, newline=""))) if os.path.exists(p) else []
db1 = rows("db1_not_converted.csv"); ifc = rows("ifc_not_converted.csv")
enc = rows("extraction_encrypted_nested_zips.csv"); uno = rows("extraction_unopenable_nested_archives.csv")
rc2 = rows("extraction_7zip_fatal_partial.csv"); dmg = rows("extraction_damaged_nested_archives.csv")
E = html.escape
def n(v): return f"{int(v):,}" if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()) else E(str(v))
def mb(b):
    try: b = int(b)
    except Exception: return ""
    return f"{b/1e6:,.1f} MB" if b >= 1e5 else f"{b/1e3:,.0f} KB"

d = S["db1"]; i = S["ifc"]; st = PUB["step_in_dataset"]; pk = PUB["packaging"]; ex = S["extraction"]
db1_by = collections.Counter(r["reason"] for r in db1); db1_txt = {r["reason"]: r["reason_text"] for r in db1}
ifc_by = collections.Counter(r["reason"] for r in ifc); ifc_txt = {r["reason"]: r["reason_text"] for r in ifc}
enc_by_arch = collections.defaultdict(lambda: [0, 0])
for r in enc: enc_by_arch[r["source_archive"]][0] += 1; enc_by_arch[r["source_archive"]][1] += int(r["locked_files"] or 0)

def table(head, body, cls=""):
    return (f'<div class="tw"><table class="{cls}"><thead><tr>' + "".join(f"<th>{h}</th>" for h in head) + "</tr></thead><tbody>"
            + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in body) + "</tbody></table></div>")

def listing(id_, head, body, note=""):
    return (f'<div class="listing"><div class="lhead"><label for="q-{id_}">Filter</label>'
            f'<input id="q-{id_}" type="search" placeholder="archive, file, version, reason…" data-target="t-{id_}">'
            f'<span class="count" id="c-{id_}">{len(body):,} rows</span></div>{note}'
            + table(head, body, f"list t-{id_}") + "</div>")

COV = S.get("db1_coverage") or {}; CL = (S.get("packaging") or {}).get("cleanup") or {}
tiles = [
    ("STEP files in the dataset", st.get("total"), f'{n(st.get("native"))} native · {n(st.get("from_ifc"))} from IFC · {n(st.get("from_db1"))} from DB1'),
    ("Tekla DB1 → STEP", d["outcomes"].get("ok", 0), f'of {n(d["distinct_files"])} DB1 files in scope'),
    ("IFC → STEP", i["outcomes"].get("ok", 0), f'of {n(i["distinct_files"])} distinct IFC files'),
    ("Projects", pk.get("projects_total"), f'{n(pk.get("projects_3d"))} in main/3d · {n(pk.get("projects_2d"))} in main/2d'),
]
db1_reason_rows = [[E(db1_txt.get(k, k)), n(v)] for k, v in db1_by.most_common()]
ifc_reason_rows = [[E(ifc_txt.get(k, k)), n(v)] for k, v in ifc_by.most_common()]
ver_rows = [[("No banner" if v == "None" else f"Tekla {E(v)}"), n(c.get("files", 0)), n(c.get("converted", 0)), n(c.get("not_converted", 0))]
            for v, c in sorted(d["by_version"].items(), key=lambda kv: (float(kv[0]) if kv[0].replace(".", "").isdigit() else 99))]
db1_list = [[E(r["tekla_version"]), E(r["source_archive"]), f'<span class="path">{E(r["path_in_archive"])}</span>', mb(r["db1_bytes"]),
             E(r["reason_text"]), f'<span class="dim">{E(r["detail"])}</span>', f'<code>{E(r["sha256"][:12])}</code>'] for r in db1]
ifc_list = [[E(r["project"]), f'<span class="path">{E(r["file"])}</span>', mb(r["ifc_bytes"]), E(r["reason_text"]),
             f'<span class="dim">{E(r.get("detail") or "")}</span>', f'<code>{E(r["id"][:12])}</code>'] for r in ifc]
enc_list = [[E(a), n(c[0]), n(c[1])] for a, c in sorted(enc_by_arch.items(), key=lambda kv: -kv[1][1])]
enc_detail = [[E(r["source_archive"]), f'<span class="path">{E(r["nested_zip"])}</span>', n(r["locked_files"]), f'<span class="dim">{E(r["locked_files_sample"][:200])}</span>'] for r in enc]
uno_list = [[E(r["source_archive"]), f'<span class="path">{E(r["nested_archive"])}</span>', E("inside a nested archive" if r["depth"] == "nested:d2" else "in the archive"), f'<span class="dim">{E(r["seven_zip_message"])}</span>'] for r in uno]
dmg_list = [[E(r["source_archive"]), E(r["problem"]), f'<span class="path">{E(r["files_not_extracted"])}</span>', f'<span class="dim">{E(r["seven_zip_message"])}</span>'] for r in dmg]
rc2_list = [[E(r["source_archive"]), n(r["rc2_events"]), n(r["stored_files"])] for r in rc2]
repairs = X.get("repairs", []); fleet = X.get("fleet", []); notes = X.get("notes", []); gen = S["generated_at"]
corrections = X.get("corrections", [])
cov_rows = [["DB1 files in the packaged dataset", n(COV.get("packaged_db1_files", 0)), "every copy, all projects"],
            ["… byte-distinct", n(COV.get("packaged_db1_distinct", 0)), ""],
            ["… of which Tekla model databases", n(COV.get("model_db1_distinct_in_dataset", 0)), "all attempted (below)"],
            ["… of which xslib.db1 component libraries", n(COV.get("xslib_library_distinct", 0)), "not a model: not converted"],
            ["Model DB1 attempted by the original pipeline", n(COV.get("attempted_by_original_pipeline", 0)), f'{n(COV.get("old_pipeline_step_ok", 0))} converted there'],
            ["Model DB1 never attempted, found in this check", n(COV.get("found_never_attempted", 0)), "added to this run and converted"],
            ["Model DB1 with a STEP now", n(COV.get("models_with_step", 0)), f'of {n(COV.get("model_db1_distinct_all", 0))} distinct model files']]
found = [[E(r["tekla_version"]), E(r["source_archive"]), f'<span class="path">{E(r["path_in_archive"])}</span>', mb(r["db1_bytes"]),
          f'<code>{E(r["sha256"][:12])}</code>'] for r in (COV.get("found_list") or [])]

page = f"""<meta charset="utf-8">
<title>CAD STEP Completion Report</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Semi+Condensed:wght@500;600;700&family=Source+Sans+3:wght@400;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root {{ --ground:#f3f4f2; --paper:#fbfbfa; --ink:#1c2530; --soft:#55616d; --line:#d6dad9; --steel:#6b7a86; --accent:#a8412c;
  --good:#2e7658; --warn:#9a6a14; --chip:#e8ebea; color-scheme: light; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --ground:#11161b; --paper:#171d23; --ink:#e4e8eb; --soft:#9aa6b1;
  --line:#2b343d; --steel:#8b99a5; --accent:#e07a5f; --good:#5fb892; --warn:#d8a54a; --chip:#222a31; color-scheme: dark; }} }}
:root[data-theme="dark"] {{ --ground:#11161b; --paper:#171d23; --ink:#e4e8eb; --soft:#9aa6b1; --line:#2b343d; --steel:#8b99a5;
  --accent:#e07a5f; --good:#5fb892; --warn:#d8a54a; --chip:#222a31; color-scheme: dark; }}
body {{ background:var(--ground); color:var(--ink); font:16px/1.55 "Source Sans 3", "Segoe UI", system-ui, sans-serif; }}
.wrap {{ max-width:1120px; margin:0 auto; padding-inline:clamp(16px,4vw,40px); padding-block:28px 64px; }}
h1,h2,h3 {{ font-family:"Barlow Semi Condensed", "Arial Narrow", sans-serif; text-wrap:balance; margin:0; }}
h1 {{ font-size:clamp(28px,4.4vw,40px); font-weight:700; letter-spacing:.01em; }}
h2 {{ font-size:26px; font-weight:600; margin-top:44px; padding-bottom:8px; border-bottom:2px solid var(--ink); }}
h3 {{ font-size:19px; font-weight:600; margin:26px 0 10px; }}
p {{ max-width:72ch; }} .dim {{ color:var(--soft); }} code,.mono {{ font-family:"IBM Plex Mono", ui-monospace, monospace; font-size:.86em; }}
.titleblock {{ display:grid; grid-template-columns:2.2fr 1fr 1fr 1fr; border:2px solid var(--ink); background:var(--paper); }}
.titleblock > div {{ padding:10px 14px; border-left:1px solid var(--ink); display:grid; gap:2px; }}
.titleblock > div:first-child {{ border-left:0; }}
.titleblock .lbl {{ font:600 11px/1.2 "IBM Plex Mono", monospace; letter-spacing:.08em; text-transform:uppercase; color:var(--soft); }}
.titleblock .val {{ font-family:"Barlow Semi Condensed", sans-serif; font-size:18px; font-weight:600; }}
.lede {{ margin:18px 0 0; color:var(--soft); }}
.tiles {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:12px; margin-top:22px; }}
.tile {{ background:var(--paper); border:1px solid var(--line); padding:14px 16px; display:grid; gap:4px; }}
.tile .k {{ font:600 12px/1.2 "IBM Plex Mono", monospace; text-transform:uppercase; letter-spacing:.07em; color:var(--soft); }}
.tile .v {{ font-family:"Barlow Semi Condensed", sans-serif; font-size:34px; font-weight:700; font-variant-numeric:tabular-nums; }}
.tile .s {{ color:var(--soft); font-size:14px; }}
.note {{ border-left:3px solid var(--accent); background:var(--paper); padding:10px 14px; margin:14px 0; max-width:80ch; }}
.grid2 {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:18px; align-items:start; }}
.tw {{ overflow-x:auto; border:1px solid var(--line); background:var(--paper); }}
table {{ border-collapse:collapse; width:100%; font-size:14px; }}
th,td {{ text-align:left; padding:7px 10px; border-bottom:1px solid var(--line); vertical-align:top; }}
th {{ font:600 12px/1.3 "IBM Plex Mono", monospace; text-transform:uppercase; letter-spacing:.05em; color:var(--soft); background:var(--chip); position:sticky; top:0; }}
td {{ font-variant-numeric:tabular-nums; }} td:last-child, th:last-child {{ white-space:nowrap; }}
.path {{ font-family:"IBM Plex Mono", monospace; font-size:12px; word-break:break-all; }}
.listing {{ margin-top:10px; }} .lhead {{ display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin-bottom:8px; }}
.lhead label {{ font:600 12px "IBM Plex Mono", monospace; text-transform:uppercase; letter-spacing:.06em; color:var(--soft); }}
.lhead input {{ flex:1 1 260px; max-width:420px; padding:7px 10px; border:1px solid var(--line); background:var(--paper); color:var(--ink); font:inherit; }}
.lhead input:focus-visible {{ outline:2px solid var(--accent); outline-offset:1px; }}
.count {{ font:12px "IBM Plex Mono", monospace; color:var(--soft); }}
.listing .tw {{ max-height:520px; overflow:auto; }}
ul.plain {{ padding-left:18px; }} ul.plain li {{ margin:4px 0; max-width:80ch; }}
.pill {{ display:inline-block; font:600 11px/1 "IBM Plex Mono", monospace; letter-spacing:.05em; padding:4px 7px; border:1px solid currentColor; }}
.pill.good {{ color:var(--good); }} .pill.warn {{ color:var(--warn); }} .pill.bad {{ color:var(--accent); }}
footer {{ margin-top:48px; color:var(--soft); font-size:13px; }}
@media (max-width:720px) {{ .titleblock {{ grid-template-columns:1fr 1fr; }} .titleblock > div:first-child {{ grid-column:1 / -1; }}
  .titleblock > div {{ border-left:0; border-top:1px solid var(--ink); }} .titleblock > div:first-child {{ border-top:0; }} }}
</style>
<div class="wrap">
<div class="titleblock">
  <div><span class="lbl">Project</span><span class="val">CAD extraction · STEP conversion &amp; packaging</span></div>
  <div><span class="lbl">Scope</span><span class="val">Disk-1 + Disk-2</span></div>
  <div><span class="lbl">Issued</span><span class="val mono">{E(gen[:16].replace("T", " "))}Z</span></div>
  <div><span class="lbl">Status</span><span class="val">{"Final" if S.get("final") else "Preliminary"}</span></div>
</div>
<p class="lede">What was converted and packaged, and the complete list of what was not converted, not packaged, or could not be opened during extraction, with the reason for each file.</p>
<div class="tiles">{"".join(f'<div class="tile"><span class="k">{E(k)}</span><span class="v">{n(v)}</span><span class="s">{s}</span></div>' for k, v, s in tiles)}</div>
{"".join(f'<div class="note">{t}</div>' for t in notes)}

<h2 id="coverage">Tekla DB1 coverage across all archives</h2>
<p>Every DB1 file in the packaged dataset was matched against every conversion attempt (by SHA-256 where the file was hashed, otherwise by S3 content identity, with size-only matches re-hashed). Every Tekla model database has now been attempted. The files left out are Tekla's per-model component libraries (<code>xslib.db1</code>). They hold custom-component definitions, not the building model, and the original pipeline skipped them too.</p>
{table(["", "Files", ""], cov_rows)}
<h3>Model DB1 files no converter had attempted: {n(len(found))}</h3>
<p class="dim">Mostly inside nested zips or in archives extracted after the original converter took its file list. All of them were converted in this run.</p>
{listing("found", ["Version", "Archive", "File inside archive", "Size", "SHA-256"], found)}

<h2 id="db1">Tekla DB1 → STEP: not converted</h2>
<p>{n(d["distinct_files"])} byte-distinct DB1 files were in scope: every file the original converter reported as unsupported or failed, the 40 it never attempted, and 1 it left unfinished. {n(d["outcomes"].get("ok", 0))} converted and passed the checks; {n(len(db1))} did not. No STEP is written for a file unless the decoded model passes its checks, so no file below has a guessed model in the dataset.</p>
<div class="grid2"><div>{table(["Reason", "Files"], db1_reason_rows)}</div><div>{table(["Version", "Files", "Converted", "Not"], ver_rows)}</div></div>
{listing("db1", ["Version", "Archive", "File inside archive", "Size", "Reason", "Detail", "SHA-256"], db1_list)}

<h2 id="ifc">IFC → STEP: not converted</h2>
<p>{n(i["distinct_files"])} byte-distinct IFC files. {n(i["outcomes"].get("ok", 0))} converted; {n(len(ifc))} did not. Every file below was inspected; the reason is what the file itself shows.</p>
{table(["Reason", "Files"], ifc_reason_rows)}
{listing("ifc", ["Project", "File", "Size", "Reason", "Detail", "ID"], ifc_list)}

<h2 id="extraction">Not opened during extraction</h2>
<p>All {n(ex.get("archives_total", 3620))} archives completed. Inside them, the content below could not be opened. Everything readable around it was extracted and packaged. Each path is the folder path inside its source archive, and <code>→</code> marks a path inside a nested archive.</p>
<div class="note">Coverage: these lists come from the EC2 extraction pipeline, which recorded every locked or unreadable nested archive for the {n(ex.get("archives_scanned_ec2_era"))} archives it processed. The 2,507 archives completed earlier by the baseline pipeline recorded only explicit errors ({n(ex.get("baseline_explicit_failure_events"))} events, all on archives that later completed), not nested-archive details.</div>
<h3>Password-protected nested zips: {n(ex["encrypted"]["nested_zips"])} zips in {n(ex["encrypted"]["archives"])} archives, {n(ex["encrypted"]["member_files_locked"])} files locked</h3>
{listing("enc", ["Archive", "Locked zips", "Locked files"], enc_list)}
{listing("encd", ["Archive", "Locked nested zip (folder path inside the archive)", "Files", "Sample of locked files"], enc_detail)}
<h3>Nested archives 7-Zip cannot open at all: {n(len(uno))} in {n(len({r["source_archive"] for r in uno}))} archives</h3>
<p class="dim">Mostly .rar files that 7-Zip reports as not an archive: damaged, or not really RAR. Nothing inside them was extracted; the files around them were.</p>
{listing("uno", ["Archive", "Nested archive (folder path inside the archive)", "Where", "7-Zip message"], uno_list)}
<h3>Damaged nested archives, partly extracted: {n(len(dmg))} in {n(len({r["source_archive"] for r in dmg}))} archives</h3>
<p class="dim">Cut short or failing a CRC or header check. Everything readable was extracted; the files named here were not.</p>
{listing("dmg", ["Archive", "Problem", "Files not extracted", "7-Zip message"], dmg_list)}
<h3>7-Zip fatal errors with partial content kept: {n(ex["sevenzip_fatal_accepted_partial"]["events"])} events in {n(len(rc2))} archives</h3>
{listing("rc2", ["Archive", "Events", "Files stored"], rc2_list)}

<h2 id="repairs">Repairs made so outputs are correct</h2>
<ul class="plain">{"".join(f"<li>{t}</li>" for t in repairs)}</ul>

<h2 id="corrections">Packaging corrections made at the end</h2>
<ul class="plain">{"".join(f"<li>{t}</li>" for t in corrections)}</ul>

<h2 id="fleet">Machines</h2>
<ul class="plain">{"".join(f"<li>{t}</li>" for t in fleet)}</ul>
<footer>Generated {E(gen)} · source lists: db1_not_converted.csv, ifc_not_converted.csv, extraction_*.csv (same folder)</footer>
</div>
<script>
document.querySelectorAll('.lhead input[type=search]').forEach(inp => {{
  const t = document.querySelector('table.' + inp.dataset.target); const c = document.getElementById('c-' + inp.dataset.target.slice(2));
  const rs = t ? [...t.tBodies[0].rows] : [];
  inp.addEventListener('input', () => {{
    const q = inp.value.trim().toLowerCase(); let k = 0;
    rs.forEach(r => {{ const hit = !q || r.textContent.toLowerCase().includes(q); r.hidden = !hit; if (hit) k++; }});
    if (c) c.textContent = k.toLocaleString() + ' of ' + rs.length.toLocaleString() + ' rows';
  }});
}});
</script>
"""
open(os.path.join(OUT, "CAD_STEP_Completion_Report.html"), "w").write(page)
print("report rows: db1", len(db1), "ifc", len(ifc), "enc", len(enc), "uno", len(uno), "rc2", len(rc2), "bytes", len(page))
