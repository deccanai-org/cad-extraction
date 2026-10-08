## 0. The four items now (live index 02:51Z) and what this patch does with them

The counts grew since the task was written (58 / 43 / 10 / 15), because the fleet re-ran thousands of SDS2 jobs on
v5.4.1-v5.5.0.

| item | rows now | root causes (proved on the jobs, sections 1-3) | resolution |
|---|---|---|---|
| sds2 stage 2 failure | 68 (class 2, members-only stage 1) | 39 `invalid_solids`, split in two:<br>- 31: the fleet judged the pre-repair read-back block;<br>- 8: the repair pass could not drop parts that failed the assembly check.<br>21 `missing_job_file`: no piece table `subm/subm_idx` in the job folder.<br>6 `steel_weight_mismatch`:<br>- AGRANCLISSEMENT x3: cold-formed studs approximated at 15.9x;<br>- MOUNTAIN VIEW x2: a 14.7x bent-plate fallback;<br>- `test` 8.004: wrong piece-table layout.<br>1 `Bnd_Box is void` (Nantucket).<br>1 v4 `ZeroDivisionError` (Seaport L4) | all fixed in the converter, except the two piece-table-layout jobs (`test`, Seaport), which need the fixer's `slot_size_job` draft. None of them can honestly reach class 1: every one keeps other class-2 needs (sections 1a-1e) |
| valueerror | 15 (class 3) | 13 BG PODIUM / Boston Garden 7.331 were v4 runs (`PLG12x14x300: built-up dimensions match neither name nor weight`, fixed in v5.0); 15-027 CSU 7.312 (stale member records); 100_Binney_Slab 7.243 (no work-point key) | CSU and Binney fixed (class 3 -> class 2 B). BG PODIUM: v5.x no longer raises, but the run is dominated by the assembly check (section 2) |
| sds2 family weight | 718 (class 2) | per family (section 3):<br>- 144 rows only in families whose untagged converter geometry was wrong: RB, WS, TWS, THD, HS, BLT, RD;<br>- 269 rows only in families written as SDS2's own exact B-rep, where SDS2's recorded weight follows its own weight conventions;<br>- 120 rows only in tagged stand-in families;<br>- 185 mixed | converter: fixed. SDS2 weight conventions: proved, plus a proposed grading rule. Stand-ins: graded by the stand-in rule (approx-pieces item) |
| sds2 weight 5% | 73 (class 2) | 29 reused v4 results; 44 v5.x rows dominated by exact W / WT / C (fillets drawn from SDS2's k_det, while the recorded weight is catalog lb/ft) and by exact deck | re-run the v4 rows; the rule makes the 5 % band measure converter-built solids only |

Class-1 lifts are few, and honestly so: of the 859 rows above, the weight item is the only converter need of just
three (section 4). The other rows keep other class-2 needs: approximate 7.1 pieces, joists, envelopes, nominal bolts.
Those belong to other items.
