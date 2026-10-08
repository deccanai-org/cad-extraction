## 5. Class-1 lifts: what is real

A row lifts to class 1 only when nothing else blocks it: no stand-ins (source-data-absent ones included), no skipped
pieces, no other issue. In the live index, the rows whose only converter needs are the weight items, or a
weight-gate rejection behind `approx pieces 7.x`, are these. All were re-run on BOX-C and graded with the
coordinator's own `classify_sds2` (current and patched `build_index.py`):

| job | live | v5.5.3 + patch, current rule | + proposed rule |
|---|---|---|---|
| processing-Ted 7.115 (1b5682da, 72f05999) | 2 B: steel 0.793, L family, L8x8x3/4 approximated (B-rep rejected at the gate) | **1**: the exact L8x8x3/4 B-rep is written (catalog 1,556 lb, B-rep 1,563, recorded 4,000: an outlier); steel 1.011 | 1 |
| YSIDRO 7.135 (1b39fd69) | 2 B: steel 0.840, W family, W360x237 approximated | 2: steel 0.923, W 0.917 (`job_mtrl` W360 lb/ft placeholders; exact B-reps) | **1** |
| TEST1 7.331 (799ba840) | 2 C: steel 1.0585 (one exact W10x12) | 2 C | **1** (k_det fillets, section 3b) |
| SHOAL CREEK BLDG-B 7.135 (c46e0c62) | 2 C: L family 0.926 (exact angles with decoded holes) | 2 C | **1** |
| chandu_job 7.323 (ab3b8a66) | 2 B: steel 1.054 (a v4 result) | 2 B: v5.4+ adds bolt-derived / mating-hole stand-ins | 2 B (not a lift) |

(The corpus letter is left out because the simulation has no worker piece inventory, which decides A vs C.)

So: 2 lifts from the converter alone and 3 more if the owner adopts the rule, 5 in all. Every other row of the four
items keeps another class-2 need.
