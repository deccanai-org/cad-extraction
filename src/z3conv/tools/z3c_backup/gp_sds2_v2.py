"""Grader patches for SDS2 rows (coord/build_index.py), from the sds2_step_verifier review. For the builder to apply;
nothing here runs by itself.

Which verifier checks our SDS2 grading lacks (and what to do):
  G4 duplicates    LACKING before v5.5.11. Converter v5.5.11 now writes converter-made repeats once
                   (converter_duplicates_removed, counted in converter_duplicates_skipped as before) and keeps SDS2's own
                   duplicate placements as stored (source_duplicate_placements). Both are counted in
                   counts.duplicate_placements. Decision 2026-10-02: neither blocks class 1. Patch A records them as
                   info. Not computable from _pieces.csv: it has origins but no rotation (an origin-only test flags 9 on
                   8d3cfac8 where 3 are real).
  G2 connectivity  LACKING, not cheap here (needs per-solid boxes). False positives on steel-in-concrete jobs
                   (6eeedc27: column segments with an 18-in gap at every floor). The verify job records it as NOTE.
  G3 piece-parent  LACKING, needs member geometry: the verify job records it as NOTE.
  G1 work line     NA for stage 2 (the verifier itself skips it); stage-1 rows are never class 1.
  S4 units/extent  HAVE: bbox_absurd + the converter writes MM only. Skip (duplicate).
  C1 completeness  HAVE (coverage from placed vs written + skipped list); the verifier's C1 uses an older copy of the
                   converter's piece decoder, so it is not independent. The verify job FAILs only on unlisted missing.
  M1 per-piece wt  HAVE in part (total + by family). Patch B (approved) adds the verifier's family rule (>= 20 parts
                   off by > 20 %) on the families that hold only parts claimed exact. On the 7 test jobs it flags
                   nothing (ca1a958a's CV family is 32 tagged stand-ins, so it is left out).
"""


# ---- patch A: in classify_sds2_manifest(row, r, man, s2), after the invalid_parts_excluded block -------------------
def patch_a(row, cn):
    # converter v5.5.11+: identical placed solids, info only (decision 2026-10-02): converter-made repeats are written once
    # (a fix, not lost material; coverage already counts them through converter_duplicates_skipped) and SDS2's own
    # duplicate placements are kept as stored, like CIS/2 source duplicates
    n_src = cn('source_duplicate_placements')
    n_conv = cn('duplicate_placements') - n_src
    if n_conv > 0:
        row['issues_info'] = (row.get('issues_info') or []) + [f'converter_duplicates_removed:{int(n_conv)} (one SDS2 piece listed twice, written once)']
    if n_src > 0:
        row['issues_info'] = (row.get('issues_info') or []) + [f'source_duplicate_placements:{int(n_src)} (as stored in the source)']


# ---- patch B (approved 2026-10-02): same function, on the parts the converter claims exact ------------------------
import re as _re


def _family(name):                    # = manifest.family() of the converter
    n = (name or "").strip()
    if n.startswith("BPL"): return "BPL"
    if n.startswith("PIPE"): return "ROUND"
    if n.startswith("HSS"): return "ROUND" if n.lower().count("x") == 1 else "HSS"
    m = _re.match(r"[A-Z]+", n)
    return m.group() if m else "?"


def patch_b(row, man, num):
    """The verifier's M1 family rule: a family of >= 20 parts whose steel weight is outside 0.8-1.25x SDS2's.
    Exact parts only: families that hold any stand-in (approximate) part are left out - those rows are class 2 already
    and their stand-ins carry their own reasons. Class-1 candidates have no stand-ins, so every family is checked."""
    fam = ((man.get('weight_check') or man.get('weight') or {}).get('by_family') or {})   # sidecar / result-record manifest
    groups = (man.get('standins') or {}).get('groups') or man.get('standin_groups') or []
    approx_fams = {_family(g.get('real_type') or g.get('name') or '') for g in groups if isinstance(g, dict)}
    approx_fams |= {_family(str(p).split(' / ')[-1]) for g in groups if isinstance(g, dict) for p in (g.get('parts') or [])[:50]}
    off = {f: v for f, v in fam.items() if f not in approx_fams and isinstance(v, dict) and num(v.get('n')) >= 20
           and v.get('ratio') is not None and not 0.8 <= float(v['ratio']) <= 1.25}
    if off:
        row['issues'].append('family_weight_off:' + ','.join(f"{f}x{float(v['ratio']):.2f}" for f, v in sorted(off.items())[:6]))


# ---- patch C: class-1 gate from the verify job (adapter_sds2.py result joined as `ver`), before finish_class -------
def patch_c(row, ver):
    """ver = the adapter_sds2.py JSON for this row (or None when the row was not in the verify sample)."""
    if not ver:
        return
    row['verify'] = {k: ver.get(k) for k in ('verdict', 'evidence', 'tier', 'tier_confidence', 'class1_ok')}
    if ver.get('verdict') == 'ERROR':
        row['issues'].append('sds2_verify_error')
    elif not ver.get('class1_ok'):
        codes = sorted({f['code'] for f in ver.get('findings') or [] if f.get('level') in ('FAIL', 'WARN')
                        and f.get('cause') not in ('source', 'by_design')})
        row['issues'].append(f"sds2_verify:{ver.get('verdict')}:{'/'.join(codes) or 'tier_' + str(ver.get('tier'))}")
    # E1-E3 never demote by themselves; ver['tier_confidence'] records them
