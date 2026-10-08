# PII redaction for CAD PDFs — plan v3 (strict, in place) — 2026-09-30

**Status:** approved in principle, but ON HOLD. Dhiren first wants every extraction copied to `s3://bim-proprietary-data/cad-disk-extract/`
(same keys). PII will then run on the BIM-bucket copies (to confirm: copy vs move, BIM versioning).
v2 (below this section in git history) is superseded where v3 differs.

## Owner decisions (2026-09-30)

**Black out:**
- every person name, initials, signature and seal;
- every company/organisation name and logo of the parties (owner/client, architect, engineer, fabricator, detailer, GC, erector,
  consultants), including inside project titles, contact blocks, notes, watermarks, metadata, paths and OCG names;
- all addresses (personal and commercial, including project site, lot/APN, lat/long, street text in vicinity maps);
- all phone/fax/mobile, emails, URLs/domains;
- licence/registration numbers (personal and firm, certificate numbers), account/PO/contract/permit/tax IDs;
- usernames/paths, annotation authors, digital-signature dictionaries;
- non-generic project names.

**Keep:**
- geometry, dimensions, quantities/BOMs/marks;
- drawing/sheet numbers, revision numbers/dates/descriptions (minus party tokens), **job/project numbers**, scale;
- generic titles;
- technical notes/specs/status text;
- standards (AISC/ASTM/AWS/ACI/IBC…) and manufacturers/products specified as material (HILTI/SIMPSON…) — the roster wins if the org is a
  party in that project;
- software names; field labels.

**Handling:**
- OpenRouter, ZDR-only routing (`provider: {zdr: true, data_collection: "deny"}`).
- Overwrite in place; **keep old versions** (the verifier and rollback use `pii-orig-version`).
- Scope: extraction folders + `dataset/main` + `packaged/main` PDFs; update package `manifest.jsonl`/`project.json` bytes/etag/sha with If-Match.
- OpenRouter key: provided by Dhiren; to be stored as SSM SecureString `/cad-pii/openrouter-key` (never in git/memory).

## Key design (details in the v3 design-agent output; summary)

**Pack `cad_strict`:**
- rows S01–S17 REDACT, K01–K11 KEEP;
- **title-block allowlist:** inside the title-block zone and revision table, every cell is redacted (interior inset 0.75 pt, borders
  kept) except allowlisted field types (sheet/drawing no., n of m, generic title, scale, size, dates, revision no./date/description,
  job no., units, technical notes, status, graphics, labels). Allowlisted values are still screened per token;
- zone guard: ≤30% of page, ≥4 cells, else "no-title-block" mode + LLM.

**Outside the title block:**
- project roster (HMAC-stored);
- global party list (≥2 tokens or ≥6 chars, non-vocabulary);
- regex (phones/emails/URLs/licences, address grammars + usaddress, PO box, lat/long, APN);
- LLM only on candidate note blocks (deduped by text hash);
- logos, seals, signatures.

**Disabled from the reference:** handwriting bands, cheque zones, `unlabelled_identity_blocks`, the QR shape detector (use a real decoder),
20% fuzzy matching.

**`redact_cad`:** as v2, plus:
- `no_new_id=True` (deterministic bytes across hosts);
- cell-interior masks;
- off-page text filter;
- stamp/FreeText appearance regeneration;
- pending source `/Redact` annots applied.

Fallback tiers: T1 field → T2 subpath → T3 (opt-in) whole title-block zone → T4 quarantine (untouched).

**`verify_cad`:** as v2, plus allowlisted-field survival, non-allowlisted fields empty, decoded-pixel identity outside masks, `qpdf --check`.

**In-place protocol, per sha group:**
1. HEAD every member (VersionId/ETag/ContentType/StorageClass/meta/tags).
2. GET the leader by VersionId and check its sha.
3. Detect → redact → verify (tiers).
4. Write the decision JSON with IfNoneMatch.
5. PutObject each member with `IfMatch=pinned ETag`, ChecksumSHA256, original ContentType/StorageClass/metadata/tags + pii-* metadata.
   - 412 → conflicts queue; null VersionId → global stop.
6. Write the ledger row; `done/<gid>` only after all members are written.

Late members: GET the redacted version, then PUT with If-Match. Package finalizer after all its groups finish. Data-4/Disk-1/2 indexes
kept as original provenance; `_state/pii/index` maps orig sha → out sha.

**Post-run `verify_s3.py`:**
- every key: current SHA256 = decision out-sha; `pii-orig-version` ETag = snapshot; no intermediate versions;
- every unique content: full collateral + second renderer (pypdfium2) + `qpdf --check` + residual sweep + Tesseract re-OCR;
- judge from a third model family on 0.5% (~16k), human audit of 1,000 pages;
- recall with Clopper-Pearson CI.

**Models (OpenRouter):**
- bulk: Gemini Flash-class; second detector: GPT-5.x-class; judge: Claude Sonnet-class (ids confirmed from `/api/v1/models` + `/endpoints`
  ZDR at build);
- AIMD concurrency ~50–100 req/s fleet-wide;
- key credit limit as hard cap + `llm_stop` at 95%;
- estimate 0.9–2.4B input tokens, ~$0.4–2.7k (suggest a $3k limit).

**Fleet:**
- c7a.16xlarge (1 vCPU = 1 core) ×10 Mumbai + r7a.8xlarge heavy queue + m7a.2xlarge coordinator; 5 × c7a/c7i.16xlarge Hyderabad;
- Docker image on AL2023; one process per core, a child per PDF;
- estimate P1 4–6 h, P3 8–11 h, post-verify 4–6 h on ~1,000 vCPU (a 2,000 vCPU cap halves it);
- compute ~$1–1.6k; S3 requests ~$60; kept versions ~$115–150/month.

**Timeline:**
- Day 0: build + G0 (0 collateral failures, controls fail 100%, deterministic bytes, stale-ETag PUT → 412, original version byte-identical).
- Day 1: detection pieces + P1 + golden labelling (~25 person-hours).
- Day 2: P2 + G1 (recall ≥99.5% per category with CI lower bound ≥99%, 0 collateral failures, allowlisted-field survival ≥99.5%, area
  precision ≥90%) + 10k in-place pilot + rollback drill + G2.
- Day 3: full P3.
- Day 4: `verify_s3` + judge + audit + `verify_dataset` + report.

## Owner inputs still needed for PII
- OpenRouter credits/limit;
- SSM parameter + `ssm:GetParameter` for `cad-disk-extract-ec2`;
- `s3:GetObjectVersion`/`ListBucketVersions`/`GetBucketVersioning`/`GetLifecycleConfiguration`, object tagging if used, `DeleteObjectVersion`
  only for rollback;
- confirm versioning Enabled and no noncurrent expiry, replication/event notifications;
- who may read old (unredacted) versions — bucket-policy Deny recommended;
- longer operator session;
- optional vCPU cap raise;
- human labellers;
- confirm T3 opt-in and a consumer freeze notice.

## Residual unredacted copies (to list in the report)
Old S3 versions; source archives; data-4 `source/` raw archives; non-CAD PDFs; data-2 renders/text/DXF; S3 key names containing party
names; quarantined files.

## v3 addendum (design-agent hand-back, 2026-09-30)
- **Target bucket:** after the annotationprod → bim-proprietary-data move, every PII path above means
  `s3://bim-proprietary-data/cad-disk-extract/…` (same keys).
- **Dataset PDFs keep their source ETag** (`cad-db1-convert/src/pkg_step.py` copies single-part objects server-side). So (ETag, size)
  joins `dataset/`/`packaged/` copies to their Disk-1/2 source even when `source_key`/`sha256` is null.
- **`project.json` holds `files`/`bytes` totals:** update them with `manifest.jsonl` (If-Match). `verify_dataset.py` checks `bytes_mismatch`
  and uses (etag, size) as the dedup identity, so it will report new "content duplicates" where redaction makes files identical.
- **Data-4 stores more CAD-PDF objects than 836,532:** ~1.87M Disk-1/2-duplicate objects stored before worker k, and <64 KB files stored
  once per archive. Enumerate by listing S3, not from counts.
- **Volumes (`sources.json`):**
  - data-4 CAD PDFs: 6.75M paths / 3.21 TB (≈475 KB avg); 2.95M unique / 1.65 TB;
  - Disk-1/2: 6.22M raw objects, 2.45M unique;
  - data-2: 1,250 / 343 MB.
- **OpenRouter:**
  - paid models have no platform request cap (upstream 429/Retry-After only);
  - a key can carry a hard credit `limit`, and `GET /api/v1/key` returns `limit_remaining`;
  - requests can set `provider: {zdr: true, data_collection: "deny"}`;
  - model ids are NOT confirmed yet (the `/api/v1/models` fetch was unreliable) → confirm ids and prices at build.
- **Recommended LLM cap $4k** (estimate $0.5–3.2k). Total one-off estimate ≈ $2–5k + ~$110/month for kept versions.


---

# (superseded) plan v2 kept for reference

# PII redaction for CAD PDFs — plan v2 (2026-09-30)

Owner requirement (Dhiren): run on AWS, finish ASAP; CAD PDFs fully PII-redacted; **nothing lost — only personal info blacked out**.
Reference: `shivangiY07/AudioPII-QC` @ `feature/multimodal-document-arm`, cloned read-only to `~/Downloads/Deccan/AudioPII-QC`.
Status: **awaiting owner decisions (§10)**; nothing built yet.

## 1. Verdict on the reference: not usable as-is for CAD

The reference is kept read-only. Modules are forked to `~/Downloads/Deccan/cad-pii/`, each crediting its source.

**It loses content.**
- `redact.py` uses `apply_redactions(graphics=LINE_ART_REMOVE_IF_TOUCHED)`, which deletes whole vector paths whose bbox touches a box
  (sheet frame, title-block grid, polylines).
- `rewrite_images(lossy=True)` re-JPEGs every image of every file.
- Every widget is deleted.
- `scrub()` wipes the whole /Info, all XMP, embedded/attached files, annotation replies/popups, thumbnails and JS; `set_toc([])` wipes
  bookmarks; `clean=True` rewrites every content stream.
- Rotated pages are not de-rotated, so boxes can be misplaced.
- `neutralise_inherited_redactions` uses an undefined `BLACK`: inherited marks are deleted and not re-added (a leak).

**It misfires on CAD.**
- Handwriting top/bottom bands black out blue linework and title blocks.
- "Cheque zones" fire on wide images and raster sheets.
- `unlabelled_identity_blocks` catches engineering-firm addresses.
- The QR shape detector fires on hatching.
- Fuzzy propagation at 20% edit distance matches ordinary words (WALTER→WATER).
- `phone` maps to REDACT, so company phones are destroyed.
- Licence numbers map to gov_id.

**It can't read CAD.**
- Answer areas are only to the right of a label: no below-label, column or cell mode.
- Short labels BY/CHK are fuzzy-repaired.
- Initials are never propagated (MIN_LEN 5) nor verified (MIN_LEN 4).
- SHX stroke text has no text layer.

**Linux/AWS.**
- Apple Vision OCR/QR/faces are macOS-only and give 0 words silently on Linux.
- `/private/tmp/claude-501/…` workdir default.
- `output/` missing → the GPT call is billed and then fails.
- Keys only from `.env`; OpenRouter only; no batch runner, no S3, no requirements.

**Verifier.**
- No before/after collateral check.
- Label regions (`[`-prefixed) and short values are never verified.
- Streams ≥4 MB are skipped.
- `added_text` is never called.

**Cost.** Naive, every page goes to GPT: ≈28B input tokens for ~5.2M pages.

## 2. `cad_drawing` pack (standalone, `conservative: false`, every sem key mapped)

**REDACT:**
- names/initials in person cells (DRAWN/DRN/DWN, DETAILER/DET, CHECKED/CHK/CKD, DESIGNED, ENGINEER, APPROVED/APP, REVIEWED, PM, PREPARED/SUBMITTED BY) and in the revision BY/CHK/APP columns;
- roster matches elsewhere;
- personal PE/SE/RA licence numbers; seal*; signatures;
- personal phone/mobile/email;
- private-client name + residential address*;
- `DOMAIN\user`/usernames/paths with a username;
- annotation authors; digital-signature certs*;
- person-encoding QR codes.

**KEEP:**
- geometry, dimensions, notes, schedules;
- company names/logos; firm registration numbers; company phone/fax/role email*;
- project/sheet numbers, titles, dates, revision text (minus roster names);
- commercial site addresses*.

(* = owner decision)

## 3. Zero-loss redactor (`redact_cad.py`)

**Finding kinds:** glyph / stroke / raster / region. All in de-rotated coordinates.

**Redaction rounds:**
1. Stroke/seal boxes: `graphics=REMOVE_IF_COVERED`, text REMOVE, images NONE.
2. Glyph boxes: `graphics=LINE_ART_NONE`, text REMOVE, pad 0.5–1 pt, `_clip_to_neighbours`.
3. Raster boxes: `images=PIXELS` only where a box hits an image placement (lossless re-encode). **Never `rewrite_images`.**

**Fallback.** If strokes live in one big path, a pikepdf subpath filter deletes only the subpaths fully inside the box. Else quarantine.

**Document objects.**
- **Widgets kept:** a PII field's value is set to "".
- **Annotations kept:** blank `/T` and Bluebeam author columns; delete PII tokens in `/Contents`/`/RC`; delete `/Ink` in signature cells;
  edit or delete AutoCAD SHX Text comments.
- **Metadata edited key by key:** `xref_set_key` on Info (never `set_metadata`); XMP `dc:creator`/`pdf:Author`/paths. Same edit for
  `/PieceInfo`, OCG names, TOC titles, StructTree Alt/ActualText.
- **Embedded PDFs:** redacted recursively.
- **Thumbnails:** regenerated only for touched pages.

**Save.** `garbage=3, deflate=True, clean=False, encryption=KEEP`: a full rewrite, as an incremental save would keep the PII.

## 4. "Nothing lost" proof (`verify_cad.py`, every output, all pages, all OCGs on)

**Removal:**
- no glyph centred in a box (any length);
- no stroke in a stroke box;
- raster box uniform.

**Collateral (source vs output, masks = boxes + 1 pt):**
- (a) char multiset outside masks identical, and `added_text` = ∅;
- (b) `get_cdrawings()` multiset outside masks identical, apart from expected removals and our fill rects;
- (c) 60 dpi render diff outside masks = 0, with default layers and with all OCGs on;
- (d) image placements, dims and format unchanged;
- (e) same page count, boxes, /Rotate, annotation counts by subtype (minus logged deletions), OCGs/configs, TOC length, embedded names,
  form fields, links, marked-content counts.

**Residual object sweep.** pikepdf over every string and stream: 0 roster, username or email hits.

**On failure.** Retry with the fallback, then quarantine with a reason; never publish.

**Audit.** Stores HMAC(value) and length only.

**Controls (must fail 100%):**
- cosmetic control (draw_rect only) → removal check;
- reference-mode control (REMOVE_IF_TOUCHED + rewrite_images) → collateral check.

## 5. Detection ("fully redacted")

**Readers:**
- text layer with all OCGs on and no MediaBox clip;
- SHX Text annotations used as words;
- SHX strokes → 300–400 dpi title-block crop → RapidOCR (ONNX, pip wheels, Linux);
- raster pages → 150 dpi tiles + 300 dpi title-block crop;
- a second OCR engine (Tesseract) only for the leak re-check.

**Cell model:**
- `get_cdrawings()` segments → lattice → cells;
- title block = densest cell cluster at the inner right/bottom border;
- revision table = header REV/DATE/DESCRIPTION/BY|CHK|APP;
- raster pages: OpenCV line mask.

**Labels → values:** same cell right/below → adjacent right/below → column mode for revision headers. Person cells are redacted by
position without needing to read them.

**Project roster:**
- key = archive + job-number folder;
- sources: title-block person values ∪ `DOMAIN\user` ∪ markup authors ∪ seal names ∪ LLM-confirmed names across all PDFs of the project.
- Matching:
  - initials ≤4 chars: exact token, only in title/revision cells, markup text, revision descriptions;
  - names ≥5: exact token sequence anywhere;
  - fuzzy only for OCR words (edit ≤1, length ≥7, never corpus-vocabulary words).

**Seals and signatures:**
- vector circle 1.2–2.5 in containing PROFESSIONAL/ENGINEER/ARCHITECT/STATE OF/P.E./No. → whole-circle stroke box;
- raster seal via template slot or Hough + OCR keywords;
- signatures: images, `/Ink` or non-axis-aligned stroke clusters inside signature/approval/seal cells.

**Contacts, licences, addresses:**
- CELL/MOBILE/DIRECT or next to a roster name → personal;
- OFFICE/TEL/FAX under a company block, or the same number seen in ≥5 projects → company;
- role emails → company;
- FIRM REG → KEEP;
- CLIENT/OWNER person-shaped or RESIDENCE → redact the name and address.

**Template learning + residual LLM:**
- title-block skeleton hash + MinHash LSH clusters (20–60k expected);
- the LLM labels 1–3 exemplars per cluster (cell table + crop if SHX/raster) → PII slots applied to the whole cluster;
- the residual LLM runs only on low-confidence pages (no grid, unresolved slots, unknown skeleton, name candidates in notes).

**Leak re-check on 100% of outputs.** Re-OCR the output title block with engine 2; slot/roster hits → quarantine. Plus a judge on a
stratified 0.5% (~16k files) and a human audit of 1,000 pages, reporting recall with CI.

## 6. Model access (owner decision)

**Recommendation.** Bedrock ap-south-1: in-account, `bedrock:InvokeModel` added to the `cad-disk-extract-ec2` role, quota increase
requested on day 0, batch inference about half price.
- Bedrock access is currently unknown: `bim` is denied ListFoundationModels and the SSO login had expired.
- Fallback: OpenRouter (data leaves AWS).

**Volume:** exemplars 0.14–0.42B + residual 0.4–0.65B + judge 0.1B ≈ **0.65–1.2B input tokens** (vs ~28B naive), 150–400k requests,
with a budget cap enforced in `llm.py`.

## 7. Jobs, dedup, outputs

**Jobs:** ~6.6k shards of ~500 unique PDFs grouped by project, under `cad-disk-extract/pii_redacted/_control/`.

**Per disk:**
- **data-4:** manifests ⨝ `classes.sqlite` (cls=cad), minus the Disk-1/2 index → 836,532.
- **Disk-1:** data-4 phase-B manifests (identical archives) give archive/member/sha → Disk-1 key via `pdf_disk12_pass.disk1_folder()`;
  keep shas in the archive's `results|ec2-results` `sha256.cad_pdf`.
- **Disk-2:** list the folders' PDFs; hash on download; keep those in the archive `cad_pdf` set; weak-hash archives classified on the fly.
- **data-2:** source PDFs (≈1,066).

**Dedup marker.** `pii_redacted/_state/sha/xx/<sha>`, value `claimed:` → `done:<out>`, written **after** the output and audit upload;
heal on hit (fixes the zx marker-before-upload gap).

**Outputs:**
- `cad-disk-extract/<disk>/pii_redacted/<same relative key>` + `.audit.jsonl`;
- per-disk `_index/part-N.jsonl.gz` (status redacted | pointer | quarantined | not_cad | error);
- quarantine records under `_quarantine/`;
- P1 features/rosters in `_private/` (deleted after the run);
- originals untouched.

## 8. Fleet

**Worker.** `fleet/pii_worker.py`, a copy of the `zx_worker` pattern: claims/takeover, heartbeat, hot reload, versioned stop, env
overrides, modes p1/p3/repair.
- One PDF per child process (`maxtasksperchild` 50, RLIMIT_AS 3 GB, per-file timeout) and retry-then-quarantine.
- Boot: `ud_pii.sh` on AL2023 with a pinned venv tarball, self-terminating.

**Machines:**
- Mumbai: 10 × c7a.16xlarge (640 vCPU) + 1 × r7i.2xlarge (P2/stats);
- Hyderabad: 5 × c7i.16xlarge (320 vCPU);
- 2 heavy-queue boxes.

**Estimate (to be confirmed by the pilot).** ≈8 CPU-s/page average → ~11.6k vCPU-h → **12–16 h wall** for P1+P3; compute ≈ $0.8–1.5k.

**Live page.** PII panel: processed/published/quarantined/not_cad, pages, findings by category, collateral pass rate, leak re-check,
tokens and $, ETA; counts only.

## 9. Timeline and gates

**Day 0**
- Fork + requirements, `redact_cad`, `verify_cad`, controls.
- `synth/cad_cases.py`: ~20 title-block layouts, Hershey SHX strokes, /Rotate 0/90/180/270 + CropBox offset, seals, rasters, Bluebeam,
  OCGs, bookmarks, embedded files, signature fields.
- Test on the 12 real sheets; build job lists; get owner decisions + Bedrock quota/IAM; pull a 2,000-PDF sample.
- **G0:** 0 collateral failures, and both controls fail 100%.

**Day 1**
- Readers/grid/labels/roster/seals/objects.
- **Full P1 features run starts in the evening.**
- Golden set: 1,000 real sheets pre-labelled by an LLM then human-verified (~25 person-hours; the critical path).

**Day 2**
- P2 clustering + exemplar labelling; residual pass; golden eval; **pilot on 10k files**.
- **G1:** recall ≥99.5% per category (95% CI lower bound ≥99%), 0 collateral failures, area precision ≥95%.
- **G2:** quarantine ≤1% with every reason understood, 0 leaks in a 300-page human audit, tokens within budget.

**Day 3**
- Full P3 run, project by project.

**Day 4**
- Quarantine re-runs, judge on 0.5% + human audit of 1,000 pages, final indexes and report.
- **G4:** recall ≥99.5%, 0 collateral failures on published files.

## 10. Owner decisions

1. Initials in person cells and revision BY/CHK/APP → REDACT? (recommend yes)
2. Company phone/fax/role email → KEEP? (recommend yes)
3. Seal: whole seal, or name + number only? (recommend whole)
4. Private-residence client name + address → REDACT; commercial → KEEP?
5. Model provider + budget cap + who grants the Bedrock quota and IAM.
6. Digital signatures: remove the PKCS#7 and signer fields? (any edit invalidates them anyway)
7. Collapse incremental revision history? (required for PII)
8. Title paths: delete only the username segment, or the whole path?
9. Duplicates: index pointers, or materialise copies at all ~8.2M raw paths?
10. Scope: repackage `dataset/main/2d` packages? The 954k non-CAD PDFs out of scope?
11. Who labels the golden set; who may access `_private/`.

## 11. Risks

| Risk | Mitigation |
|---|---|
| SHX strokes merged into big paths | subpath filter, else quarantine |
| OCR misses | person slots redacted by position; 2 OCR engines |
| Over-redaction | cell-bounded boxes; vocabulary guard; precision gate |
| Rotation/CropBox/off-page text | golden edge cases |
| Hidden OCG content | detect and verify with all OCGs on |
| MuPDF version drift | pin the version; regression before each hot reload |
| LLM limits | templates; quota; budget cap; fallback |
| Leaks via audit, features or the public page | HMAC values, restricted `_private/`, counts only |
| SSO expiry mid-run | fleet runs on the instance role |

## 12. Trial + model cost decision (2026-09-30 / 10-01)

**Trial:** 20 CAD PDFs (Disk-1/2, data-4), local only in `~/Downloads/Deccan/cad-pii/trial/`.
- Contents: `in/`, `out/`, `compare/<id>/{before,after}.pdf + PNGs`, `quick_view.html` (before | after viewer). It contains PII.
  Never publish it.
- Model: `qwen/qwen3.8-max-prime` ($4 / $12 per M tokens, Alibaba only, no ZDR).
- Cost: 43 calls, $3.85 for 2 passes, ≈ $0.10 per drawing per pass.
  - 94% of output tokens were reasoning (267k of 283k).
  - Each call sent ~6k prompt tokens plus 2 images.
- Pass-1 verify: "PII removed" 7/11 and "nothing lost" 3/11. Small vector-segment losses outside the boxes were being fixed when the
  owner stopped the run.
- Owner liked the s13 result. Recall gaps on s02 (Gensler sheet): client name, firm names and logos, seal, signature, engineer
  name, licence number, project name.
- **Stopped by the owner** (a cheap-model bake-off was started without being asked and was stopped too). Do not run PII work
  unless asked.

**Budget: ≤ $250 total for the LLM part (owner).**
- Per-drawing LLM calls at trial size would cost ~$330k with max-prime and ~$600 even at $0.03/M.
- So the design must be: free deterministic layers + LLM only per new title-block template / project roster (~150k calls) plus a
  compact-text residual sweep (~1M calls), thinking off, text not images.

**Model recommendation given (price list only, not tested on our drawings):** use OpenRouter, pinned to zero-data-retention
providers.
- Text: `openai/gpt-oss-120b` ($0.037 / $0.17); cheapest is `gpt-oss-20b` ($0.018 / $0.09).
- Scans: `google/gemini-2.5-flash-lite` ($0.10 / $0.40, ZDR via Google).
- `qwen/qwen3.7-flash` ($0.03 / $0.13) is cheaper for scans but has no ZDR.
- Estimates: LLM part ~$100–140; total including CPU fleet (~$250 spot / $600 on-demand) and S3 PUTs (~$40) ≈ $390–780.

**Self-hosting compared:**
- Qwen3-30B-A3B text + Gemma-4-26B vision on GPU.
- Similar total cost and a lower quality ceiling; needs GPU quota and setup.
- Choose it only if PII must never leave AWS.

**Still to decide (owner):** API vs self-host; the model; versioning ON for the bim bucket (needed to keep originals; ~$125–200 per
month).
