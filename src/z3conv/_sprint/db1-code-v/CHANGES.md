# DB1 code v (z3-db1-2026-10-01v) - changes vs u

Files: v/db1step.py, v/db1bolts2.py, v/db1old.py, v/db1bolts.py, v/worker.py (patch: db1-code-v.patch). Not deployed.

1. Tekla "rotate slots" decoded and applied (env DB1_SLOT_ROTATE=1, default on).
   - Old engines (< 7.5): byte @368 of the part-attribute record (stride 373), new field `srot` -> member `slot_rot` -> bolt `slot_rot`.
   - 7.x new-path bolt strings (attribute stride 389, 7.64 / 7.82): byte @385.
   - 8.x / 9.x own bolt table: byte @265 + shift (stride 317: 8.44 / 8.53 / 8.85; 8.07 shift 48).
   - Values: 0 none, 1 = rotate the even plies (2nd, 4th from the bolt head), 2 = rotate the odd plies (1st, 3rd). A rotated ply
     gets the slot turned 90 deg (slot x <-> slot y). Any other value -> group left undecided (cut round, tagged as before).
   - Groups with every ply slotted and rotation set are now ranked by ply (before: shortcut without ranking); unrankable -> undecided.
   - Effect on the engines already ON (6.87, 7.01, 7.64, 8.53): u wrote those slots 90 deg off. New stat bolt_stats.slots_rotated.
2. 8.x slot ply selection (`slot_parts`) read at +21 with no variable-block shift (env DB1_SLOTPARTS_NOSHIFT=1). Only changes 8.07
   (shift 48; u read +69 = garbage / 0). No effect while 8.07 slots stay off; 8.53 / 8.85 / 8.44 have shift 0 (unchanged).
3. Slot engines unchanged: DB1_SLOT_ENGINES default 6.87,7.01; DB1_V2_SLOT_ENGINES default 7.64,8.53 (no other engine reached
   >= 99 % per part vs Tekla NC1 on a multi-model sample; see REPORT.md). Turning one on is an env change only.
4. Panels (`A*B` names with no prefix):
   - `A*A` (square): source `parametric_rect_square` (exact, no tag) on every engine (env DB1_PANEL_SQUARE_EXACT=1).
   - `A*B`: source `parametric_rect_hb` (exact, A = height along the part y, B along x) on DB1_PANEL_AXB_ENGINES=7.64,7.82,8.07,8.53;
     other engines keep `parametric_panel` (tag "orientation assumed"). Geometry is identical to u; only the source label / tag changes.
5. Headed studs: unchanged (stand-in stays; see REPORT.md).
6. worker.py: CODE = 'z3-db1-2026-10-01v' + history comment.
