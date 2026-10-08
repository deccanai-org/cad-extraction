## 3. Weights, per family: converter geometry wrong (fixed) vs SDS2's recorded weight (proved) vs stand-ins

Method. `wdump.py` runs the pipeline's own `to_step2.convert` with the STEP write stubbed. For every piece it dumps:
- SDS2's piece weight and the written solid's weight;
- the builder and the piece-table fields;
- the section record (catalog lb/ft, d, bf, tf, tw, k);
- the piece's own B-rep volume, with and without its decoded holes;
- the stud / rod ring geometry.

Coverage:
- round 1 (v5.4): 51 representative jobs and the 41 v4-reused weight-5% jobs;
- round j2 (v5.5.3): the families new since then (HS, RPL, FL, L, MA, SH, DK, HSS) on 11 jobs.

The family rows of the live index, split by how each flagged family is written:

| geometry of the flagged families in a row | rows | what moves the weight |
|---|---|---|
| exact only (SDS2's own piece B-rep) | 269 | SDS2's weight conventions (3b) |
| built only (untagged converter primitives) | 144 | converter geometry (3a, fixed) |
| tagged stand-ins only | 120 | the stand-in itself (3c) |
| mixed | 185 | the same causes, combined |

### 3a. Converter geometry wrong: fixed in the patch

| family (rows) | what v5.4-v5.5.3 wrote | proof (SDS2's own data) | after the patch |
|---|---|---|---|
| RB round bars (194 built + 49 tagged) | 7.5+ straight-rod guess sized from table `W`, which there is 0.25, not the diameter. Bent / curved bars: only the first ring pair, or a straight bar | STERLING VIII RB3/4 x 648 in: closed B-rep 80.668 lb vs SDS2 80.658 | STERLING 0.112 -> 1.0001 (101 bars exact); THERMOFISHER 0.515 -> 1.003; Cats Rail 0.78 -> 1.005; ASC 0.19 -> 1.0008 |
| WS weld studs (94) | head only: station 3.6875 / radius 0.4375 split by 3-decimal rounding, so the shank ring was lost | P545 WS1/2: true cylinders 0.2750 vs SDS2 0.2749 once the rings merge | P545 0.857 -> 1.0001; EDWARDS AFB 0.146 -> 1.0001 |
| HS headed studs (37: 32 copies of RCMS 7.039, Henderson Hospital 7.618/7.619, 7.135) | RCMS 3.47x on 400 pieces, Henderson 4.47x: wrong rings / straight rods | the stud's own closed B-rep matches SDS2 | RCMS 7.039 and Henderson: HS no longer off (built part 1.0001 / 1.0066); 8.007 23-06 PH exact HS B-reps 0.964 = 16-gon convention (3b) |
| TWS / THD threaded studs (37 / 13) | straight rod with L = table L (holds the diameter on stud records) and d = W | CENTER GROVE THD STUD 3/4: face-vertex extent 2.0 x 0.75 in gives 0.2506 lb = SDS2; SHERIFFS TWS2: 2.5 x 2.0 in gives 2.227 = SDS2 | CENTER GROVE 0.065 -> 1.0001; SHERIFFS 0.0195 -> 1.0001 |
| BLT SDS2 bolt pieces (20) | shank lost (0.3125 split); hex head as a cylinder through its corners (+21 %) | ASC 1/2 x 3 1/2: SDS2 0.245 lb; hex prism of the stored 6 vertices + shank 0.2535 | ASC 1.085 -> 1.036 |
| MA (Queen Street 7.708, 4 rows) | 3.47x | same mechanism | no longer off |
| exact pieces rejected by the 0.6-1.6 weight gate: PL, L, ROUND, W, cold-formed `?` | approximation (profile / plate fallback) because SDS2's recorded weight disagrees with SDS2's own stock | EDWARDS AFB PL3/8x3 5/16: L x W x T 7.93 lb, B-rep 7.83, recorded 4.69. processing-Ted L8x8x3/4: catalog 1,556 lb, B-rep 1,563, recorded 4,000. YSIDRO W360x237/x382/x463: `job_mtrl` gives all three 335.3 lb/ft (placeholder); the B-reps are 163 / 261 / 315 lb/ft. AGRANCLISSEMENT 254S89-144M (16 ga stud): record 7.53 lb/ft, B-rep 3.71 lb/ft | exact B-rep when it equals SDS2's own stock; listed in `weight_check.sds2_weight_outliers` and kept out of the ratio. processing-Ted 0.793 -> 1.011; AGRANCLISSEMENT 1.652 -> 1.020; YSIDRO 0.840 -> 0.923 |

### 3b. SDS2's recorded weight is a table / convention; the solid is SDS2's exact B-rep (no converter fix; grading rule)

| family (rows exact-only) | solid / SDS2 | proof |
|---|---|---|
| W, WT, C, MC, S, H (73 / 33 / 36 / 2 / -, 4) | +2.5 ... +8 % (lighter sections higher) | SDS2's B-rep section carries fillets of radius k - tf from the section's own `k` field (k_det), while the recorded weight is catalog lb/ft x L.<br>- W10x12 (TEST1): catalog 12 lb/ft x L = SDS2 3,393.9 lb exactly; B-rep 3,592.5 (+5.85 %); plates 3.459 in² + 4(1 - π/4)(0.75 - 0.21)² = 3.709 in².<br>- RCMS C3x6: catalog 65.72 = SDS2, B-rep 69.88 |
| CK / DK steel deck (75 / 16) | +11.2 ... +11.8 % (1 1/2 in deck), +27.7 % (1 in) | every deck piece in 6 jobs: SDS2 weight = 0.100 in (void: 0.1345 in) x the B-rep's developed area x 0.2836 lb/in³, to 4 digits. 19156_610 DK1 1/2x36: 152.37 vs B-rep 170.13 |
| PL / FL / RPL / L with decoded holes (14 / 70 / 32 / 33) | 0.80 ... 0.95 | the recorded weight is the gross stock, the B-rep has SDS2's own decoded holes / slots cut:<br>- RCMS RPL1x2: B-rep 0.7363 = SDS2 0.7362; with its 13/16 hole 0.5893 (0.807).<br>- RCMS FL1/2x4 1/2: L x W x T 6.062 = SDS2 6.0616 = B-rep; 3 holes -> 5.0915.<br>- THIRD DISTRICT L4x3x5/16 x 17.5: catalog 10.5 = SDS2; B-rep 10.595, 6 holes -> 9.887 (0.94).<br>- bernardPSC FL3/8x4: SDS2 3.614 removes less than the stored 13/16 x 1 13/16 slots (B-rep 3.829 -> 3.404) |
| CP / CHKD checkered plate (19 / 16) | 3/8: 0.936; 1/4: 0.907; 1/8: 0.829 | SDS2 weight = area x AISC floor-plate weight (1/8 6.16, 1/4 11.26, 3/8 16.37 psf). SOCORRO CHKD1/4: 6.595 ft² x 11.26 = 74.27 lb = SDS2; the B-rep is the flat plate (no lugs in the data) |
| ROUND / HSS exact (68 / 30) | 0.93 | B-rep wall = design thickness (0.93 x nominal), recorded weight on nominal (Cutler Ice Shield, 1,981 pieces; RCMS ROUND 0.9347) |
| SD (dome) (4) | 0.6667 exactly | SDS2 weighs it as the bounding cylinder; the B-rep is the dome (2/3) |
| HD / HSA / WS / HS exact stud B-reps | 0.96 | 16-gon faceted solid vs SDS2's true-cylinder weight |

### 3c. Tagged stand-ins (already graded as stand-ins: item "sds2 approx pieces", not this patch)

- CV clevis (75), TB turnbuckle (40), ADJ / BPL bent plates, HSS / W / ROUND `profile_fallback` on open B-reps.
  Examples: Henderson W 1.94x, HSS 1.80x; NWCC HSS 3.15x; 19156_610 BPL 8.0x.
- One case was gross enough to stop stage 2 and is gated here (section 1c): MOUNTAIN VIEW, 300 x BPL10GAx83 3/16 at
  14.7x. The 5-10x fallbacks (19156_610 BPL 8.0x) remain for that item.
