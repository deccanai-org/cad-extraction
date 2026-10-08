# db1 v2 — profile fixes (data-3 Tekla DB1 class-2 reasons)

Owner rule: only real definitions, never guessed dimensions. Every entry carries its provenance.

## What was wrong (data-3, 52 graded DB1 models, 6.87 / 7.01 MoldTek)

| reason in grade | root cause | fix |
|---|---|---|
| `angle: root radius assumed = t` (6,937 parts, 52 models) | parser reads `L h*b*t` from the name only | real r1/r2 from the model folder's own `profdb.bin` (format decoded, `profdb.py`) |
| `profile sizes missing: 'R.B '` (787 parts, 10 models) | old reader `cstr` stopped at the first non-ASCII byte: the name is `R.B \xd820` = `R.B Ø20` | Latin-1 kept (`db1prof.latin1_cstr`), `R.B Ø<d>` = round bar d from own `profdb.bin` (family 6, param 6109) |
| `ELD…` / `EPD…` unresolved (23 parts, 14 models) | tapered parametric profiles not parsed | `ELD h1*b1*h2*b2` solid frustum, `EPD …*t` tube frustum; exact-volume faceted solid |
| `D2940`, `ROD2120`, … implausible (51 parts, 18 models) | generic plausibility bound (round bars ≤ 1500 / 300 mm) rejects vessel dummies | per model, only where the model's own data proves the size (tiers A/B) |
| `/110/…`, `5`, `0*5955` unresolved (8 parts, 8 models) | records with zero/denormal length at the origin, no outline | not parts (`db1prof.is_null_record`) |

## Evidence

- **profdb.bin** (gzip; value records `04|pid|1|param|0|f8`, index records `04|pid|0|hash|0x0e|name`, name table stride 153 with
  family/type at +65/+69). Param codes: 6106 h, 6105 b, 6242/6241 t, 6111 r1, 6229 r2, 6122 area, 6121 kg/m, 6109 diameter, 6108 wall.
  Names without an index record are accepted only via the unique parameter block whose dimensions equal the name's.
  29 data-3 model folders ship one; the 27 MoldTek copies agree on every angle / R.B value they define.
  Check: L65*65*6 → 5.91 kg/m, area 752.9 mm²; the model's own Hot_Rolled report gives 6.4 kg for 1078 mm (5.94 kg/m).
- **ELD grammar**: 1620-C-003 KSS_ASSEMBLY_LIST-AREA.CSV (Tekla's own): ELD2188*2188*1260*1260 L1500 = 28,132 kg / 13.51 m²
  (solid frustum 28,150 kg / 13.51 m²; a constant 2188×1260 ellipse would be 25,500 kg / 12.6 m²); ELD5288..2212 L7150 654,237 kg
  (frustum 654,700). Start diameter at the part start point: 1640-C-001 D4594 | ELD4594→3268 | D3268 | ELD3268→2248 | D2248 stack
  end to end. EPD: 1220-D-010 assembly area 33.5 m² = mean-line tube frustum 1852→1440, t 10, L 6510.
- **D<d> = solid round bar** (Tekla built-in), from the models' own reports: D3376 L10120 710,655 kg; D2212 L9050 272,830 kg;
  D2530 L8205 323,604 kg; D4740 L15401 2,131,930 kg; D3368 L6400 447,299 kg; D2723 L10700 488,824 kg (all within 0.1 % of a solid round).
- **Tiers** (per model, `catalog_evidence.json`): A = own (or same-model) report weight / exact diameter continuity; B = stacked vessel
  run on one axis; C = grammar only → **not applied** (12 parts, 12 models).

## Deliverables (s3://annotationprod/cad-disk-extract/_control/z3conv/db1/v2/)

- `tekla_profiles_overlay.json` + `.README.txt`: `{meta, global (86), per_model {sha256: …} (28+ models), not_applied_tier_c}`;
  consume: `cat.update(global); cat.update(per_model.get(sha256(db1)))`. Global scope = MoldTek environment (safe for data-3).
- `prof/apply_prof_patch.py` (anchor-checked, idempotent) applies to a kit dir: db1step (ELD/EPD parser + frustum writer + null
  records), db1old (Latin-1 cstr), convert_one (overlay merge). `prof/db1prof.py`, diffs `prof/*.diff`.
- `washer_side_proof.json`: Tekla bolt flag digits d5..d0 = [holes only, washer under head, washer 2, washer under nut, nut 1, nut 2];
  1,837 / 1,841 bolt groups exact vs the Tekla IFC (BSA Ardent 8.53, GUID join).
- `bolt_catalog.json`: per model `assdb.db` + `screwdb.db` (formats decoded, `prof/bolt/screwdb.py`) → assemblies (e.g. `HEX B/N …`)
  with real head k/s/e, nut m/s/e, washer t/di/do; screwdb semantics validated vs Tekla IFC bolt geometry (head 1841/1841, washer
  1910/1910, nut 1807/1807).

## Lift (data-3, 52 graded DB1 models; decoded parts lists)

angle root radius 6,937 parts / 52 models · R.B Ø 787 / 10 · ELD/EPD 23 / 14 · D/ROD vessel rounds (A/B) 51 / 18 · null records 8 / 8.
Profile-clean after: 36 / 52 models. Class 1 additionally needs the bolt groups (all 52 carry `pieces_without_bolt_holes`).

Before/after (kit copies, 3 models): 3585d86a38 +5 parts written (ELD×2, D×3); 863be0aa5b +9 written, 347 angles exact;
14e4060080 +25 written (R.B Ø20 ×24, EPD ×1), 60 angles exact. No other part changed; status ok → ok.

## Still open (needs a real definition)

- `PD<d1>-<d2>-0` tapered (10 parts / 5 models, 1220-C-004 family): grammar with t = 0 unverified; no report row anywhere in
  478 MoldTek reports.
- `L90*90*12` (8 parts, 772329a2d9): not in its own profdb, no MoldTek-environment IFC in the 16,741-file harvest.
- 12 tier-C D<d> vessel rounds (no own report row, no continuity).
- Disk-1/2 hold the same ELD/EPD names in large numbers (e.g. ELD69.85*69.85*12.7*12.7 ×14,962 in 165 models, EPD350*350*3*3*1
  ×19,600 in 249) — the parser fix applies there too; worth a visual spot check before a Disk-1/2 re-run.
- IFC harvest note: `profcat.jsonl` rows from feet-unit files look scaled twice (L150*90*10 → 45720/27432/3048).
