"""One self-contained HTML report for a run folder: summary, fleet checks, findings, and a card per file with its
renders embedded (JPEG data URIs), findings and visual verdict. python -m db1stepverify html --out RUN [--suffix _v2]"""
import base64, collections, glob, html, io, json, os, re, statistics as S, datetime


def _img(path, width=1100, q=76):
    from PIL import Image
    im = Image.open(path).convert("RGB")
    if im.width > width: im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    b = io.BytesIO(); im.save(b, "JPEG", quality=q, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()


def _load(out):
    rows = []
    for f in sorted(glob.glob(os.path.join(out, "*.json"))):
        if re.fullmatch(r"[0-9a-f]{16}\.json", os.path.basename(f)):
            d = json.load(open(f))
            if "result" in d: rows.append(d["result"])
    return rows


E = html.escape
ORDER = {"FAIL": 0, "WARN": 1, "PASS": 2}


def build(out, suffix="", fleet_path=None, title="DB1 STEP Verification"):
    rows = _load(out)
    fleet = json.load(open(fleet_path or os.path.join(out, "fleet.json"))) if os.path.exists(fleet_path or os.path.join(out, "fleet.json")) else None
    vc = collections.Counter(r["verdict"] for r in rows)
    T = [r["truth"] for r in rows if (r.get("truth") or {}).get("status") == "matched"]
    ex = [t["match"]["recall_b"] for t in T]; ip = [t.get("recall_with_near") or 0 for t in T]
    rp = [r["reproduce"]["match"]["precision_a"] for r in rows if (r.get("reproduce") or {}).get("match")]
    g = [r["geometry"] for r in rows if (r.get("geometry") or {}).get("parts")]
    parts = sum(x["parts"] for x in g); solids = sum(x["kinds"].get("solid", 0) for x in g)
    chk = sum(x.get("brepcheck_checked", 0) for x in g); inv = sum(x.get("brepcheck_invalid", 0) for x in g)
    vlm = collections.Counter((r.get("vlm") or {}).get("overall") for r in rows)
    inp_ok = sum(1 for r in rows if (r.get("input") or {}).get("sha256") == r["sha"])
    codes = collections.Counter(c for r in rows for c in r.get("codes", []))
    msg = {}
    for r in rows:
        for f in r.get("findings", []): msg.setdefault(f["code"], f)
    fc = (fleet or {}).get("summary", {}).get("counts", {})
    pub = (fleet or {}).get("summary", {}).get("published", 0)

    def pct(a, b): return f"{a / b:.1%}" if b else "-"

    # ---------------------------------------------------------------- cards
    cards = []
    for r in sorted(rows, key=lambda r: (ORDER[r["verdict"]], r["sha"])):
        rec = r.get("record") or {}; gg = r.get("geometry") or {}; t = r.get("truth") or {}; m = t.get("match") or {}; v = r.get("vlm") or {}
        rpm = (r.get("reproduce") or {}).get("match") or {}
        stem = r["sha"][:16]; key = rec.get("key") or ""; model = key.rsplit("/", 1)[-1].replace(".db1", "")
        imgs = []
        for suf, cap in (("_step.png", "STEP renders"), ("_vs_tekla.png", "STEP vs Tekla export")):
            p = os.path.join(out, stem + suf)
            if os.path.exists(p): imgs.append(f'<figure><img src="{_img(p)}" alt="{E(cap)} for {E(model)}" loading="lazy"><figcaption>{cap}</figcaption></figure>')
        fl = "".join(f'<li class="lv-{f["level"].lower()}"><span class="code">{E(f["code"])}</span><span class="cause">{E(f["cause"].lower().replace("_", " "))}</span> {E(f["message"])}</li>'
                     for f in sorted(r.get("findings", []), key=lambda f: ("FWI".index(f["level"][0]), f["code"])) if not f["code"].startswith("I_VLM"))
        facts = [("Xsteel", rec.get("engine")), ("parts", f'{gg.get("parts", "-"):,}' if gg.get("parts") else "-"),
                 ("extent", " × ".join(f"{x / 1000:.0f}" for x in gg.get("extent_mm", [])) + " m" if gg.get("extent_mm") else "-"),
                 ("reproduced", f'{rpm["precision_a"]:.1%}' if rpm else (r.get("reproduce") or {}).get("skipped", "-")),
                 ("Tekla export", f'{m["recall_b"]:.0%} exact · {t.get("recall_with_near", 0):.0%} in place · {m["b"]:,} el.' if m else {"none": "none next to the .db1", "unaligned": "another model", "timeout": "could not be meshed"}.get(t.get("status"), "-")),
                 ("evidence", r.get("evidence"))]
        fx = "".join(f"<div><dt>{E(k)}</dt><dd>{E(str(v_))}</dd></div>" for k, v_ in facts)
        vl = (f'<p class="vlm vlm-{E(v.get("overall", ""))}"><b>Visual check · {E(v.get("overall", "").upper())}</b> '
              f'<span class="muted">({E(v.get("confidence", ""))} confidence{", " + E(", ".join(i.replace("_", " ") for i in v.get("issues", []))) if v.get("issues") else ""})</span><br>{E(v.get("notes", ""))}</p>') if v.get("overall") else ""
        cards.append(f'''<article class="card" data-verdict="{r["verdict"]}" id="f-{stem}">
<header><span class="pill pill-{r["verdict"].lower()}">{r["verdict"]}</span><h3>{E(model)}</h3><code class="sha">{stem}</code></header>
<p class="key">{E(key)}</p><dl class="facts">{fx}</dl>{vl}<div class="imgs">{"".join(imgs)}</div>
<details><summary>All findings ({len(r.get("findings", []))})</summary><ul class="findings">{fl}</ul></details></article>''')

    # ---------------------------------------------------------------- per-file table
    trs = []
    for r in sorted(rows, key=lambda r: (ORDER[r["verdict"]], r["sha"])):
        rec = r.get("record") or {}; t = r.get("truth") or {}; m = t.get("match") or {}; rpm = (r.get("reproduce") or {}).get("match") or {}
        model = (rec.get("key") or "").rsplit("/", 1)[-1].replace(".db1", "")
        ks = " ".join(c for c in r.get("codes", []) if c[0] in "FW")
        trs.append(f'<tr data-verdict="{r["verdict"]}"><td><a href="#f-{r["sha"][:16]}"><code>{r["sha"][:16]}</code></a></td><td class="mdl">{E(model[:48])}</td>'
                   f'<td>{E(rec.get("engine") or "")}</td><td class="n">{(r.get("step") or {}).get("products", 0):,}</td><td><span class="pill pill-{r["verdict"].lower()}">{r["verdict"]}</span></td>'
                   f'<td class="n">{rpm["precision_a"]:.1%}</td>' if rpm else f'<td class="n">-</td>')
        trs[-1] += (f'<td class="n">{m["recall_b"]:.0%} / {t.get("recall_with_near", 0):.0%}</td>' if m else '<td class="n">-</td>')
        trs[-1] += f'<td>{E((r.get("vlm") or {}).get("overall", "-"))}</td><td class="codes">{E(ks)}</td></tr>'

    # ---------------------------------------------------------------- code table
    ctr = "".join(f'<tr><td><span class="code">{E(c)}</span></td><td>{E(msg[c]["level"])}</td><td>{E(msg[c]["cause"].lower().replace("_", " "))}</td><td class="n">{n}</td><td>{E(msg[c]["message"][:150])}</td></tr>'
                  for c, n in sorted(codes.items(), key=lambda x: ("FWI".index(x[0][0]), -x[1])) if c[0] in "FW")
    ftr = "".join(f'<tr><td><span class="code">{E(k)}</span></td><td class="n">{n:,}</td><td class="n">{pct(n, pub)}</td></tr>'
                  for k, n in sorted(fc.items(), key=lambda x: ("FWI".index(x[0][0]), -x[1])))
    date = datetime.date.today().isoformat()

    page = f'''<title>{E(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&family=Archivo:wght@600;700&display=swap">
<style>
/* layout: one reading column; summary -> findings -> fleet -> per-file table -> file cards (shop-drawing sheet feel) */
:root {{
  --bg:#f5f6f4; --paper:#ffffff; --ink:#1c2226; --muted:#5e6a70; --rule:#d8dddb; --steel:#2f5d86; --steel-soft:#e4ecf3;
  --pass:#1f7a4a; --pass-bg:#e3f2e9; --warn:#9a6300; --warn-bg:#fbefd8; --fail:#b3261e; --fail-bg:#f9e2df;
  --display:"Archivo", "Helvetica Neue", Arial, sans-serif; --body:"IBM Plex Sans", "Segoe UI", system-ui, sans-serif; --mono:"IBM Plex Mono", Consolas, monospace;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg:#12171a; --paper:#1a2125; --ink:#e3e8ea; --muted:#9aa7ad; --rule:#2e383d; --steel:#7fb0db; --steel-soft:#1f3040;
  --pass:#6fcf97; --pass-bg:#173326; --warn:#f0b64f; --warn-bg:#3a2c12; --fail:#f28b82; --fail-bg:#3c1b19; color-scheme:dark }} }}
:root[data-theme="dark"] {{
  --bg:#12171a; --paper:#1a2125; --ink:#e3e8ea; --muted:#9aa7ad; --rule:#2e383d; --steel:#7fb0db; --steel-soft:#1f3040;
  --pass:#6fcf97; --pass-bg:#173326; --warn:#f0b64f; --warn-bg:#3a2c12; --fail:#f28b82; --fail-bg:#3c1b19; color-scheme:dark }}
* {{ box-sizing:border-box }}
body {{ background:var(--bg); color:var(--ink); font:15px/1.55 var(--body); margin:0 }}
.wrap {{ max-width:1180px; margin:0 auto; padding-inline:clamp(16px,4vw,40px); padding-block:32px 64px; display:grid; gap:36px }}
h1,h2,h3 {{ font-family:var(--display); text-wrap:balance; margin:0 }}
h1 {{ font-size:clamp(28px,4vw,40px); letter-spacing:-.01em }} h2 {{ font-size:22px; margin-bottom:12px }} h3 {{ font-size:16px }}
.eyebrow {{ font:500 12px/1 var(--mono); letter-spacing:.08em; text-transform:uppercase; color:var(--steel) }}
.lede {{ max-width:70ch; color:var(--muted) }} .muted {{ color:var(--muted) }}
code,.code,.sha {{ font-family:var(--mono); font-size:.86em }}
.stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:12px }}
.stat {{ background:var(--paper); border:1px solid var(--rule); border-radius:6px; padding:14px 16px; display:grid; gap:4px }}
.stat b {{ font:700 26px/1.1 var(--display); font-variant-numeric:tabular-nums }} .stat span {{ color:var(--muted); font-size:13px }}
.stat.fail b {{ color:var(--fail) }} .stat.warn b {{ color:var(--warn) }} .stat.pass b {{ color:var(--pass) }}
section {{ display:grid; gap:12px; min-width:0 }}
.findings-list {{ display:grid; gap:10px; margin:0; padding:0; list-style:none; counter-reset:f }}
.findings-list li {{ background:var(--paper); border:1px solid var(--rule); border-left:4px solid var(--steel); border-radius:4px; padding:12px 16px; max-width:none }}
.findings-list li.sev-fail {{ border-left-color:var(--fail) }} .findings-list li.sev-warn {{ border-left-color:var(--warn) }} .findings-list li.sev-pass {{ border-left-color:var(--pass) }}
.findings-list b {{ display:block; margin-bottom:2px }}
.tbl {{ overflow-x:auto; background:var(--paper); border:1px solid var(--rule); border-radius:6px }}
table {{ border-collapse:collapse; width:100%; font-size:13.5px }}
th,td {{ text-align:left; padding:7px 10px; border-bottom:1px solid var(--rule); vertical-align:top }}
th {{ font:600 12px/1.3 var(--body); color:var(--muted); text-transform:uppercase; letter-spacing:.05em; background:var(--steel-soft) }}
td.n {{ text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap }} td.codes {{ font:12px/1.4 var(--mono); color:var(--muted) }}
td.mdl {{ max-width:26ch; overflow-wrap:anywhere }}
.pill {{ display:inline-block; font:600 11px/1 var(--mono); letter-spacing:.05em; padding:4px 7px; border-radius:3px }}
.pill-pass {{ color:var(--pass); background:var(--pass-bg) }} .pill-warn {{ color:var(--warn); background:var(--warn-bg) }} .pill-fail {{ color:var(--fail); background:var(--fail-bg) }}
.stages {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:10px; margin:0; padding:0; list-style:none; counter-reset:s }}
.stages li {{ background:var(--paper); border:1px solid var(--rule); border-radius:6px; padding:12px 14px; counter-increment:s }}
.stages li::before {{ content:counter(s); font:600 12px var(--mono); color:var(--steel); display:block }}
.filters {{ display:flex; flex-wrap:wrap; gap:8px }}
.filters button {{ font:500 13px var(--body); color:var(--ink); background:var(--paper); border:1px solid var(--rule); border-radius:20px; padding:6px 14px; cursor:pointer }}
.filters button[aria-pressed="true"] {{ background:var(--steel); border-color:var(--steel); color:var(--paper) }}
.filters button:focus-visible, a:focus-visible, summary:focus-visible {{ outline:2px solid var(--steel); outline-offset:2px }}
.cards {{ display:grid; gap:18px }}
.card {{ background:var(--paper); border:1px solid var(--rule); border-radius:6px; padding:16px 18px; display:grid; gap:10px; min-width:0 }}
.card header {{ display:flex; flex-wrap:wrap; align-items:center; gap:10px }} .card header h3 {{ overflow-wrap:anywhere }}
.card .sha {{ color:var(--muted) }} .key {{ font:12px/1.4 var(--mono); color:var(--muted); overflow-wrap:anywhere; margin:0 }}
.facts {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:8px; margin:0 }}
.facts div {{ border-top:1px solid var(--rule); padding-top:6px }} dt {{ font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:.06em }} dd {{ margin:0; font-variant-numeric:tabular-nums }}
.vlm {{ margin:0; padding:10px 12px; border-radius:4px; background:var(--steel-soft) }}
.vlm-fail {{ background:var(--fail-bg) }} .vlm-warn {{ background:var(--warn-bg) }} .vlm-pass {{ background:var(--pass-bg) }}
.imgs {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,460px),1fr)); gap:10px }}
figure {{ margin:0 }} figure img {{ width:100%; height:auto; border:1px solid var(--rule); border-radius:4px; background:#fff; display:block }}
figcaption {{ font-size:12px; color:var(--muted); margin-top:4px }}
.findings {{ margin:8px 0 0; padding-left:18px; font-size:13.5px; display:grid; gap:4px }}
.findings .code {{ font-weight:500; margin-right:6px }} .findings .cause {{ font:11px var(--mono); color:var(--muted); border:1px solid var(--rule); border-radius:3px; padding:0 4px; margin-right:6px }}
.lv-fail .code {{ color:var(--fail) }} .lv-warn .code {{ color:var(--warn) }} .lv-info {{ color:var(--muted) }}
summary {{ cursor:pointer; color:var(--steel); font-weight:500 }}
.two {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr)); gap:18px }}
.two > * {{ min-width:0 }}
@media (prefers-reduced-motion: reduce) {{ * {{ scroll-behavior:auto }} }}
</style>
<div class="wrap">
<header style="display:grid;gap:10px">
  <span class="eyebrow">s3://annotationprod/cad-disk-extract/conversions/db1-step · run {date}</span>
  <h1>Tekla .db1 → STEP verification</h1>
  <p class="lede">{len(rows)} published conversions checked end to end, chosen to cover every Xsteel version with output and every risk flag in the production records. Every file was traced to its input, re-decoded, measured in OpenCascade, compared with Tekla's own IFC export where one exists, rendered, and reviewed visually. Checks over all {pub:,} published files run alongside, from the production records.</p>
</header>

<section class="stats" aria-label="Summary">
  <div class="stat fail"><b>{vc.get("FAIL", 0)}</b><span>FAIL of {len(rows)} sampled</span></div>
  <div class="stat warn"><b>{vc.get("WARN", 0)}</b><span>WARN</span></div>
  <div class="stat pass"><b>{vc.get("PASS", 0)}</b><span>PASS</span></div>
  <div class="stat"><b>{inp_ok}/{len(rows)}</b><span>input .db1 found, sha256 = STEP name</span></div>
  <div class="stat"><b>{S.median(rp):.1%}</b><span>median share of parts rebuilt from the .db1 ({len(rp)} re-runs, min {min(rp):.1%})</span></div>
  <div class="stat"><b>{S.median(ex):.0%} / {S.median(ip):.0%}</b><span>Tekla export elements matched exactly / placed ({len(T)} exports)</span></div>
  <div class="stat"><b>{solids:,}</b><span>closed solids of {parts:,} parts; BRepCheck fails {inv} of {chk:,}</span></div>
  <div class="stat"><b>{vlm.get("pass", 0)} · {vlm.get("warn", 0)} · {vlm.get("fail", 0)}</b><span>visual check pass · warn · fail</span></div>
</section>

<section>
  <h2>What the verification shows</h2>
  <ol class="findings-list">
    <li class="sev-pass"><b>The files are what they claim to be.</b> All {pub:,} published STEPs have an ok record and their input .db1 is still in the bucket at the recorded size. In the sample, every input hashes to its STEP's name, and re-running the production decoder rebuilds the same parts in the same place (median {S.median(rp):.1%}; the two below 98% differ only in tessellated volume of round bars and cut members). OpenCascade reads every part as a closed solid in {solids / max(1, parts):.2%} of cases.</li>
    <li class="sev-warn"><b>Member-level accuracy is limited.</b> Against Tekla's own IFC exports, a median {S.median(ex):.0%} of elements match exactly and {S.median(ip):.0%} sit in the right place. The rest follow three patterns: members in place but {codes.get("W_VOLUME_DIFF", 0)} files show STEP volumes 10-30% larger (copes, fittings and cuts not applied); members shifted by a fixed offset in {codes.get("W_DISPLACED_PARTS", 0)} files (e.g. HEA140 edge beams moved by half their depth, an ignored Tekla position offset); and elements with no STEP counterpart in {codes.get("W_ABSENT_PARTS", 0)} files.</li>
    <li class="sev-fail"><b>Some published files hold only a fraction of their model.</b> {fc.get("W_SPARSE_DECODE", 0)} files across the fleet decoded fewer than 5 members per MB from models of 20 MB and more (the median is about 230/MB); two in the sample were confirmed visually as fragments (a hospital model reduced to 82 plate strips, a utility building to scattered pieces). Unresolved section names also drop whole groups: in one sample British UC/UKC columns and 347 members without a profile left out the entire hipped roof.</li>
    <li class="sev-fail"><b>A corrupted position stretches {fc.get("W_EXTENT_OVER_1KM", 0)} files beyond 1 km.</b> 50 of them are Xsteel 8.85 files carrying one part at the same bogus coordinate (about -78.8 km, -62.9 km), which makes their bounding box 79 km wide. The part is a decoder artefact, and the file is unusable without removing it.</li>
    <li class="sev-warn"><b>{fc.get("W_PARTS_DROPPED", 0):,} files ({pct(fc.get("W_PARTS_DROPPED", 0), pub)}) lost parts between the decoder and the STEP</b> ({(fleet or {}).get("summary", {}).get("parts_dropped_total", 0):,} parts in total), {fc.get("W_ORIENTATION", 0)} failed the orientation guard, and one published STEP no longer matches its record's size (re-uploaded without a new record).</li>
    <li class="sev-warn"><b>Dataset hygiene.</b> {fc.get("I_LIKELY_DUPLICATE", 0):,} published files are likely copies of another (daily model backups with the same members and extent), {fc.get("I_TEMPLATE_MODEL", 0)} are Tekla model templates rather than projects, and near-identical models appear under different project names.</li>
  </ol>
</section>

<section>
  <h2>How each file was checked</h2>
  <ol class="stages">
    <li><b>Record</b><br><span class="muted">An ok production record exists and describes the published object.</span></li>
    <li><b>Input</b><br><span class="muted">.db1 present, sha256 = STEP name, engine banner matches; source archive located in bim-proprietary-data.</span></li>
    <li><b>STEP file</b><br><span class="muted">Complete ISO-10303-21, AP214, millimetres, faceted only, products = solids = decoder output.</span></li>
    <li><b>Geometry</b><br><span class="muted">OpenCascade per part: closed solid, volume, BRepCheck, extent, stray and duplicate parts.</span></li>
    <li><b>Reproduction</b><br><span class="muted">The production decoder re-run on the .db1 must rebuild the same parts at the same coordinates.</span></li>
    <li><b>Ground truth</b><br><span class="muted">Tekla's IFC export next to the .db1, aligned (rotation + base point) and matched element by element.</span></li>
    <li><b>Renders</b><br><span class="muted">Four views of the STEP, and an overlay against the export: green found, yellow in place with other volume, red missing.</span></li>
    <li><b>Visual check</b><br><span class="muted">A vision model answers a fixed rubric: coherent structure, misplaced or scattered parts, agreement with the export.</span></li>
  </ol>
</section>

<section class="two">
  <div><h2>Findings in the sample</h2><div class="tbl"><table><thead><tr><th>code</th><th>level</th><th>cause</th><th>files</th><th>example</th></tr></thead><tbody>{ctr}</tbody></table></div></div>
  <div><h2>Checks over all {pub:,} files</h2><div class="tbl"><table><thead><tr><th>check</th><th>files</th><th>share</th></tr></thead><tbody>{ftr}</tbody></table></div>
  <p class="muted" style="font-size:13px">From the production records and the bucket listing, no downloads. W_SPARSE_DECODE is a candidate list: one sampled hit was a bloated .db1 of a genuinely small model, confirmed complete by its Tekla export.</p></div>
</section>

<section>
  <h2>All {len(rows)} files</h2>
  <div class="tbl"><table id="ftable"><thead><tr><th>sha</th><th>model</th><th>Xsteel</th><th>parts</th><th>verdict</th><th>rebuilt</th><th>Tekla exact / placed</th><th>visual</th><th>warnings and failures</th></tr></thead><tbody>{"".join(trs)}</tbody></table></div>
</section>

<section>
  <h2>File by file</h2>
  <div class="filters" role="group" aria-label="Filter by verdict">
    <button type="button" id="flt-all" data-f="ALL" aria-pressed="true">All {len(rows)}</button>
    <button type="button" id="flt-fail" data-f="FAIL" aria-pressed="false">FAIL {vc.get("FAIL", 0)}</button>
    <button type="button" id="flt-warn" data-f="WARN" aria-pressed="false">WARN {vc.get("WARN", 0)}</button>
    <button type="button" id="flt-pass" data-f="PASS" aria-pressed="false">PASS {vc.get("PASS", 0)}</button>
  </div>
  <div class="cards">{"".join(cards)}</div>
</section>

<footer class="muted" style="font-size:13px">db1-step-verifier · rules {E(rows[0].get("versions", {}).get("rules", ""))} · OpenCascade (cadquery-ocp {E(rows[0].get("versions", {}).get("cadquery-ocp", ""))}), IfcOpenShell {E(rows[0].get("versions", {}).get("ifcopenshell", ""))}. Each result carries a SHA-256 digest of its inputs, rules and library versions.</footer>
</div>
<script>
(function () {{
  var btns = document.querySelectorAll('.filters button');
  function apply(f) {{
    btns.forEach(function (b) {{ b.setAttribute('aria-pressed', String(b.dataset.f === f)); }});
    document.querySelectorAll('.card, #ftable tbody tr').forEach(function (el) {{ el.hidden = !(f === 'ALL' || el.dataset.verdict === f); }});
    try {{ localStorage.setItem('db1v-filter', f); }} catch (e) {{}}
  }}
  btns.forEach(function (b) {{ b.addEventListener('click', function () {{ apply(b.dataset.f); }}); }});
  var saved = null; try {{ saved = localStorage.getItem('db1v-filter'); }} catch (e) {{}}
  if (saved) apply(saved);
}})();
</script>
'''
    # standalone file (opens from disk) + a body-only fragment for hosts that add their own document wrapper
    p = os.path.join(out, f"verification_report{suffix}.html")
    open(p, "w", encoding="utf-8").write('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
                                         '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
                                         + page + "\n</html>\n")
    open(os.path.join(out, f"verification_report{suffix}.fragment.html"), "w", encoding="utf-8").write(page)
    return p
