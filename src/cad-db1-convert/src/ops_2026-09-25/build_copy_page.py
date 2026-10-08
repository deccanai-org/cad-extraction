"""Build the copy-friendly page of locked / damaged files from the simple CSVs."""
import csv, json, html, os

S = "/Users/dhiren/Downloads/Deccan/cad-db1-convert/report_final/out/simple"
OUT = "/private/tmp/claude-501/-Users-dhiren-Downloads-Deccan/cc2df5a5-2f05-4112-ac6d-adb750ab0b8a/scratchpad/locked_and_damaged_files.html"
rd = lambda f: list(csv.reader(open(os.path.join(S, f), newline="")))[1:]

t1 = rd("1_Password_locked_by_archive.csv")
t2 = rd("3_Could_not_open_damaged.csv")
t3 = rd("2_Password_locked_zip_files.csv")
zips = sum(int(r[1]) for r in t1); files = sum(int(r[2]) for r in t1)
arch2 = len({r[0] for r in t2})

T = {
    "summary": {"headers": ["What", "Count"], "num": [1],
                "rows": [["Archives received", "3,620"], ["Archives opened and processed", "3,620 (all)"],
                         ["Archives with password-locked files inside", f"{len(t1)}"],
                         ["Password-locked zip files", f"{zips:,} ({files:,} files inside)"],
                         ["Damaged files we could not open", f"{len(t2)} (in {arch2} archives)"]]},
    "locked": {"headers": ["#", "Archive", "Locked zip files", "Files locked inside"], "num": [0, 2, 3],
               "rows": [[str(i), a, f"{int(z):,}", f"{int(f):,}"] for i, (a, z, f) in enumerate(t1, 1)]
                       + [["", f"Total: {len(t1)} archives", f"{zips:,}", f"{files:,}"]]},
    "damaged": {"headers": ["#", "Archive", "Folder inside the archive", "File", "Problem"], "num": [0],
                "rows": [[str(i)] + r for i, r in enumerate(t2, 1)]},
    "allzips": {"headers": ["#", "Archive", "Folder inside the archive", "Locked zip file", "Files locked inside"], "num": [0, 4],
                "rows": [[str(i), r[0], r[1], r[2], f"{int(r[3]):,}"] for i, r in enumerate(t3, 1)]},
}


def table_html(key):
    t = T[key]; num = set(t["num"])
    head = "".join(f'<th scope="col"{" class=n" if i in num else ""}>{html.escape(h)}</th>' for i, h in enumerate(t["headers"]))
    body = []
    for r in t["rows"]:
        tot = key == "locked" and r[0] == ""
        cells = "".join(f'<td{" class=n" if i in num else ""}>{html.escape(c)}</td>' for i, c in enumerate(r))
        body.append(f'<tr{" class=total" if tot else ""}>{cells}</tr>')
    return f'<table id="t-{key}"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>'


def block(key, title, desc, badge=None, fold=False):
    cnt = len(T[key]["rows"]) - (1 if key == "locked" else 0)
    btn = (f'<div class="bar"><button type="button" class="copy" id="copy-{key}" data-key="{key}">Copy table</button>'
           f'<span class="status" id="status-{key}" role="status" aria-live="polite"></span></div>')
    tag = f'<span class="tag {badge}">{"Password-locked" if badge == "locked" else "Damaged"}</span>' if badge else ""
    inner = f'{btn}<div class="tw">{table_html(key)}</div>'
    if fold:
        return (f'<section class="blk" id="{key}"><h2>{html.escape(title)} {tag}</h2><p class="desc">{desc}</p>'
                f'<details id="d-{key}"><summary>Show all {cnt:,} rows</summary>{inner}</details></section>')
    return f'<section class="blk" id="{key}"><h2>{html.escape(title)} {tag}</h2><p class="desc">{desc}</p>{inner}</section>'


page = f"""<title>Locked and Damaged Files</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;600;700&display=swap">
<style>
:root {{ --ground:#f5f6f4; --paper:#ffffff; --ink:#1e2a2e; --soft:#5b6b70; --line:#d5dbda; --head:#eef2f1;
  --accent:#1f6f8b; --accent-ink:#ffffff; --locked:#9b5a0f; --locked-bg:#fbf1e3; --damaged:#a33a2a; --damaged-bg:#fbeae6;
  --good:#2d6e4e; color-scheme: light; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --ground:#12181a; --paper:#192124; --ink:#e3eaec;
  --soft:#9db0b5; --line:#2c393d; --head:#1f292c; --accent:#5fb3d1; --accent-ink:#0d1719; --locked:#e0a45a; --locked-bg:#2c2215;
  --damaged:#e27a66; --damaged-bg:#301b17; --good:#6cc095; color-scheme: dark; }} }}
:root[data-theme="dark"] {{ --ground:#12181a; --paper:#192124; --ink:#e3eaec; --soft:#9db0b5; --line:#2c393d; --head:#1f292c;
  --accent:#5fb3d1; --accent-ink:#0d1719; --locked:#e0a45a; --locked-bg:#2c2215; --damaged:#e27a66; --damaged-bg:#301b17;
  --good:#6cc095; color-scheme: dark; }}
body {{ background:var(--ground); color:var(--ink); font:15px/1.5 "Public Sans", "Segoe UI", system-ui, -apple-system, sans-serif; }}
.wrap {{ max-width:1120px; margin:0 auto; padding-inline:clamp(16px,4vw,40px); padding-block:32px 72px; display:grid; gap:36px; }}
h1 {{ font-size:clamp(26px,3.6vw,34px); font-weight:700; margin:0; letter-spacing:-.01em; text-wrap:balance; }}
h2 {{ font-size:20px; font-weight:700; margin:0; display:flex; flex-wrap:wrap; align-items:center; gap:10px; text-wrap:balance; }}
.intro {{ display:grid; gap:10px; }} .intro p {{ margin:0; max-width:68ch; color:var(--soft); }}
.blk {{ display:grid; gap:12px; }} .desc {{ margin:0; color:var(--soft); max-width:72ch; }}
.tag {{ font-size:12px; font-weight:600; letter-spacing:.04em; text-transform:uppercase; padding:3px 8px; border-radius:4px; }}
.tag.locked {{ color:var(--locked); background:var(--locked-bg); }} .tag.damaged {{ color:var(--damaged); background:var(--damaged-bg); }}
.bar {{ display:flex; flex-wrap:wrap; align-items:center; gap:12px; }}
.copy {{ font:600 14px/1 "Public Sans", system-ui, sans-serif; color:var(--accent-ink); background:var(--accent); border:0;
  border-radius:6px; padding:10px 16px; cursor:pointer; }}
.copy:hover {{ filter:brightness(1.08); }} .copy:focus-visible, summary:focus-visible {{ outline:3px solid var(--accent); outline-offset:2px; }}
.status {{ font-size:14px; color:var(--good); min-height:1em; }}
.tw {{ overflow-x:auto; background:var(--paper); border:1px solid var(--line); border-radius:6px; }}
table {{ border-collapse:collapse; width:100%; font-size:14px; }}
th, td {{ text-align:left; vertical-align:top; padding:8px 12px; border-bottom:1px solid var(--line); overflow-wrap:anywhere; }}
th {{ background:var(--head); font-weight:600; font-size:13px; position:sticky; top:0; }}
.n {{ text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }}
tr.total td {{ font-weight:700; border-bottom:0; }}
details {{ display:grid; gap:12px; }} details[open] > summary {{ margin-bottom:12px; }}
summary {{ cursor:pointer; font-weight:600; color:var(--accent); width:max-content; max-width:100%; }}
#allzips .tw {{ max-height:620px; overflow:auto; }}
.ask {{ margin:0; padding:14px 16px; background:var(--paper); border:1px solid var(--line); border-radius:6px; max-width:80ch; }}
@media (prefers-reduced-motion: reduce) {{ * {{ transition:none !important; }} }}
</style>
<div class="wrap">
  <header class="intro">
    <h1>Locked and Damaged Files</h1>
    <p>Everything in the 3,620 archives was opened and processed, except the files below. Press <strong>Copy table</strong> and paste into an email, a document or a spreadsheet. The table keeps its rows and columns.</p>
  </header>
  {block("summary", "Summary", "Counts across all archives.")}
  {block("locked", "Archives with password-locked files", "Zip files inside these archives are protected by a password, so their contents could not be opened. Everything else in these archives was opened.", "locked")}
  {block("damaged", "Damaged files we could not open", "These files are damaged or are not real archives, so they could not be opened. Where only one file inside a damaged zip was lost, that file is named.", "damaged")}
  <p class="ask"><strong>What we need:</strong> the passwords (or unlocked copies) for the password-locked zip files, and fresh copies of the damaged files.</p>
  {block("allzips", "Every password-locked zip file", f"The exact folder and file name of all {len(t3):,} locked zip files, grouped by archive.", "locked", fold=True)}
</div>
<script>
const T = {json.dumps(T, ensure_ascii=False)};
const esc = s => String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
function asHtml(t) {{
  const cell = "border:1px solid #b9c3c2;padding:4px 8px;vertical-align:top;font-family:Arial,Helvetica,sans-serif;font-size:13px;";
  const num = new Set(t.num);
  const th = t.headers.map((h,i) => `<th style="${{cell}}background:#e8eeed;text-align:${{num.has(i)?"right":"left"}}">${{esc(h)}}</th>`).join("");
  const rows = t.rows.map(r => "<tr>" + r.map((c,i) => `<td style="${{cell}}text-align:${{num.has(i)?"right":"left"}}">${{esc(c)}}</td>`).join("") + "</tr>").join("");
  return `<table style="border-collapse:collapse"><thead><tr>${{th}}</tr></thead><tbody>${{rows}}</tbody></table>`;
}}
const clean = c => String(c).replace(/[\\t\\r\\n]+/g, " ");
const asText = t => [t.headers, ...t.rows].map(r => r.map(clean).join("\\t")).join("\\n");
function selectTable(key) {{
  const d = document.getElementById("d-" + key); if (d) d.open = true;
  const el = document.getElementById("t-" + key), sel = window.getSelection(), rg = document.createRange();
  rg.selectNodeContents(el); sel.removeAllRanges(); sel.addRange(rg);
}}
function say(key, msg) {{
  const s = document.getElementById("status-" + key); s.textContent = msg;
  clearTimeout(s._t); s._t = setTimeout(() => {{ s.textContent = ""; }}, 6000);
}}
document.querySelectorAll("button.copy").forEach(b => b.addEventListener("click", () => {{
  const key = b.dataset.key, t = T[key], h = asHtml(t), txt = asText(t);
  const fallback = () => navigator.clipboard.writeText(txt)
      .then(() => say(key, "Copied. Pastes as columns in Excel or Google Sheets."))
      .catch(() => {{ selectTable(key); say(key, "Table selected. Press Ctrl+C (Cmd+C on a Mac) to copy it."); }});
  try {{
    if (!navigator.clipboard || !window.ClipboardItem) throw new Error("no rich clipboard");
    navigator.clipboard.write([new ClipboardItem({{"text/html": new Blob([h], {{type:"text/html"}}), "text/plain": new Blob([txt], {{type:"text/plain"}})}})])
      .then(() => say(key, "Copied " + (t.rows.length) + " rows. Paste into an email, document or spreadsheet."))
      .catch(fallback);
  }} catch (e) {{
    if (navigator.clipboard) fallback(); else {{ selectTable(key); say(key, "Table selected. Press Ctrl+C (Cmd+C on a Mac) to copy it."); }}
  }}
}}));
</script>
"""
open(OUT, "w").write(page)
print("written", OUT, len(page), "bytes;", "rows:", {k: len(v["rows"]) for k, v in T.items()})
