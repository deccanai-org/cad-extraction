# Adversarial review of stream "ifcxml" (ifcxml2spf 1.1.1 + worker patches)

Reviewer verdict: **CONFIRMED WITH CAVEATS**. The headline claims hold. My independent re-runs on BOX-A reproduce every
number, and they also hold on real cases the stream never looked at. One latent integration defect (F1) must be fixed:
a conversion that loses data still grades as `status ok`. It does not affect the 8 data-4 models.

Everything heavy ran on BOX-A (i-0c694360a18d7759f) under `/work/agentwork/ifcxml-review` (my own dir; never more than about 16
threads). Scripts are staged at `s3://annotationprod/cad-disk-extract/_control/z3conv/agentjobs/ifcxml-review/`. Results
are under `s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/ifcxml-review/` (r1_results.json,
indep/, sib/, r4_results.json, inv6.txt, valerr_result.json, harness_live/, harness_valerr/, listing.json).
Converter under test: md5 4d09bf7a0ce7fea567ccbd57062169d2. The same file is in the Mac dir, in `fixes/ifcxml/`, and in the live kit.

## 1. Re-run of the stream's evidence (BOX-A)
- **Conversion of the 8 data-4 inputs:** all 8 return rc 0.
  - Instance counts are 397,657 / 270,364 / 100,619 / 93,504 / 77,993 x2 / 28,040 / 12,314, totalling 1,058,484.
  - The SPF DATA-section sha256 is identical to the stream's `spf_final.json` for 8/8.
  - ifcopenshell 0.8.4.post1 opens all 8.
- **Independent XML-to-SPF checker** (`indep_check.py`, written from scratch; it imports nothing from the stream): **8/8 pass**.
  - It compared 1,058,484 instances, 2,291,499 attributes, 2,234,151 references and 1,866,644 scalars (918,067 of them reals, compared bit-exact through `float()`), plus 210,577 typed select values.
  - 0 mismatches.
  - Fabrication check: 295,809 attributes are absent from the XML, and 0 of them have a value in the SPF. 0 SPF instances lack an XML source. Per-type counts are equal.
  - These totals equal the stream's validator totals exactly.
- **Expected parts counted directly from the XML** (IfcElement with a Representation, excluding openings): 8,293 + 2,237 + 430 + 430 + 1,940 + 1,940 + 541 + 283 = **16,094**. This equals the census figure the stream reports, so the census computed on the SPF is not hiding losses.
- **Kit chain re-run** (stream kit copy, ifc2step6 6.0.1): within-5% volume counts are bf3bffbf2f32 242/242, bbfaf0a7d8e7 257/283, 895f3bf617be 257/283 and c452935b7eff 268/271. Coverage is 1.0 everywhere. All match the table.
- **Live deployed kit** (`z3-ifc-2026-10-01a+s6.1+x1`; the patch is already in s3 `.../z3conv/ifc/worker.py`) in a non-publishing harness:
  - 8/8 ifcXML jobs return `status ok` / `ok_solid` with the same parts, coverage and volumes. The only drift is from ifc2step6 6.1: OZARK has 17,138 solids instead of 17,141, and 6,412 volumes checked instead of 6,413.
  - 3/3 Revit zips return `not_ifc_xml_tekla_export_to_revit`.
  - SPF regression: 3/3 SPF inputs are ok (6ce2aeb6c67d 283 parts, b4f9240c55ce 2,350, 5b1331b4dc05 35).
- **Data-4 patched worker** (`z4-ifc-2026-09-30f+x1`, ifc2step5). The stream did not run this one; I did:
  - bf3bffbf2f32 (ifcXML) is ok with 430 parts and 2,683 solids.
  - SPF 6ce2aeb6c67d is ok with 283 parts, the same as the fleet's original result.
  - 2 jobs could not be tested because their bim keys do not exist in the annotationprod bucket that the d4 kit reads from (404). That is not a patch fault.
  - Side effect: the d4 harness uploads landed in `annotationprod` under my review prefix. I copied them locally and deleted them, so 0 objects are left.
- **The 21 `not_step21` zips:** every one gives ifcxml2spf rc 2 with root `NewDataSet`. None contains an .ifc or ifcXML member, so class 3 is correct.
  - Correction to the stream's text: 11 hold Levels + DataInformation + Profiles, **9 hold only `<name>_Levels.xml`**, and 1 also holds a log. The log reads "Tekla Structures 18.1 … Successful exports: 0 … Untransferrable … Antimaterial 2".
  - The "Export-to-Revit" label is an interpretation; what is proven is "an IFC export with no exported objects".

## 2. Different real cases
- **Independent ground truth from the exporter itself.**
  - Data-4 holds Tekla's own SPF export of the Deep Well model: 6ce2aeb6c67d, `MONSANTO(LULING-DEEP WELL PLATFORM)/out.ifcZIP` → `out.ifc`, Tekla 16.1, dated 2014-08-15.
  - Compared with the converted 895f3bf617be ifcXML:
    - Instances: 12,314 = 12,314, with no per-type differences.
    - Products: 392/392 matched by GlobalId, 0 class or name mismatches.
    - Absolute placement: maximum difference 5e-5 mm.
    - Mesh volume: **391/392 within 1e-6 relative, 392/392 within 1%**; totals 0.886028495 vs 0.886028499 m3.
    - Through the live worker: SPF 283 parts with 257/283 volumes within, ifcXML 283 parts with 257/283 within — identical.
  - The Deep1 HANDRAIL volume outlier (x44 / x74) is a source difference: the extrusion depth is 20,634 mm in Deep1 against 287 mm in out.ifc. It is not a conversion error.
- **20 public ifcXML files from other exporters.**
  - Revit IFC2x3 (Green-Resilience: 4Room x5, Single_Room x2, L_1Floor 16,710 instances, L_2Floor 18.5 MB / 63,842 instances, Vet_Center 11,800), GeometryGym and Revit-beams, IfcObjAsm hellowall: my independent checker passes 12 of 13 numeric-id IFC2X3 files with 0 mismatches.
  - The 13th, 4Room.ifcxml, has a **broken source**: refs i20419 and i20425 are never defined, ContextOfItems points to IfcBuilding i1733, and PlacementRelTo points to IfcRectangleProfileDef i1770. The converter wrote all three refs verbatim (`#20433=IFCPRODUCTDEFINITIONSHAPE($,$,(#20425,#20419,#20431))`) and returned rc 4.
  - jmirtsch "revit beams" against its SPF sibling: 154 = 154 instances, 0 type differences, placement difference 3e-6, volumes equal within 2e-11. The kit gives 2/2 parts and an identical bbox for both.
  - GeometryGym IFC4 pairs: the instance difference against the SPF comes from the XML itself (IfcPlane / IfcSIUnit / IfcAxis2Placement2D missing from the XML; confirmed with grep). Converter output equals the XML.
  - Kit chain on the converted Revit SPFs: coverage 1.0 everywhere, 0 invalid solids (for example L_2Floor: 342 parts, 854 valid solids).
- **Robustness mutations of the real Deep1.ifcXML.** Sorted DATA (93,506 lines) is identical for gzip, no XML declaration, prefix `ex:`→`q9:`, and an ElementTree re-serialisation with every pos-aggregate reversed and the top-level instance order reversed.

## 3. Defects found
- **F1 (must fix before relying on the patch; latent, no current data affected): data loss and a fabricated location pass as `status ok` and are class-1-eligible.**
  - Mechanism:
    - `Converter.entity()` calls `self.defined.add(n)` before building the values. When a value raises, the instance is never written but still counts as "defined", so its references are **not reported as dangling**.
    - rc 4 (value errors or dangling references) is then accepted by the worker patch (`rcx not in (0, 4)` → fail; otherwise continue).
    - The only trace left is `input_fix: ifcxml_converted_to_spf_with_dangling_references`.
    - `coord/build_index.py` does not treat that input_fix as an issue; only `truncated_tail_repaired` blocks.
  - Demonstration: in the real Deep.ifcZIP (bf3bffbf2f32) I changed ONE coordinate text, `2463.064449` → `2463.064449.5`. This is the placement point of the ANGLE part 1JxSlL0000234qC3WmEJCs.
    - The converter returns rc 4 `converted_with_value_errors` and reports **dangling_references 0**. In fact the SPF holds 1 reference to the undefined #11599.
    - The live worker returns **status ok**, ok_solid, coverage 1.0, 430/430 parts, 2,683/2,683 valid solids and 242/242 volumes within 5%. Every grade signal is the same as the unmodified file.
    - But the ANGLE was moved from bbox x 2437–2488 / y 8102–8407 / z 7899–7975 to x -25–25 / y 0–305 / z -38–38: the kernel put the missing Location at the origin. The model bbox z-min went from 3530 to -38.
  - The same pass-through applies to true dangling references in a source (4Room: 2; EnEff VDI 6020: refs i48 and i50 are never defined).
  - Fix:
    1. In `entity()`, add to `defined` only after the instance is written (or record failed ids as dangling).
    2. In the worker, treat `value_errors` as a fail, or at least add an issue so the model is capped at class 2.
    3. In build_index, map `ifcxml_converted_to_spf_with_dangling_references` to an issue.
- **F2 (minor):** UTF-16 input is silently renumbered. `prescan_ids` is a byte regex and sees 0 ids, yet the report still says `numeric_kept: true`. I verified that the output is identical after id mapping (93,504 lines), so no geometry is affected, but the #N = iN traceability breaks.
- **F3 (minor):** in a zip, the member chosen is the largest .xml. An .ifcZIP holding ifcXML plus a larger non-IFC .xml returns rc 2 (`not_ifc_xml`); demonstrated with a decoy. Not seen in the data.
- **F4 (minor):** an input that yields 0 instances returns rc 0 `converted` (IfcObjAsm hellowall-refs.ifcxml: 22 unknown top-level `<include>`, 0 instances). It should be a non-zero rc.
- **F5 (reporting):** the 9/21 single-member zips noted in section 1. The stream's own IFC4 sibling comparison, `wall-with-opening-and-window`, has verdict "differences" (a missing IfcProjectLibrary), and the summary does not mention it. I traced it to the sample XML, which lacks the library, so it is not a converter loss.

## 4. Not refuted / checked OK
- No geometry is invented on any of the 8. All 8 stay rc 0 with 0 value errors and 0 dangling references.
- The class-1 claim for bf3bffbf2f32 holds under the z3-rules-1 class rules (coverage 1.0, 242/242 volumes, no blocking v6 tags; `approx-curved` is info-only).
- The sniff change is safe for SPF heads. It only reroutes heads that start with `<` (after BOM/whitespace) or a UTF-16 BOM; those previously failed as not_step21 and now fail as not_ifc_xml.
- Discovery: see section 5. It is a listing cross-check that does not depend on manifests.

## 5. Discovery cross-check (S3 listing, independent of manifests)
- `list_ifcx.py` listed the stored objects under the data-4 / data-3 / data-2 extracted prefixes, `dataset/main/3d`, Disk-1 and Disk-2, keeping keys that contain ifcxml / ifczip or `.xml` with `ifc` in the basename. It then sniffed every hit.
- It listed 16,715,770 keys in the 30-minute cap and **did not finish**: 7,045 of 7,639 top prefixes were truncated, including 2,393 data-3 and 879 data-4 prefixes. **This cross-check is partial.**
- Within the part it covered, 2,989 hits were sniffed:
  - 3 plain ifcXML and 2 ifcZIP files with an ifcXML member. All 5 are among the stream's 8 candidates, so 0 are new.
  - Data-3 hits are 1 ifcZIP holding an SPF member (`ISO-10303-21.txt`) and 6 `EncryptedData` .xml files. This matches the stream's "data-3 has no ifcXML".
- Other public sources found while looking for test cases (GitHub): none bear on the data. All 20 were tested in section 2.

## 6. Box use and cleanup
- All heavy work ran on BOX-A at about 16 threads or fewer. Nothing was published. I launched no instances and killed no processes.
- Box intermediates were deleted: 1.5 GB down to 9.5 MB.
- In S3 I removed the large STEP / mutated-input objects from my review prefix, leaving 65 objects (4.8 MB).
- My stray d4 harness uploads in annotationprod (my review prefix only) were copied and deleted.
- Reviewer tools are in `/tmp/ifcxml_rev/` on the Mac and at `s3://annotationprod/.../agentjobs/ifcxml-review/`: `indep_check.py`, `sib_compare.py`, `mutate.py`, `mut_valerr.py`, `list_ifcx.py`, `utf16_iso.py`, `harness_rev.py`, `driver_r1.py`, `driver_r4.py`.
