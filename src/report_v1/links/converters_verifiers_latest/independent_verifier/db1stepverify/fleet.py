"""Checks over EVERY published conversion that need no download: record vs published object, parts lost between
decoder and STEP, decoder coverage, orientation guard, rescue exclusions, input presence. Complements the sampled
deep verification (which can only look at a few dozen files end to end)."""
import collections, json, os
from . import config as C


def run(records, step_sizes, inputs=None):
    ok = {k: r for k, r in records.items() if r.get("status") == "ok"}
    F = collections.defaultdict(list)
    for k, r in sorted(ok.items()):
        c = r.get("convert") or {}; sk = c.get("skipped") or {}
        if k not in step_sizes: F["F_STEP_MISSING"].append(k)
        elif r.get("out_bytes") is not None and step_sizes[k] != r["out_bytes"]: F["W_RECORD_STALE"].append(k)
        sp = (r.get("step_stats") or {}).get("parts"); w = c.get("written")
        if sp is not None and w is not None and sp < w: F["W_PARTS_DROPPED"].append(k)
        if sp is not None and w is not None and sp > w: F["W_PARTS_EXTRA"].append(k)
        mb, mem = c.get("mb"), c.get("members")
        if mb and mb >= C.SPARSE_MIN_MB and mem is not None and mem / mb < C.SPARSE_MEMBERS_PER_MB: F["W_SPARSE_DECODE"].append(k)
        lost = sum(sk.get(x, 0) for x in ("unresolved", "contour_plate_no_outline", "implausible_profile", "writer_skip"))
        if (w or 0) + lost and lost / ((w or 0) + lost) > 0.2: F["W_DECODER_LOSS"].append(k)
        yv = c.get("y_vertical_frac_I")
        if yv is not None and (c.get("horizontal_I") or 0) >= 20 and yv < 0.8: F["W_ORIENTATION"].append(k)
        if r.get("excluded_elements"): F["W_RESCUE_EXCLUDED"].append(k)
        rb = r.get("readback") or {}
        if rb.get("read_status") == "ok" and sp and (rb.get("solids") or 0) < sp: F["W_READBACK_SHORT"].append(k)
        if r.get("code") != C.CURRENT_CODE: F["I_OLDER_CODE"].append(k)
        bb = (r.get("step_stats") or {}).get("bbox")
        if bb and max(bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]) > C.FAR_STRAY_MM:
            F["W_EXTENT_OVER_1KM"].append(k)          # whole-file extent > 1 km: almost always a stray / corrupted part
    # dataset hygiene: Tekla templates (not projects) and likely duplicate models (the same model saved in several
    # backup folders: same decoded member count, same written count, same extent to 0.1 m)
    for k, r in ok.items():
        key = r.get("key") or ""
        if "/environments/" in key or "model_template" in key.lower() or "template" in key.rsplit("/", 1)[-1].lower():
            F["I_TEMPLATE_MODEL"].append(k)
    sig = collections.defaultdict(list)
    for k, r in sorted(ok.items()):
        c = r.get("convert") or {}; bb = (r.get("step_stats") or {}).get("bbox")
        if bb and c.get("written"): sig[(c.get("members"), c["written"], tuple(round(x / 100) for x in bb))].append(k)
    groups = [v for v in sig.values() if len(v) > 1]
    for v in groups:
        for k in v[1:]: F["I_LIKELY_DUPLICATE"].append(k)     # the first (sorted) of each group is kept as the original
    orphans = sorted(set(step_sizes) - set(ok))
    if orphans: F["F_ORPHAN_STEP"] = orphans              # published STEP without an ok record
    if inputs:
        for k, v in inputs.items():
            if k in ok and not v.get("in_bucket"): F["W_INPUT_MISSING_EXTRACT"].append(k)
            if k in ok and v.get("in_bucket") and not v.get("bytes_ok", True): F["W_INPUT_SIZE"].append(k)
    dropped = sum(max(0, (ok[k].get("convert") or {}).get("written", 0) - (ok[k].get("step_stats") or {}).get("parts", 0)) for k in F["W_PARTS_DROPPED"])
    summary = dict(published=len(step_sizes), ok_records=len(ok), statuses=dict(collections.Counter(r.get("status") for r in records.values())),
                   engines=dict(collections.Counter(r.get("engine") for r in ok.values()).most_common()),
                   counts={k: len(v) for k, v in sorted(F.items())}, parts_dropped_total=dropped,
                   duplicate_groups=len(groups), duplicate_group_examples=[[ok[k]["key"] for k in v[:3]] for v in sorted(groups, key=len, reverse=True)[:5]],
                   any_warning=len({k for c, v in F.items() if c[0] in "FW" for k in v}))
    return summary, {k: v for k, v in F.items()}


def write(out_dir, summary, flags, suffix=""):
    json.dump(dict(summary=summary, flags=flags), open(os.path.join(out_dir, f"fleet{suffix}.json"), "w"), indent=1)
    L = [f"# Fleet checks: all {summary['published']} published db1 -> STEP files", "",
         f"ok records: {summary['ok_records']}; published files with any FAIL/WARN flag: {summary['any_warning']}", "",
         "| check | files | share |", "|---|---|---|"]
    for k, n in sorted(summary["counts"].items(), key=lambda x: ("FWI".index(x[0][0]), -x[1])):
        L.append(f"| {k} | {n} | {n / max(1, summary['published']):.1%} |")
    L += ["", f"parts lost between decoder and STEP (W_PARTS_DROPPED files): {summary['parts_dropped_total']}"]
    open(os.path.join(out_dir, f"fleet{suffix}.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
