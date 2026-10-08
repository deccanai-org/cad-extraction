"""Cross-check decoded bolt holes per piece against the job's NC1 / DSTV files (FIX item 8).

Each NC1 file is one fabricated part: header (piece mark, profile, length in mm) and BO blocks (one line per hole).
Pieces are matched on profile name + length (within 2 mm) against the job's piece table; the hole count of every
matching piece file (brep.holes) is compared with the NC1 hole count. Only unambiguous matches (all candidate pieces
decode the same hole count) are scored.
usage: python nc1_holes.py <job_dir> <folder with .nc1 files> [-o out.json]
"""
import os, sys, re, json, glob, argparse, collections

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "decode"))


def read_nc1(path):
    L = open(path, errors="replace").read().splitlines()
    hdr = []; i = 1
    while i < len(L) and not re.match(r"^[A-Z]{2}\s*$", L[i]):
        hdr.append(L[i].strip()); i += 1
    holes = 0; marks = 0; cur = None
    for line in L[i:]:
        if re.match(r"^[A-Z]{2}\s*$", line):
            cur = line.strip(); continue
        if cur == "BO" and line.strip():
            tok = line.split()
            try:
                dia = float(tok[3])
            except (IndexError, ValueError):
                dia = 0.0
            if dia > 0:
                holes += 1                 # BO lines with a 0 diameter are punch / scribe marks, not holes
            else:
                marks += 1
    try:
        length = float(hdr[8])
    except (IndexError, ValueError):
        length = None
    return dict(mark=hdr[3] if len(hdr) > 3 else "", profile=(hdr[6] if len(hdr) > 6 else "").replace("X", "x"),
                qty=hdr[5] if len(hdr) > 5 else "", length_mm=length, holes=holes, marks=marks)


def norm(s):
    return re.sub(r"\s+", "", s or "").lower().replace("x", "x")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("job"); ap.add_argument("nc1dir"); ap.add_argument("-o", "--out")
    ap.add_argument("--manifest", help="v5.4 manifest: add the bolt-derived holes per piece (holes.derived.by_piece)")
    ap.add_argument("--pieces-csv", help="<out>_pieces.csv: only pieces actually placed in the model are candidates")
    a = ap.parse_args()
    placed = None
    if a.pieces_csv:
        import csv
        placed = {int(r["piece"]) for r in csv.DictReader(open(a.pieces_csv)) if r.get("piece") not in (None, "", "0")}
    derived = {}
    if a.manifest:
        derived = {int(k): v for k, v in json.load(open(a.manifest))["holes"].get("derived", {}).get("by_piece", {}).items()}
    from piece_table import read_pieces
    import brep
    P = read_pieces(a.job)
    by = collections.defaultdict(list)
    for sid, p in P.items():
        by[norm(p["name"])].append(sid)
    holes_cache = {}

    def nh(sid):
        if sid not in holes_cache:
            try:
                holes_cache[sid] = len(brep.holes(open(os.path.join(a.job, "subm", str(sid)), "rb").read())) + derived.get(sid, 0)
            except OSError:
                holes_cache[sid] = None
        return holes_cache[sid]
    res = []
    for f in sorted(glob.glob(os.path.join(a.nc1dir, "**", "*.nc1"), recursive=True)):
        n = read_nc1(f)
        cands = [s for s in by.get(norm(n["profile"]), []) if n["length_mm"] and abs(P[s]["L"] * 25.4 - n["length_mm"]) <= 2.0
                 and (placed is None or s in placed)]
        counts = {nh(s) for s in cands}
        res.append(dict(file=os.path.basename(f), mark=n["mark"], profile=n["profile"], length_mm=n["length_mm"],
                        nc1_holes=n["holes"], candidates=len(cands),
                        decoded_holes=(counts.pop() if len(counts) == 1 else None) if cands else None))
    scored = [r for r in res if r["decoded_holes"] is not None]
    exact = sum(r["decoded_holes"] == r["nc1_holes"] for r in scored)
    for r in scored:
        r["matched"] = min(r["decoded_holes"], r["nc1_holes"])
        r["missing"] = max(r["nc1_holes"] - r["decoded_holes"], 0)
        r["extra"] = max(r["decoded_holes"] - r["nc1_holes"], 0)
    out = dict(nc1_files=len(res), matched_unambiguous=len(scored), hole_count_equal=exact,
               holes_matched=sum(r["matched"] for r in scored), holes_missing=sum(r["missing"] for r in scored),
               holes_extra=sum(r["extra"] for r in scored),
               nc1_holes_total=sum(r["nc1_holes"] for r in scored), decoded_holes_total=sum(r["decoded_holes"] for r in scored),
               mismatches=[r for r in scored if r["decoded_holes"] != r["nc1_holes"]][:30])
    s = json.dumps(out, indent=1)
    if a.out:
        open(a.out, "w").write(json.dumps(dict(summary=out, rows=res), indent=1))
    print(s)


if __name__ == "__main__":
    main()
