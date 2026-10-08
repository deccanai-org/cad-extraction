"""SDS2 layout family from file sizes alone (what a .7z listing gives), no file contents needed.

mem_idx and subm_idx are a 256-byte header plus fixed-size slots; job_mtrl is 78 + n x 178 (7.0/7.1),
766 + n x 510 (7.2/7.3) or a variable-length archive (7.4+). The slot sizes identify the layout family.
Validated on 26 local jobs of known version (7.021 ... 7.613). usage (library): family(sizes, max_mem_id)
"""
MEM_SLOTS = {1280: "7.0xx", 1416: "7.1xx", 2494: "7.2xx", 2944: "7.3xx", 2976: "7.4xx", 3204: "7.5/7.6xx", 3404: "7.5/7.6xx"}
SUBM_SLOTS = {384: "7.0xx", 440: "7.1xx", 852: "7.2xx", 902: "7.3/7.4xx", 1024: "7.5/7.6xx"}


MEM_SLOTS_8 = {3600: "8.0xx"}                    # SDS2 2019+ (8.007): 7456-byte mem_idx header


def _slot(size, table, min_count=1, header=256):
    """Slot sizes from `table` with size == header + k * slot and k >= min_count."""
    if not size or size < header:
        return []
    return [s for s in table if (size - header) % s == 0 and (size - header) // s >= min_count]


def mtrl_kind(size):
    if not size: return None
    if (size - 78) % 178 == 0: return "178"
    if (size - 766) % 510 == 0: return "510"
    return "archive"


def family(job_mtrl, mem_idx, subm_idx, max_mem=0):
    """Returns (family, reason). family None when the job is incomplete or the layout is unrecognised."""
    if not job_mtrl: return None, "no main/job_mtrl"
    if not mem_idx: return None, "no mem/mem_idx"
    if not subm_idx: return None, "no subm/subm_idx"
    mk = mtrl_kind(job_mtrl)
    if mk == "archive" and _slot(mem_idx, MEM_SLOTS_8, max_mem + 1, header=7456) and _slot(subm_idx, {1024: ""}):
        return "8.0xx", "sizes"
    ms = _slot(mem_idx, MEM_SLOTS, max_mem + 1) or _slot(mem_idx, MEM_SLOTS)
    ss = _slot(subm_idx, SUBM_SLOTS)
    fam_m = {MEM_SLOTS[s] for s in ms}; fam_s = {SUBM_SLOTS[s] for s in ss}
    # consistency with job_mtrl: 178-B records -> 7.0/7.1, 510-B -> 7.2/7.3, archive -> 7.4+
    allowed = {"178": {"7.0xx", "7.1xx"}, "510": {"7.2xx", "7.3xx"}, "archive": {"7.4xx", "7.5/7.6xx"}}[mk]
    cand = [f for f in fam_m if f in allowed]
    if len(cand) > 1:                               # disambiguate with the piece table
        cand = [f for f in cand if any(f in fs or fs in f or f.split("x")[0] in fs for fs in fam_s)] or cand
    if len(cand) == 1: return cand[0], "sizes"
    return None, f"unrecognised (mem slots {ms}, subm slots {ss}, job_mtrl {mk})"
