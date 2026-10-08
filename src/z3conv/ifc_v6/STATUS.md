# ifc2step6 work status (resume note)

Live: 6.1.5 deployed by the builder 05:26Z (6.1.3 04:06Z, 6.1.4 tested on the Tekla OOM models). Earlier: 6.1.2 deployed by the builder (a965852984ca96fd8) 02:55Z; 6.1.3 handed over (release zip sha b7ee187a…,
ifc2step6.py sha 4d1c0695…) at s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifcv6/release/.
Source of truth: /Users/dhiren/Downloads/Deccan/z3conv/ifc_v6/ifc2step6.py (+ CHANGES.md).

Running (final 81-model regression of 6.1.3 vs v5 on the current grader kit):
- BOX-A i-0c694360a18d7759f: /work/agentwork/ifcv6, label v6z (ids_a: big + half), results uploaded at the end to
  s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifcv6/v6z/; 0b3b8b2f final-code check
  in w/tclip.
- ifcv6 test box i-07e998cae8617b25c: /scratch/v6, label v6z2 (ids_b); upload with /tmp/v6/s_up5n.sh pattern
  (change v5n -> v6z2) to s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_dev/ifcv6/v6z2/.
- v5 baseline (current grader): s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_dev/ifcv6/v5n/ (81 done).
- Report: regress/report.py TESTSET v5dir v6dir OUT.md (merge v6z + v6z2 into one dir first).

To do: regression table -> coordinator; release the ifcv6 test box (it self-terminates 90 min after /opt/v6/alive
stops being touched; hard cap 10 h from launch) and clean /work/agentwork/ifcv6 on BOX-A.
Rules: no writes to kit/control files; S3 writes only under agentjobs/ifcv6, ifc_v6dev, _dev/ifcv6, agentwork/ifcv6.

Update: regression report in REGRESSION.md (78/81 graded both ways); ifcv6 test box released (shutdown) after the run; BOX-A v6z job finishes 4efa1dc5 + 0fc26e2e read-backs and uploads to agentwork/ifcv6/v6z on its own.

Correction 06:0xZ: the ifcv6 test box had a builder fleet worker loop on it; I had already shut it down (terminated 05:51Z). Builder and coordinator notified to requeue its in-flight jobs. BOX-A is left alone (releases with the RELEASE flag).

## 6.1.6 (prepared 2026-10-02 ~03:15 local, NOT deployed yet - SSO expired)

Change vs 6.1.5 (live): (1) opening-tool repair retry-only - only products with openings whose kernel result with the
ORIGINAL tools is empty are rerun with repaired tools, tools restored after (verifier: 6.1.2+ lost 36 parts on SDS/2
pipe-cope models 7ec85dca / 1ea774eb / c8f3e1a6, 60 solids -> open-surface); (2) far mode hard-off - V6_FAR_VERIFY
ignored (the builder set it =1 in the worker env; now a no-op), V6_FAR_VERIFY_TEST=1 for tests only.
Release zip (local only): ifc_v6/release/ifc2step6_6.1.6.zip sha256 9bea4d57b443f95001a3b66bd1ab53e0c791d89e73d543ee52f9460887594725;
ifc2step6.py sha256 4dafd7f3b09c83a3cb3c1485de5a0d7b70a2cb1ecfbaf1ce088300a180bbf39a. Previous: /tmp/v6/ifc2step6_615_backup.py.

Local test (Mac, nice 19, 1 thread, converter only; /tmp/v6/pc): 6.1.5 vs 6.1.6 identical on all 3 pipe-cope models
(80 / 136 / 944 parts, 0 missing, 0 changed volumes, all L0, no open-surface; repair never triggered in 6.1.6 because no
product was empty with the original tools). The verifier's loss does NOT reproduce on macOS arm64 - likely depends on
the Linux OCC booleans -> must be confirmed on BOX-A.

After the owner logs in (annotationprod-publish SSO):
1. Upload: aws s3 cp ifc_v6/release/ifc2step6_6.1.6.zip and ifc2step6.py to
   s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifcv6/release/ (my prefix only; echo dest first).
2. BOX-A (i-0c694360a18d7759f, /work/agentwork/ifcv6): stage ifc2step6_616.py in agentjobs/ifcv6, download the 3
   pipe-cope inputs (keys in /tmp/v6/pipecope.json) into in/, run dev/run_case.py with 6.1.5 and 6.1.6 on
   7ec85dca, 1ea774eb, c8f3e1a6 (+ 0933b1c1, 0813) - pass = pipe-cope coverage_all 1.0 under 6.1.6, 0933/0813 0 invalid
   (0933: 10, 0813: 2 open-source surfaces as before).
3. Hand to the builder a965852984ca96fd8 (zip key + shas + results); tell the coordinator.
Do not stop any box without the coordinator's OK (the ifcv6 test box had a fleet worker loop; it is terminated).

## 6.1.6 / 6.1.7 (2026-10-02)
- 6.1.6 deployed by the builder 17:43Z (pipe-cope coverage back to 1.0 on BOX-A; far mode off).
- 6.1.7 handed over (~19:40Z): release/ifc2step6_6.1.7.zip sha256 c1448c0bcafe2c722bba92bbde782f8a755c7dfdabc46da7ed0f2e75212eb18d;
  verify time budget (V6_VERIFY_BUDGET_S 2 h, capped at 85% of V6_TOTAL_BUDGET_S / IFC_TIMEOUT_S), fork isolation Linux-only.
- Confirmation run in progress on BOX-A: /work/agentwork/ifcv6/w/t617/big.{log,json,rc} (ca769beb, 1.2 GB, 6.1.7-rc =
  6.1.7 without the total cap). To report: when verify hits the budget (verify_partial count, total_sec, rc 0).
- Note: Mac-local tests of 6.1.4-6.1.6 were invalid for kernel parts (fork children died on macOS); fixed in 6.1.7.

## 6.1.8-rc (2026-10-02 ~21:40Z)
- Items: (1) v6_L1_tessellated_analytic (30 L1-only models), (2) v6_open_in_source_healed (62 OIS-only models),
  410b3c2decb3 missing beam, aa22160f pipeline parts_without_solid list (18 models), coordinator follow-ups:
  coplanar overlap union (14 models), sew_max_mm count over class-1 models.
- Release: release/ifc2step6_6.1.8-rc.zip sha256 0b18fa628c40076e3705b1bc04f8fee6781e5f14667e57096a895471b65c0fc6,
  ifc2step6.py sha256 6ace8612c260899a98676adeae6efaad7147089a16776e99d01885d4ea362618; uploaded to
  agentjobs/ifcv6/release/ifc2step6_6.1.8-rc.{zip,py}. Previous: /tmp/v6/ifc2step6_617_backup.py (= 6.1.7).
- Canary: builder runs agentjobs/ifcv6/canary618_jobs.json (122 models) on the fleet with 6.1.7 and 6.1.8-rc; I compare
  and give go/no-go.
- OIS probe (BOX-A oisp/, build only): 856 old-OIS parts -> 6.1.7 closes 210, 6.1.8 234 (+coplanar union); remaining open
  gaps are missing / overlapping faces (571 > 10 mm), none <= 0.01 mm.
- BOX-A: ca769beb (t617) still running (verify budget ~22:13Z); sew probe sewp/ (145 class-1 sewn models).
- Open: ecae31e1 w18078 (kernel boolean drops faces; needs OCC cut of the exact faceted body); far-model L1 (OCC in-place
  precision at 3e9 mm).
- 22:05Z: canary started 21:57:44Z on ifc1 (builder; 3 slots each): outputs conversions/ifc-step/<id>.v618-rc.* and
  .v617-ctl.*, results _state/conv/ifc/detail/<id>.{v618-rc,v617-ctl}.result.json. Compare: /tmp/v6/canary/compare.py
  --fetch (INDEX_WORK=/tmp/v6/index, local env python).
- 6.1.8 final package ready locally (NOT uploaded): /tmp/v6/rel618f/ifc2step6_6.1.8.zip sha256
  3203d3852f943152fd9a5fbb28428d50d20f90532df7b9b21e702e46d647638f, ifc2step6.py sha256
  afce7707465d07dca83740ed81e02769071015eee3a2f0567b0e564208dc0b31 (= rc + leader-clustering sew + GAP_CLOSE_MM 0.1;
  approved by the coordinator to ship once the rc canary passes; then confirm canary on the 38 class-1 models with
  sew_max_mm > 0.01 - list from /tmp/v6/sewp/all.jsonl).
- Working copy = 6.1.9-dev: + contact-wall regions (786aab37 7 L4 -> L0), + exact OCC opening cut (ecae31e1 L4 -> L0).
  BOX-A d619p batch (pipeline set) running.
- Local converter tests MUST pass --prec 2 (CLI default is 6; the worker passes 2).
- Sources found defective: 0614136c ch40/ch45 (OCC argument analyzer: faulty / self-intersecting, OCC inverts volume).

## 23:20Z 2026-10-02
- 6.1.8 final shipped (GO 23:10Z): release/ifc2step6_6.1.8.zip sha256 3203d385..., py afce7707...; builder deploying with
  best-of; grader rule sent (sew_max_mm / gap_max_mm / open_shell / coplanar_overlap_merged). Canary 6.1.7 vs 6.1.8-rc:
  112/122 compared, 0 regressions, 19 lifted 2->1 (compare: /tmp/v6/canary/compare.py, results compare.json).
- Confirm canary requested: sewconfirm618_jobs.json (38 class-1 models with sew_max_mm > 0.01).
- 6.1.9-rc uploaded: release/ifc2step6_6.1.9-rc.zip sha256 aebaa3e5..., py 381ec711...; canary list canary619_jobs.json
  (18 pipeline + 12 controls), builder to run after 6.1.8 is live (6.1.9-rc vs 6.1.8).
  6.1.9: contact-wall regions, exact OCC opening cut (polygon extraction), exact polygon-extrusion fallback (also shared
  geometry), l1_planar_exact / l1_check sidecar fields (coordinator rule (b) per part).
- Open: f7664cd2 B_99/101/102 (planarity tol 0.01 -> 0.05 would close; global change), B_240 / weld-3W553 pinched
  shells (optional), far-model L1 = OCC in-place precision (grader rule (b) per part now).

## 23:50Z 2026-10-02
- BOX-A: my work stopped and /work/agentwork/ifcv6 removed (results: s3 bim .../_state/agentwork/ifcv6/{d619p,d619q,...}).
- 6.1.9 final packaged locally: /tmp/v6/rel619f/ifc2step6_6.1.9.zip sha256 fe5e2793..., py c2da1285...
  (= 6.1.9-rc + exact-fallback time budget 900 s). Upload with the GO after the fleet canary (.v619-rc vs .v618-ctl,
  compare: /tmp/v6/canary/compare2.py /tmp/v6/up618/canary619_jobs.json v618-ctl v619-rc --fetch).
- 6.1.10-rc packaged locally: /tmp/v6/rel6110/ifc2step6_6.1.10-rc.zip (planarity accept 0.05 mm + pinch split); NOTE
  rel6110 was zipped BEFORE the exact-fallback budget was added to /tmp/v6/ifc2step6_6110rc.py - re-zip from that file.
- Working copy ifc2step6.py = 6.1.9-rc + budget (VERSION string 6.1.9-rc).
- 00:05Z: 6.1.10-rc uploaded (release/ifc2step6_6.1.10-rc.{zip,py}; zip b301f5a9..., py dbd8ce3e...; list
  canary6110_jobs.json 29 models). 6.1.9-rc canary waiting on owner permission rules (suffixes .v619-rc / .v618-ctl).
- Production check: 54 models with v617 and v618 production results: all class 2 both, 0 regressions, L4 1503 -> 1012.
- step_duplicate_parts = duplicate GlobalIds in the SOURCE (e0fb748a: 26 IfcMechanicalFastener GUIDs twice).
- 6.1.11-dev (/tmp/v6/ifc2step6_6111dev.py): exact_open with curved opening tools via the kernel's own B-rep of the
  opening (world mm), result meshed + approx-curved (1ea774eb pp11304: closed, vol 1,212,259 vs body 1,213,482).
- Not done: e0fb748a C_7/C_8 = IfcBooleanClippingResult inside an IfcMappedItem (exact_clip skips mapped items);
  7b35850c a122_1 invalid at all levels.
- 00:45Z: 6.1.9 final GO (release/ifc2step6_6.1.9.{zip,py}: zip fe5e2793..., py c2da1285...). Canary 6.1.8-ctl vs
  6.1.9-rc: 24/30, 0 regressions, 3 lifted. Working copy ifc2step6.py = 6.1.10-rc (dbd8ce3e...); 6.1.11-dev at
  /tmp/v6/ifc2step6_6111dev.py (curved opening tools). Next: 6.1.10-rc canary go/no-go
  (compare2.py /tmp/v6/up618/canary6110_jobs.json v619-ctl|v618-ctl v6110-rc --fetch).
- 01:30Z: 6.1.10 final GO (release/ifc2step6_6.1.10.{zip,py}: zip 90a892f3..., py 35e610b4...). Canary 6.1.9-ctl vs
  6.1.10-rc: 22/29, 0 regressions, controls unchanged. Working copy ifc2step6.py = 6.1.10 final.
  Builder re-targets with the narrow filter (class 2 with OIS/L4/L3/pipeline parts_without_solid AND
  faces_nonplanar_triangulated > 0 or pinched open_shell).
- Next: 6.1.11-dev (/tmp/v6/ifc2step6_6111dev.py, based on 6.1.10-rc): curved opening tools via kernel B-rep.

## 02:xxZ 2026-10-03 (data-3 IFC class-2 push)
- Analysis of index (bim .../_state/conv/index.jsonl.gz, 1,672 IFC class 2): /tmp/v6/d3/ (det/, side/, stats/, live/).
  step_duplicate_parts = source GUID collisions in 548/548 (step dups == src_parts dups) -> grader info rule
  (source_duplicate_globalids) lifts 72. 195 rows on Disk-1/2 v5 .stp chosen by build_index "exact parts" rank -> grader
  rank fix + re-run. 400 rows have no source-bound blocker.
- 6.1.11-rc2 (/tmp/v6/ifc2step6_6111dev.py; release/ifc2step6_6.1.11-rc2.{zip,py}: zip 71ac2b28..., py 9de189c0...):
  6.1.10 + curved opening tools / curved body via kernel B-rep + closed surface models as solids.
- Canary requested: canary6111b_jobs.json (340: 195 old-reused, 133 no-source, 12 controls), .v6111-rc2 vs .v6110-ctl.
  Compare: compare2.py /tmp/v6/up618/canary6111b_jobs.json v6110-ctl v6111-rc2 --fetch.
