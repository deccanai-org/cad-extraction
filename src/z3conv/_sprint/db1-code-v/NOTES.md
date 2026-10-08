# DB1 code v - working notes
- 16:35Z box /opt/db1v: synced 1,499 data-4 manifests; scan_nc.py -> nc_cands.json (DB1 entries with *.nc1/*.nc under the model dir in the same archive). Copy: s3://annotationprod/.../agentjobs/db1-code-v/nc_cands.json
- Code facts: engines < 7.5 -> convert_old (slots via SLOT_SET, DB1_SLOT_ENGINES default 6.87,7.01; 7.24 off: 8/92 slots rotated vs NC).
  engines >= 7.5 -> db1bolts2 (V2 slots, DB1_V2_SLOT_ENGINES default 7.64,8.53). slot_parts: 7.x only when attr stride 389 (7.64); 8.x/9.x at +21+shift.
- Index (data-4, 2026-10-05 16:26): class-2 DB1 13,810; panel 11,217, slotted 9,791, stud 8,583. Models where ONLY these 3 tags block: 270.
- 17:2xZ: resolve.py -> /opt/db1v/sel1r.json (212 picks, ~1 data-4 archive each, models with hole_slotted_cut_round, <=150 MB). Harness h/{hook.py,vnc.py,runv.py}
  (s3 agentjobs/db1-code-v/h/): hooks db1step to export V2SLOT (new) / SLOT_SET (old), runs with ALL engines enabled, labels each bolted part vs NC1.
  systemd unit db1v-slots1 -> /opt/db1v/out1/<sha12>.json, log slots1.log, kit_u = prod u kit, kit_h = hooked.
- 17:50Z partial slots1 (20 models): 7.24 ply selection 418/418 agree (3 models) BUT direction: 272 ok / 33 rot90 (Tekla 'rotate slots'?).
  7.01 194/194 + dir 194/194. 7.64 10/11. 8.85 2/2. Need more truth for 8.07/7.82/8.85/9.08.
  Started db1v-slotsold (kit_h2 also dumps the old part-attr record 0..124 per slotted group) -> out_old/, to find the rotate-slots field.
- Panel/stud plan: secck.py (h/) GUID-joins DB1 parts to Tekla's own IFC export in the same model dir (Tag 'ID<guid>'); panel: world axis of
  the first number A vs writer (YDim=A along part y); stud: Tekla body = single circle extrusion (no head) => shank IS Tekla's stored geometry.
  scan_ifc.py (db1v-scanifc) -> ifc_cands.json still running.
- 20:40Z STUDS: Tekla's own IFC export (GUID-joined, 7.64 4 models + 8.07 1 model, 10,190 studs) writes every STUD_x-DIA part as a faceted
  brep WITH a head: e.g. STUD_1/2-DIA L127: shank r6.35 to 118.11, flare to 120.65, head r12.7 to 127; STUD_5/8 L152.4: 140.21/141.73, head r15.88;
  STUD_3/4 L152.4: 138.68/140.21, head r19.05. The head comes from the environment profile catalog (variable cross-section profile), NOT the DB1
  (DB1 holds only the name). => shank-only IS a stand-in; tag stays. Path to exact: decode the model folder's own profile catalog if it defines STUD_*.
- SLOTS so far (out1 + out_old): selection 7.24 837/837 (7 models), 7.30 554/554, 7.82 126/126 (2), 7.64 1889/1902, 6.87 2838/2909 (prod ON), 7.01 194/218 (prod ON).
  Direction (pred slot & NC slot, axis-aligned): 7.24 687 ok / 37 rot90; 7.30 512/8; 6.87 2505/2; 7.01 194/0. No bolt-string or attr[0..120] field separates 7.24 rot90.
  All selection/direction errors have ncand>1 (NC match by x-stations only is ambiguous) -> truth noise possible. db1v-rot dumps full attr+member records.
- 20:55Z FOUND old-engine 'rotate slots' field: part-attr record (stride 373) byte @368: 0 / 1 / 2. Every NC rot90 case has b368 != 0
  (b368=2 & ply rank 0 rotated: 2c53 x4, aad065 x29; b368=1 & rank 1 rotated: 33a0 x4, 5e49 (7.30) x8); every agreeing case has b368=0.
  Hypothesis: 1 = rotate even plies (2nd, 4th), 2 = rotate odd plies (1st, 3rd) [Tekla 'Rotate slots' Even/Odd]. Prod u ignores it (6.87/7.01 ON!).
  Rerun all old models with full record dump: db1v-slotsold2 -> out_old2.
- 20:34Z ROTATE-SLOTS rule H CONFIRMED on out_old2 (38 old models): rotated iff (b368==1 and ply rank odd-index k%2==1) or (b368==2 and k%2==0);
  distinguishing cases all agree (7.01 b368=2 rank1 not rotated x3, rank2 rotated x1; 7.24 b368=1 rank0 not rotated x1).
  Direction-checkable parts: 4,742 / 4,745 agree with H (3 misses all b368=0: 6.87 x2, 7.01 x1 = NC truth noise / ambiguous match).
  Patch written in _sprint/db1-code-v/v/{db1old,db1bolts,db1step}.py (DB1_SLOT_ROTATE=1). Square A*A panels -> 'parametric_rect_square'
  (exact; ~1 % of panel models are square-only: 6 / 567 sample; 13,166 / 113,015 panel parts square).
- 20:45Z PANELS (sec1 98 + sec2 55 pairs, mesh extents of Tekla's own element in the writer frame): non-square A*B with A along part y
  140 / 140 (0 rotated; 8 'extents_other' = cut/revised walls, not a rotation), 7 models on 7.64/7.82/8.07/8.53; squares 97/97.
  Control catalog I sections depth axis: 7.64 4850/4850, 7.82 1391/1391, 8.07 389/390, 8.53 1012/1012. Old engines: no GUID join -> no truth.
  Patch: A*A -> 'parametric_rect_square' (all engines); A*B -> 'parametric_rect_hb' on DB1_PANEL_AXB_ENGINES=7.64,7.82,8.07,8.53.
- STUDS: 23,128 GUID-joined studs (7.64 14,445 / 7.82 2,955 / 8.07 3,309 / 8.53 2,419): 100 % have a head in Tekla's IFC. Tag stays.
- 20:43Z harness vnc.py now passes layouts.json (was doing full layout discovery: 8.07 3 MB took > 38 min). 8.07 slot_parts @+21+48:
  out1 model 834ea: 84/84 wrong (mask 0 / 1099674157 garbage) -> offset wrong for 8.07; searching (maskfind.py, db1v-snew3 -> out_new3).
- 20:55Z 8.x SLOT MASK OFFSET FOUND: maskfind on out_new3 (8.07 stride 365): i32 @+21 (NO shift) == NC truth mask in 688/688 groups
  (292 nonzero); prod reads @+21+48 (matched only the 396 all-round groups). 7.64/7.82 stride 389: @+25 = 137/137, 9/9 (as in prod).
  Patch db1bolts2.py (DB1_SLOTPARTS_NOSHIFT=1). kit_v on box = kit_u + v/{db1step,db1old,db1bolts,db1bolts2}.py; kit_h3 = hooked kit_v.
  db1v-sv: harness with v code on all 193 NC models -> out_v. db1v-reg-u: full-chain regression of 40 models with kit_u -> regress/u.
- 21:15Z out_v (v code, all engines forced on): selection vs NC: 7.64 3525/3559 (99.04 %, 8 models), 7.82 2333/2413 (96.7 %), 8.07 5177/5183
  (99.88 %, 11), 8.44 1970/1980 (99.5 %, 1), 8.53 42/42, 8.85 106/106 (4), 7.98 1/8, 9.08 no truth.
  NEW-ENGINE ROTATE-SLOTS byte (rule H): stride 389 (7.64/7.82) @385: 3346/3346 + 2009/2009; stride 317 (8.44) @265: 1936/1936 (22 rotated);
  8.07 (365) @265+48=313: 3707/3915 - all misses in ONE model 8f1601234212 (+2 b26a): there NC1 shows EVERY angle slot along the length
  (268 predicted across; other 8.07 models' angle slots are across) -> unexplained -> 8.07 direction 94.7 % -> 8.07 slots stay OFF.
- 21:25Z CODE v written (_sprint/db1-code-v/v/): worker.py CODE z3-db1-2026-10-01v; db1step (old+new rotate slots, engine defaults
  DB1_SLOT_ENGINES=6.87,7.01,7.24,7.30, DB1_V2_SLOT_ENGINES=7.64,8.44,8.53,8.85, panels square/hb), db1bolts2 (+21 no-shift, slot_rot),
  db1old (srot @368), db1bolts (slot_rot passthrough). Box: kit_v2; regression db1v-reg-u / db1v-reg-v (40 models) -> /opt/db1v/regress/{u,v}.
- 21:30Z BROAD SAMPLE (all models finished): per-part selection vs NC drops below 99 % everywhere: 7.24 3123/3271 (95.5 %, 11 models; misses
  = whole groups in 2 models 9e890cef0b3f 126 / 9c7f7a1e7145 22 where the NC has ROUND holes for plies the DB1 marks slotted), 6.87 92.9 %
  (prod ON), 7.01 95.3 % (prod ON), 7.64 97.9 % (prod ON), 8.07 98.0 %, 8.85 94.5 %, 8.44 97.6 %, 7.82 97.7 %. No bolt-string field or
  attr byte separates the missed groups. Suspect stale NC (older revision) -> added 'strict' truth: NC part's full hole-station set must
  equal the DB1 part's bolt stations (same revision). db1v-strict -> out_strict (84 models with truth). V2 engine default reverted to 7.64,8.53.
  Rotation rule final (out_old2): 6,321 / 6,324 direction-checkable parts.
- 22:02Z STRICT (same-revision NC) results: 8.07 selection 5692/5711 (99.67 %, 11 models), direction w/ rotate byte 4060/4268 (95.1 %; all
  206 misses in 8f1601234212 whose NC has every angle slot along; other 10 models 3655/3657). 7.24 2370/2496 (95.0 %; all 126 misses in
  9e890cef0b3f; other 7 models 829/829). 8.85 1650/1750 (94.3 %). 6.87 2916/2969 (98.2 %), 7.01 594/624 (95.2 %), 7.64 4536/4682 (96.9 %).
  DECISION: no engine added (rule >= 99 %); old-engine default reverted to 6.87,7.01. Regression for 7.24/7.30 models re-run with final
  kit (kit_vf, tag vf); other models from tag v (identical code paths).
- 22:20Z CHANGES.md written. Expected: panel tag gone from ~6,290 class-2 models (6,239 on 7.64/7.82/8.07/8.53 + ~50 square-only),
  ~68 models -> class 1; slot / stud tags unchanged by default. Optional env: 8.07 (~830 models lose slot tag), 7.24 (~1,040).
  Waiting for db1v-reg-v to finish, then p71.sh merges v + vf -> regress/vm and runs cmp.py u vm -> evidence/regression_u_vs_v.json.
- 22:45Z REGRESSION u vs v (final code; 40 models, 12 engines, full chain): 40/40 ok in both, 0 worse, 0 invalid solids in both,
  transferred parts identical, total part volume identical in every model. Panel tag lost in 15 models (all panel parts on 7.64/7.82/8.07/8.53;
  squares only on 7.24/8.62/8.85). Slots rotated in 6 models (33/8/56/67/56/632) - volume-neutral. 8.07 (+7.98): the +21 mask fix makes u's
  silent under-count visible: slotted_bolts_cut_round 10->2771, 3->2458, 65->586, 38->66 (7.98 36->84) - more honest tags, same geometry.
  Final strict NC table in evidence/slots_strict_per_model.txt. All db1v units stopped. REPORT.md write was blocked by the harness (report in final message).
