"""SDS2 job folder (binary, no SDS2 install needed) -> STEP AP214.

usage: python sds2_to_step.py <job_dir> [-o out.step] [--stage 1|2] [--verify]

  <job_dir>  an SDS2 job folder (contains main/job_mtrl, mem/mem_idx, subm/subm_idx), or a folder holding exactly one
  --stage 1  one solid per structural member: AISC profile swept along the work line (fast, small file)
  --stage 2  (default) one solid per fabricated piece: main material at detailed cut length + connection plates,
             bent plates and angles; members without pieces (joists) are kept as stage-1 envelopes
  --verify   read the written STEP back with OCC: solid count, BRep validity, bounding box, preview PNG

Formats handled: 7.2xx (validated on 50_Binney 7.243 against its IFC), 7.3xx (members; Greenwood 7.312) and 7.4xx
(TRI NORTH 7.425: boost-archive job_mtrl, 902-byte subm_idx slots). Layouts are detected from the files, not the
version string. Writes <out>_members.csv / <out>_pieces.csv alongside the STEP.
"""
import os, sys, time, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def find_job(path):
    """The job folder itself, or the single job folder directly inside `path`."""
    is_job = lambda d: all(os.path.exists(os.path.join(d, *p)) for p in (("main", "job_mtrl"), ("mem", "mem_idx")))
    if is_job(path):
        return path
    subs = [os.path.join(path, d) for d in os.listdir(path) if os.path.isdir(os.path.join(path, d))]
    jobs = [d for d in subs if is_job(d)]
    if len(jobs) == 1:
        return jobs[0]
    raise SystemExit(f"{path}: not an SDS2 job folder (need main/job_mtrl and mem/mem_idx)"
                     + (f"; found several jobs: {jobs}" if jobs else ""))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("job")
    ap.add_argument("-o", "--out")
    ap.add_argument("--stage", type=int, choices=(1, 2), default=2)
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--approx", action="store_true", help="stage 2: approximate piece builders instead of exact B-rep solids")
    ap.add_argument("--no-holes", action="store_true", help="stage 2: don't cut bolt holes")
    ap.add_argument("--no-bolts", action="store_true", help="stage 2: don't add nominal bolts through hole stacks")
    ap.add_argument("--nc1", metavar="DIR_OR_ZIP",
                    help="stage 2 opt-in: cut the job's own NC1 / DSTV holes that SDS2's piece files lack into main "
                         "W-shape pieces (strict match only; tagged holes_from_nc1)")
    ap.add_argument("--flat", action="store_true",
                    help="stage 2: write every piece instance as its own solid instead of shared parts in an assembly")
    a = ap.parse_args()

    job = os.path.abspath(a.job)
    if os.name == "nt" and len(job) > 200 and not job.startswith("\\\\?\\"):
        job = "\\\\?\\" + job                      # deeply nested job folders exceed Windows MAX_PATH
    job = find_job(job)
    from sds2job import read_version
    name = os.path.basename(job.rstrip("\\/")).replace(" ", "_")
    out = os.path.abspath(a.out or f"{name}_stage{a.stage}.step")
    print(f"job {job}\nSDS2 version {read_version(job) or 'unknown'} -> {out} (stage {a.stage})")

    t = time.time()
    md = os.path.join(job, "mem")
    if a.stage == 2 and not any(n.isdigit() for n in os.listdir(md)):
        # empty / seed job (mem_idx without a single member file): record it, then fail as before so batch
        # bookkeeping (reason no_members_to_calibrate) is unchanged
        import manifest
        mi = os.path.join(md, "mem_idx")
        with open(mi, "rb") as f_:
            head = f_.read(8 << 20)
        proof = dict(member_files=0, mem_idx_bytes=os.path.getsize(mi), mem_idx_nonzero_bytes_first_8MB=sum(1 for x in head if x),
                     subm_files=sum(n.isdigit() for n in os.listdir(os.path.join(job, "subm"))) if os.path.isdir(os.path.join(job, "subm")) else 0)
        reasons = ["empty job: no member files in mem/ (seed or emptied job)"]
        if proof["subm_files"]:
            # v5.5.5: piece files without any member file (seed / library / emptied jobs, imports whose member file
            # is gone): every placement lives in a member file, so nothing can be placed. Prove the pieces are in
            # piece-local coordinates and record what the index still holds; never place them anywhere.
            up = unplaced_pieces_proof(job)
            proof["unplaced_pieces_proof"] = up
            reasons = [f"pieces without placements: {proof['subm_files']} piece file(s) but no member file; SDS2 stores every "
                       f"placement in member files, so none is stored (seed / library / emptied job). The pieces hold "
                       f"piece-local geometry ({up['pieces_checked']} checked: median centre {up['median_centre_from_origin_in']} in "
                       f"from the origin, median size {up['median_piece_extent_in']} in)"]
        manifest.write(dict(schema=manifest.SCHEMA, empty_job_proof=proof, converter="sds2-step-pipeline v5", job=os.path.basename(job.rstrip("/\\")),
                            version=read_version(job), stage=2, step=None, write_ok=False,
                            counts=dict(members=0, placed_pieces=0, pieces_written=0, solids_written=0, skipped=0),
                            standins=dict(total=0, by_type={}, groups=[]), readback=dict(checked=False),
                            **{"class": 3, "corpus": "C", "class_reasons": reasons}),
                       os.path.splitext(out)[0] + "_manifest.json")
        raise SystemExit("mem_idx: too few members to calibrate (0): empty job, no member files in mem/")
    opts = dict(approx=a.approx, no_holes=a.no_holes, no_bolts=a.no_bolts, flat=a.flat,
                nc1=os.path.abspath(a.nc1) if a.nc1 else None)
    ok = _in_child(_convert_job, a.stage, job, out, opts, None, None)
    print(f"converted in {time.time() - t:.0f}s")
    if not ok:
        raise SystemExit("STEP write failed")

    if a.verify:
        png = os.path.splitext(out)[0] + "_preview.png"
        # v5.5.7: the read-back and its repair passes share one time budget (SDS2_VERIFY_BUDGET_S, default 7200 s;
        # 0 = none). Past it the written STEP is kept and the manifest records a partial read-back, so the job is
        # published as converted instead of timing out after the STEP was already written (fleet: 260 timeouts).
        budget = float(os.environ.get("SDS2_VERIFY_BUDGET_S", "7200")) or None
        max_pass = int(os.environ.get("SDS2_REPAIR_MAX_PASSES", "2"))
        t_conv = time.time() - t
        tv0 = time.time(); partial = None
        left = lambda: None if budget is None else budget - (time.time() - tv0)
        try:
            res = _in_child(_verify, out, png, timeout=left())
        except _Budget as e:
            res, partial = None, str(e)
        t_ver = time.time() - tv0
        if a.stage == 2 and res and res.get("invalid"):
            # read-back repair: solids valid in memory but invalid once read back (1 in ~10,000; v4 jobs were rejected
            # for 1-22 of them). Pass 2 writes those instances as placed copies; pass 3 leaves out any still invalid.
            force, drop = None, None
            for attempt in range(1, max_pass + 1):
                if budget is not None and t_conv + 2 * t_ver > left():
                    if t_conv + t_ver <= left():
                        # a full pass (label scan + rebuild + re-check) does not fit, a rebuild does: leave every
                        # still-invalid part out in one final pass (reported as skipped), without the re-check
                        try:
                            names = {n.strip() for n in (_in_child(_invalid_labels, out, timeout=left()) or [])}
                        except _Budget as e:
                            partial = str(e); break
                        if names:
                            _in_child(_convert_job, a.stage, job, out, opts, force, names)
                            partial = (f"read-back repair: {len(names)} invalid part(s) left out in a final pass that the "
                                       f"time budget did not allow to re-check")
                            res = None
                        print("  " + (partial or "read-back repair: nothing left to fix"))
                        break
                    partial = (f"read-back repair pass {attempt} not run: about {t_conv + 2 * t_ver:.0f} s needed, "
                               f"{left():.0f} s of the budget left; {res.get('invalid')} invalid part(s) stay")
                    print("  " + partial)
                    break
                try:
                    names = _in_child(_invalid_labels, out, timeout=left()) or []
                except _Budget as e:
                    partial = str(e); break
                names = {n.strip() for n in names}       # labels of members without a type start with " #": compare stripped
                if not names:
                    break
                print(f"  read-back repair pass {attempt}: {len(names)} invalid solid(s): {sorted(names)[:5]}")
                if attempt == 1:
                    force = names
                else:
                    drop = names
                _in_child(_convert_job, a.stage, job, out, opts, force, drop)
                try:
                    res2 = _in_child(_verify, out, png, timeout=left())
                except _Budget as e:
                    partial = str(e) + " (repair pass written, not re-checked)"; res = None; break
                res = res2
                if not res or not res.get("invalid"):
                    break
        if a.stage == 2 and partial and not res:
            import manifest
            man = manifest.update_readback(os.path.splitext(out)[0] + "_manifest.json",
                                           dict(partial=True, note=partial), checked=False)
            if man:
                print(f"  read-back partial ({partial}); manifest: class {man['class']} corpus {man['corpus']}")
        if a.stage == 2 and res:
            import manifest
            rbd = {k: res.get(k) for k in ("top_level_shapes", "solids", "surfaces", "valid", "invalid",
                                            "invalid_names", "load_errors", "bbox_in")}
            if partial:
                rbd.update(partial=True, note=partial)
            man = manifest.update_readback(os.path.splitext(out)[0] + "_manifest.json", rbd)
            if man:
                print(f"  manifest after read-back: class {man['class']} corpus {man['corpus']} "
                      f"({'; '.join(man['class_reasons'][:4])})")


# v5.4.1: every heavy phase (conversion, read-back verify, repair-label scan) runs in its own forked child process, so
# the memory of one phase is returned to the OS before the next starts. In v5.4 the read-back ran in the converter
# process while its whole XCAF document, STEP writer model and part caches were still alive (peak = sum of phases).
class _Budget(Exception):
    """A child phase ran past its time budget and was stopped."""


def _in_child(fn, *args, timeout=None):
    import multiprocessing as mp
    if os.name == "nt" or os.environ.get("SDS2_NO_FORK") == "1":
        return fn(*args)
    ctx = mp.get_context("fork")
    rd, wr = ctx.Pipe(duplex=False)

    def run():
        try:
            r = fn(*args)
            wr.send(("ok", r))
        except SystemExit as e:
            wr.send(("exit", str(e)))
        except BaseException as e:
            import traceback; traceback.print_exc()
            wr.send(("err", f"{type(e).__name__}: {e}"))
        finally:
            sys.stdout.flush(); sys.stderr.flush()
            os._exit(0)
    sys.stdout.flush(); sys.stderr.flush()
    pr = ctx.Process(target=run)
    pr.start(); wr.close()
    if timeout is not None and not rd.poll(max(timeout, 1.0)):
        pr.terminate(); pr.join(10)
        if pr.is_alive():
            pr.kill(); pr.join()
        raise _Budget(f"{fn.__name__} stopped after {timeout:.0f} s (SDS2_VERIFY_BUDGET_S)")
    try:
        kind, val = rd.recv()
    except EOFError:
        pr.join()
        raise SystemExit(f"{fn.__name__} child process died (exit code {pr.exitcode})")
    pr.join()
    if kind == "ok":
        return val
    if kind == "exit":
        raise SystemExit(val)
    raise RuntimeError(val)


def unplaced_pieces_proof(job, limit=400):
    """Evidence that a job's piece files cannot be placed: their B-rep centres sit in piece-local coordinates (near
    the origin, not spread over a building), what the member index still holds, and what the pieces are."""
    import re, collections
    import numpy as np
    import brep
    md, sd = os.path.join(job, "mem"), os.path.join(job, "subm")
    nz, typed = 0, collections.Counter()
    with open(os.path.join(md, "mem_idx"), "rb") as f:
        while True:
            b = f.read(8 << 20)
            if not b:
                break
            nz += int(np.count_nonzero(np.frombuffer(b, np.uint8)))
            for m in re.finditer(rb"(?<![ -~])(BEAM|COLUMN|VERTICAL BRACE|HORIZONTAL BRACE|MISC|JOIST|AnchorRod|"
                                 rb"DWF Import|IFC Import|ReferenceModel)\x00", b):
                typed[m.group(1).decode()] += 1
    ids = sorted(int(n) for n in os.listdir(sd) if n.isdigit())
    step = max(1, len(ids) // limit)
    C, E, n = [], [], 0
    for sid in ids[::step]:
        try:
            with open(os.path.join(sd, str(sid)), "rb") as f:
                r = brep.parse(f.read())
        except OSError:
            continue
        if r is None:
            continue
        V, F = r; used = sorted({i for fc in F for i in fc})
        if not used:
            continue
        n += 1; C.append(V[used].mean(0)); E.append(float(np.ptp(V[used], 0).max()))
    out = dict(mem_idx_nonzero_bytes=nz, mem_idx_typed_records=dict(typed), pieces_checked=n)
    if C:
        C = np.array(C)
        Ea = np.maximum(np.array(E), 1.0)
        out.update(max_centre_from_origin_in=round(float(np.linalg.norm(C, axis=1).max()), 1),
                   median_piece_extent_in=round(float(np.median(E)), 1),
                   median_centre_from_origin_in=round(float(np.median(np.linalg.norm(C, axis=1))), 1),
                   median_centre_over_own_extent=round(float(np.median(np.linalg.norm(C, axis=1) / Ea)), 2))
    else:
        out.update(max_centre_from_origin_in=None, median_piece_extent_in=None, median_centre_from_origin_in=None,
                   median_centre_over_own_extent=None)
    try:
        from piece_table import read_pieces
        P = read_pieces(job)
        out["piece_table"] = dict(pieces=len(P), names=collections.Counter(p["name"] for p in P.values()).most_common(6))
    except Exception as e:
        out["piece_table"] = dict(error=type(e).__name__)
    if typed:
        out["note"] = ("mem_idx still holds typed records but their member files are absent (stale index entries); "
                       "no placement or material is stored for them")
    return out


def _convert_job(stage, job, out, opts, force, drop):
    if stage == 1:
        import to_step
        ok, _ = to_step.convert(job, out)
        return ok
    import to_step2
    to_step2.USE_BREP = not opts["approx"]
    to_step2.USE_HOLES = not opts["no_holes"]
    to_step2.USE_BOLTS = not opts["no_bolts"]
    to_step2.NC1_SRC = opts.get("nc1")
    if force:
        to_step2.FORCE_FLAT = set(force)
    if drop:
        to_step2.DROP_LABELS = set(drop)
    ok, _ = to_step2.convert(job, out, shared=not opts["flat"])
    return ok


def _verify(out, png):
    import verify_step
    sys.argv = ["verify_step.py", out, png]
    return verify_step.main()


def _invalid_labels(out):
    import verify_step
    return verify_step.invalid_labels(out)


if __name__ == "__main__":
    main()
