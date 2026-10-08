## 4. Proposed grading rule (owner / lead decision: `coord-build_index.patch`)

The patched converter splits the weight tally by geometry source:
- `weight_check.by_source.{exact, built, standin}`, with the same three parts in every `by_family` entry;
- `exact`: SDS2's own piece B-rep;
- `built`: solids the converter constructs and writes untagged (stud / rod / bolt cylinders, hex prisms);
- `standin`: tagged `[approx: ...]` solids.

The weight check exists to catch converter geometry that is wrong *without* a tag. Section 3b shows that exact
B-reps differ from SDS2's recorded weight only through SDS2's own tables and conventions:
- k_det fillets;
- deck at 0.100 in;
- floor-plate psf;
- gross stock with holes and slots ignored;
- design wall thickness;
- domes weighed as cylinders.

Tagged stand-ins are already graded by the stand-in rule. The proposal:
1. **Class-1 5 % band** on `(exact_sds2 + standin_sds2 + built_step) / total_sds2`. Only untagged converter-built
   solids move it. The 0.75-1.3 "broken" band stays on the overall ratio, to catch gross decoding errors.
2. **Family 5 % rule** (n >= 5) on the `built` part of each family.
3. **Info only**, no class effect:
   - exact families outside 0.85-1.2 ("SDS/2 recorded weight differs from its own piece B-rep ... SDS/2 weight
     tables / conventions, not converter geometry");
   - the `sds2_weight_outliers` count.
4. Manifests without the split (v5.5.3 and older) keep today's rule.

`RULES` keys: `sds2_weight_converter_built_only` (default true) and `sds2_exact_family_band` ([0.85, 1.2]).

The same patch maps the new stand-in type `unindexed_brep` to `source_file_missing | sds2 piece table absent`.
Without that mapping it would fall to the generic `converter_feature` key.

`fleet-worker.patch` does two things:
- passes the split and the outlier count through `manifest_summary`;
- makes `parse_extra` read the last read-back block (the acceptance counts come from the converter's
  `run_batch.parse_log`, fixed in the converter patch).
