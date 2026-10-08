# Adversarial review: class1-readiness-audit (DB1)

Reviewer run: 2026-10-02 01:20Z to 02:00Z. All heavy work ran on BOX-B (i-076e73980707c7dbe) under
`/work/agentwork/class1-readiness-audit-review/`. The Mac only did small file reads, S3 copies of small files and quick Python.
Results are in `s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/class1-readiness-audit-review/`
(setup.log, dec/<kit>/<sha12>.json, anal.json, full_h/, full_m/, grade_bi_c1live.json, grade_bi_live.json, regrade.json, nuts.json).
Scripts are in `s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/class1-readiness-audit-review/`.

**Verdict: confirmed with caveats.** The patches are correct, apply cleanly and do not regress non-bolt geometry, and every bug
I re-tested is real. The problems are in the evidence and the projections: the full-chain evidence file was made with an older patch
version, the ranking beyond the first lever relies on an assumed-clean STEP stage, and the "7 models, nothing else wrong" headline
depends on the unapproved environment catalog and ignores a known untagged washer deviation.

## Kit identity (important for integration)
- What the deliverable calls "stock kit k" is the kit deployed at review start: `kit_k/worker.py` on BOX-B has `CODE = 'z3-db1-2026-10-01l'`.
  Its db1bolts.py md5 is 5846a3bf..., the same as the S3 kit.
- **Kit m was deployed during the review** (S3 `db1/worker.py` CODE 'z3-db1-2026-10-01m', uploaded 01:30Z). Its db1bolts.py, db1step.py
  and db1bolts2.py have the same md5 as the local kit m I tested (814360f4 / 19453880 / 420ba4d8).

## Re-run on BOX-B: what holds

1. **The patches apply on every base.** I tested deployed kit l, kit l + htr, and kit m, each with the env and the own catalog.
   apply_c1_patch and apply_c1_stats report every anchor patched. A second run changes nothing (identical md5), and py_compile succeeds (setup.log).
   apply_bi_c1 also applies to the live coordinator build_index.py (18:30 local, 108,648 bytes), and the patched module imports.
2. **The KeyError crash is real on the deployed kit l.** 3585d86a380d, 48e010c8ec25 and 7c68f0c9874e all fail with convert_error,
   `KeyError: 's'` at db1bolts.py line 98. All patched kits decode them (1,928 / 1,926 / 1,437 bolts). Kit m also decodes them through its own guard.
3. **No regression on non-bolt parts.** I decoded 15 models with 6 kits (90 decodes). On every model both kits decode, the parts list is
   identical between stock and patched: seq, profile, category, status, source and cut count, for kit l vs l+c1env, l vs l+c1own,
   and m vs m+c1env. Bolt counts, holes_cut and holes_tolerance_decoded are also identical stock vs patched.
4. **The catalog rebuild matches the deployed catalog** on its 14 models: 1,090 head entries are identical, with no nut or washer
   differences. 102 'ambiguous' sizes become exact and 45 become per-length, matching the claimed 6-12 and 3-4 per model.
   Example: HSFG-XOX M33 L170 has s=60 where the other lengths have s=55, so per-length lookup is needed there.
5. **Geometry changes are consistent with published tables and Tekla's own output**:
   - F10T M22 becomes s36 / k14 / nut m22 / washer OD44 t6, which is JIS B 1186.
   - 8.8XOX M16 becomes s24 / k10.
   - a95d70a8981d (engine 9.21) own catalog: 31.75 / 11.9062 / 19.05 / 37.3063 / 3.175, against the Tekla IFC harvest values
     31.75 / 11.91 / 19.05 / 37.306 / 3.17.
   - 39a8f23724f8: the 15 TSF10T bolts move from catalog hex (counted exact) to nominal (tagged).
6. **The approx-marker bug is real and fixed.** In IFC names under kit l, after a simulated 120-character step_str cut:
   - 4671ea562003: 60 of 77 fastener names were empty '[approx: ]' markers and were cut off.
   - a95d70a8981d (v2 path): all 317 approx-tagged names lost the marker.
   - 0dd3da934923: 3,400 of 3,401.
   - With the patch, 100% of approx names keep the marker, and exact groups carry no marker.
   - STEP read-back with the final patch: 4671ea562003 has 65 approx fastener products, 7c68f0c9874e has 622.
7. **Full chain with the final patch** (decode, ifc2step6, step_check, census, join, graded by the patched live build_index and live rules.json):
   | model | kit | class | blocking stand-ins | solids | invalid | volume within 5% | approx products in STEP |
   |---|---|---|---|---|---|---|---|
   | 4671ea562003 | h+c1env and m+c1env | 2 | hole_slotted_cut_round 107 only | 705 | 0 | 93/93 | 65 |
   | ceeafb221d65 | h+c1env | 2 | hole_slotted_cut_round 107 only | 746 | 0 | 150/150 | 65 |
   | 7c68f0c9874e | h+c1env and m+c1env | 2 (live: 3) | washer_nominal 110, hole_slotted_cut_round 1,072 | 7,841 | 0 | 1,835/1,835 | 622 |

   With the **unpatched** live grader, 4671ea562003 and ceeafb221d65 stay class 2 through the STEP backstop (approx_tagged_products 65).
   The marker fix alone is enough to stop false class 1.
8. **The grader patch alone changes no class on today's results.** I re-graded every current `_state/conv/db1/results/*.json` with the
   live and the patched classify_db1: 96 stay 2, 1 stays 3, 1 stays 1, and 17 differ only in stand-ins.
   - 7 v2 code-l results lose hole_clearance_nominal (e.g. 0f3629014894: 72,768 to 0); bolt_nominal_head_nut still blocks them.
   - The code-m results gain hole_slotted_cut_round.
9. **The slot fields are genuine.** 5a2284473e4e slot fields in the DB1 (M16 + tol 2 = 18 mm): 0/57 x234, 0/17 x228, 0/22 x156, 57/0 x126,
   22/0 x68, 10 x44 and others. Tekla NC slot lengths: 17, 22, 57, 10, 11, 48. Same values.
10. **Multi-nut check:** 61,308 catalog-drawn bolts in the agent's k4/k4e dumps all have nuts at most 1. The nut1 / nut2 difference in 784
    catalog sizes never reaches the writer. The 976 catalog bolts whose washers are not drawn (not head_up) are all covered by axial stand-ins.

## Problems found

P1. **The full-chain evidence was made with an older apply_c1_stats.** BOX-B `class1-readiness-audit/kit_k4e/db1step.py` (md5 399c5df0)
    differs from a kit built from the uploaded deliverable (71e2e692):
    - no `_c1_name`, so the old path still writes '[approx: {tags}]';
    - no old-path `bolts_axial_unknown`.

    That is why `full_chain_k4e_graded.json` shows approx_products 0 for 4671ea562003, i.e. the bug itself. The claim "STEP keeps the
    marker on 65 groups" is true (my rerun: 65), but the uploaded evidence does not show it. Re-run the full chain with the final files
    before integration.

P2. **The projection uses an invented STEP stage for 20 of 106 models.** project.py sets `step_stage='not_run_here'` and grades those
    models as read OK, join coverage 1.0. Affected claims:
    - "9 of the 10 current class-3 models move to class 2": all 9 are not_run_here. I confirmed 7c68f0c9874e with a real STEP.
      12cbdcaaec9e (live class 3, part coverage 0.43) has 68 parts without geometry (ROD24 / ROD21) in my ifc2step6 run.
    - "+bolt_axial: 11 more to class 1": 8 of the 11 are not_run_here, including:
      - ec92f6149806: live member coverage 0.71, parts_outside_volume_tolerance 724/4698;
      - ffd36bc29f2f: live 0.69, 718/3789;
      - 14a172ca0af2 and b88e66e4b457: live class 3, coverage 0.47 / 0.48.
      These cannot reach class 1 by a bolt fix.
    - Unproven entries in other lever lists: washer_dims 1, bolt_head_nut 1, sections 4, washer2_side 1, cuts 1, hole_tolerance 2.

    Only lever 1 (slots, 7 models) is backed by real full chains.

P3. **"7 models ... nothing else wrong" is conditional.**
    - (a) 6 of the 7 rely on the environment screwdb catalog. With the own catalog, 4671ea562003 has 131 nominal head/nut bolts and
      150 nominal washers. The summary says this further down, but the headline does not.
    - (b) The writer draws every washer with inner diameter d + 1 (db1step bolt_group `r_in=(d + 1.0) / 2`); the catalog gives di = d
      (e.g. WASHERM20 di 20.0). These washers are counted exact with no tag; 4671ea562003 has 150 of them. The agent lists this as an
      open issue, yet calls the 7 models clean.

P4. **The environment-scope bolts count as exact.** Env-catalog entries carry `source='model_catalog'`, which the grader treats as exact.
    `catalog_scope='environment'` is written but never read. Integration step 1 defaults to `bolt_catalog.c1_env.json`. The owner rule
    allows only the model's own records or published standards, so default to `c1_own` until the lead approves. Alternatively, have
    washer_exact / build_index treat catalog_scope='environment' as approx.

P5. **The grader patch does not cover existing old-engine results.** 97c7c25d3237 has a code-l DB1 result (4,308 bolts, no slot keys,
    approx_products 0). It grades class 1 under both the live and the patched build_index, although the patched kit counts 3,376 bolts
    cut round in slotted groups. The live index currently shows class 2 (washer_nominal 4308 from another result), but with auto_final
    on, best-of could pick the code-l result. Either re-convert 97c7c25d3237 with the patched kit before the final pass, or block old-engine
    results that have no slot key.

P6. **The name fix trades away descriptive text.** `_c1_name` keeps the marker by shortening the prefix to as little as about 9-25
    characters. Example STEP name: `MM16*40/0/10/2/0/100/0/ [approx: washer thickness nominal; slotted holes cut as round hol...`, where
    the bolt standard is gone. The intermediate IFC is cut to 120 characters too; before, it kept the full name. No geometry is affected.

P7. **The slot stand-in is conservative, not proven.** 6eabb07e7145 (1,580 slot-field bolts, 0 slotted holes in 219 NC parts) and
    6b87b724b554 show that slot fields do not mean slotted plies. The stand-in may block models whose round holes are correct. That is
    acceptable under the honesty rule, but "slot decoding lifts 7" assumes those 7 really have slots.

P8. **Minor.** In the final-chain run 97c7c25d3237 is "currently class 2 as a reused Windows-pipeline model", but its code-l DB1 result
    is class 1 (P5). The summary also says "class 3 = 6", while the live status now shows 5 (12cbdcaaec9e, 14a172ca0af2, 7c68f0c9874e,
    7d7b67181db9, b88e66e4b457).

## Not refuted
I found no fabricated geometry, no loosening of grading rules (apart from the env-scope policy question in P4) and no data loss in parts
or holes. The crash fix, the holes-only fix, the engine-7.5+ stats keys, the stricter washer rule, the ASTM-vs-own-assdb guard, the
cup-head guard, the slot stand-in and the marker fix all behave as described on models I chose (5a2284473e4e, 863be0aa5b95,
c114f84dc319, a95d70a8981d, 7b06c94ec667, 39a8f23724f8, 0dd3da934923, 12cbdcaaec9e, 6eabb07e7145, 7d7b67181db9, 97c7c25d3237, plus
the 3 crash models and 4671ea562003).

---

# Second adversarial review (review2): 2026-10-02 02:50Z to 03:40Z

All heavy work ran on BOX-B (i-076e73980707c7dbe) under `/work/agentwork/class1-readiness-audit-review2/`. That covered 100 decodes,
9 full chains and the analysis; the work dir was cleaned afterwards. The Mac only read small JSON files and copied files to and from S3.
- Results: `s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/class1-readiness-audit-review2/`
  (main.log, dec/kit_nd/<sha12>.json, full_nenv/, full_nown/, grade_live.json, anal_nd.json).
- Scripts: `s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/class1-readiness-audit-review2/`.

**Verdict: confirmed with caveats.** These problems must be fixed before the auto-final pass (rules.json auto_final=true, deadline 10:00Z).

## What I re-ran, and what holds
- **The deliverable is now in production.** Deployed kit n (`CODE z3-db1-2026-10-01n`, uploaded about 02:04Z) contains the deliverable verbatim:
  - bolt_catalog.json md5 6bc3e6c1... equals bolt_catalog.c1_own.json, so the lead chose the own catalog, not env.
  - catalog_geometry / assdb_bolt_std / fallback_geometry / washer_exact / bolts_of / _c1_name / _c1_slot / _c1_v2_stats are
    byte-identical to kit m + apply_c1_patch + apply_c1_stats (r2_cmp in main.log).
  - Re-applying both scripts to kit n changes nothing.
  - The live coordinator build_index.py carries the apply_bi_c1 hunks (c1audit-bi at lines 552-570).
- **Decode-only run with the deployed kit n** (own catalog, audit dump) on 101 models under 20 MB: 100 ok, 1 local file race.
  - Old engines: the slot stand-in matches the slot fields bolt for bolt. 109,392 bolts with slot fields in 83 models, and
    slotted_bolts_cut_round has the same total.
  - The 3 former KeyError models decode.
  - The by_L per-length lookup is hit by only 35 bolts (5b33936fcd1e).
  - No ASTM or harvest table is used against a metric stored diameter without an own assdb: the 2,544 metric table bolts in 9 models
    are '8.8XOX' drawn as ISO 4014/4032. I found no residual false-exact ASTM case.
- **Full chain on the deployed kit n**: decode, ifc2step6, step_check, census, join, graded by the live classify_db1 and live rules.json.

  | model | catalog | class | blocking stand-ins | solids | invalid | volume within 5% | approx in STEP | est |
  |---|---|---|---|---|---|---|---|---|
  | 63ecb8207e98 | env | 2 | hole_slotted_cut_round 115 | 864 | 0 | 187/187 | 76 (20 parts) | (0,-1.0,0,76) |
  | e5e813f81462 | env | 2 | slots 115 | 864 | 0 | 187/187 | 76 (20 parts) | |
  | 9f619582d242 | env | 2 | slots 171 | 1,251 | 0 | 193/193 | 119 (26 parts) | |
  | f639717b04db | env | 2 | slots 561 | 4,010 | 0 | 736/736 | 410 (89 parts) | |
  | 97c7c25d3237 | env and own | 2 | slots 3,376 | 18,986 | 0 | 977/977 | 586 (0 parts) | (0,-1.0,0,586) |
  | d6f8605eb07b | env | 2 | section_parametric_panel 3 | 525 | 0 | 473/473 | 23 | |
  | 4671ea562003 | own | 2 | head/nut 131, washer 150, slots 107 | 709 | 0 | 74/74 | 102 (25 parts) | |
  | 9f619582d242 | own | 2 | head/nut 191, washer 294, slots 171 | 1,251 | 0 | 193/193 | 135 | |

  - The slot counts reproduce the deliverable exactly: 115 / 115 / 171 / 561 / 3,376 / 107.
  - Solids and checked-part counts differ slightly (for example 862 vs 864) because kit n also carries audit-db1-codes.
  - Volume, validity and the slot-only blocker hold, with env, for the 5 models I ran. The prior reviewer ran 4671 and ceeafb.

## New problems (not in the first review)

R1. **Slot fix #6 misses the v2 7.x bolt-string path. This is a correctness gap in the patch.**
    - For engines 7.5x-7.9x, db1bolts2.parse_mm reads slot_x / slot_y from the same `MM<d>*<L>/<slot x>/<slot y>/...` string
      that the old path uses, but sets no `slot_parts`.
    - `_c1_v2_stats` and the v2 name tag both require `slot_parts` to be non-zero, so these groups are never tagged.
    - Under kit n: 4518a79a995b (7.64) has 3,710 groups / 7,362 bolts with slot fields (e.g. `MM19.05*44.45/0/6.35/1.59/...`),
      slotted_bolts_cut_round 0, and 5,515 fastener names with no marker. a94442572f22 (7.64) has 542 groups / 1,647 bolts
      (slot_y 26.99), also 0.
    - In total 9,009 bolts in 2 models are cut round with no stand-in and no STEP marker. That is the same bug the deliverable says it fixed.
    - The deliverable's own lift_env.txt lists a94442572f22 as reaching class 1 at the "+cuts" step: a false class 1 waiting to happen.
    - Fix: in the v2 path, treat `slot_parts is None` (bolt-string source) like the old path, i.e. tag and count when either slot field is non-zero.
    - The 8.x/9.x attribute path (slot_parts decoded) is fine: 1d8972fb557e 755 and a95d70a8981d 1,458 bolts are tagged.

R2. **apply_bi_c1 ignores the slot key that v2 results already carry.**
    - v2 results from codes k-m store `slotted_groups_cut_round` (and code-m names said "slotted holes cut as round holes").
    - classify_db1 reads only `slotted_bolts_cut_round` or `holes_in_slotted_groups_cut_round`.
    - In the live index, these stored v2 results show no hole_slotted_cut_round:
      - 0f3629014894: 9,265 slotted groups
      - 7a6a190dfd82: 9,173
      - a95d70a8981d: 243
      - 1d8972fb557e: 70
    - a95d70a8981d is the dangerous one: its kept code-m STEP has approx_products 0 (the 120-character cut removed the markers), and
      its only live blocker is bolt_axial_position_fitted 1,308.
    - Fix: in apply_bi_c1, also add the stand-in from `slotted_groups_cut_round`.

R3. **In production, best-of throws away almost every kit-n result, and keeps the old stats.** The deliverable warned about this in
    integration step 5, but kit n shipped with `est()` unchanged (worker.py line 363).
    - Of 32 kit-n re-runs so far, 26 carry "z3-db1-2026-10-01n graded worse than ...: earlier STEP kept".
    - In all 26, the written share and invalid count are identical. The only difference is the approx-product count, which went up
      because of the honest markers this deliverable adds. Examples:
      - 4671ea562003: 17 vs 102
      - 9f619582d242: 0 vs 135
      - a95d70a8981d: 0 vs 317
      - 0f3629014894: 898 vs 10,327
    - The kept records are stamped code n in the index but carry code-l/m bolt_stats and STEPs, with no slot keys or untagged slots.
    - Fix: drop approx_products from est() for the n bump, or force replacement on the redo list.

R4. **97c7c25d3237 is a live false class 1 now, and it will stay class 1 through the final pass.**
    - Live index: class 1, standins [], converter z3-db1-2026-10-01l, STEP .l.stp.
    - Its code-l bolt_stats (4,308 bolts, A325N harvest) have no slot key, so the patched grader cannot see that kit n counts 3,376
      slotted bolts (6,444 holes) cut round.
    - My kit-n full chain gives est (0,-1.0,0,586) against the stored (0,-1.0,0,0), so best-of will keep the code-l result.
    - The deliverable's summary ("97c7c25d3237 currently class 2", "no DB1 model reaches class 1") is no longer true live.
      Its open-issue fix ("apply these patches before the auto-final pass") does not work without the est() change.
    - Fix: force-replace 97c7c25d3237 with a kit-n result, or have the grader block old-engine results that have no slot key
      (prior review P5).

R5. **The "top lever: 7 models" ranking is stale for the deployed kit.**
    - Kit n (audit-db1-codes) adds `[approx: polybeam ...]` parts: 4671ea562003 25, 63ecb8207e98 20, e5e813f81462 20,
      9f619582d242 26, f639717b04db 89.
    - After slots are decoded, the grader's approx_tagged_products backstop would still keep these models at class 2.
    - With kit n, only 97c7c25d3237 is slot-only and has no part markers (ceeafb221d65 not run).
    - This comes from another stream's change, not from this deliverable, but the ranking should be redone on kit n.

R6. **Most headline counts do not reproduce on the deployed kit, but they point the same way.** Kit n with the own catalog over 100
    decoded models gives:
    - slotted bolts: 111,605 in 85 models (109,392 in 83 on old engines, 2,213 v2), vs the claimed 98,993 in 83;
    - holes-only bolts with no geometry: 7,108 in 52 models, vs the claimed 13,915 in 56 (that was measured on kit k);
    - bolts that are nominal because of the own-assdb guard and that the name-keyed tables would otherwise have drawn: 30,598 in
      33 models, vs the claimed 7,273 in 32 (that was the env scenario).

    Other checks:
    - The env catalog mostly carries env_copies 19, but 31 entries carry 30. So the copy pool holds more than 19 screwdbs, and
      "19 of 19" describes the copies that define each size, not every copy. That makes it weaker evidence of one shared environment
      (the lead deployed own; keep it that way).

## Not refuted
- I found no fabricated geometry, and no grader rule is loosened. The holes-only, v2 hole-tolerance and slot/axial stand-ins only add
  or narrow nominal counts.
- Non-bolt parts are unchanged.
- The patches are idempotent on the deployed kit.
- The ASTM guard and the per-length head lookup behave as described on the models I chose:
  97c7c25d3237, 4518a79a995b, a94442572f22, 63ecb8207e98, e5e813f81462, 9f619582d242, f639717b04db, d6f8605eb07b, plus the 100-model decode.

Required before the final pass: R1 kit fix, R2 grader fix, R3 est() or forced replacement, R4 re-convert 97c7c25d3237.
