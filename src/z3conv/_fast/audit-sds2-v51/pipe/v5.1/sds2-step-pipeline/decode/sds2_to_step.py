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
        manifest.write(dict(schema=manifest.SCHEMA, empty_job_proof=proof, converter="sds2-step-pipeline v5", job=os.path.basename(job.rstrip("/\\")),
                            version=read_version(job), stage=2, step=None, write_ok=False,
                            counts=dict(members=0, placed_pieces=0, pieces_written=0, solids_written=0, skipped=0),
                            standins=dict(total=0, by_type={}, groups=[]), readback=dict(checked=False),
                            **{"class": 3, "corpus": "C", "class_reasons": ["empty job: no member files in mem/ (seed or emptied job)"]}),
                       os.path.splitext(out)[0] + "_manifest.json")
        raise SystemExit("mem_idx: too few members to calibrate (0): empty job, no member files in mem/")
    if a.stage == 1:
        import to_step
        ok, _ = to_step.convert(job, out)
    else:
        import to_step2
        to_step2.USE_BREP = not a.approx
        to_step2.USE_HOLES = not a.no_holes
        to_step2.USE_BOLTS = not a.no_bolts
        ok, _ = to_step2.convert(job, out, shared=not a.flat)
    print(f"converted in {time.time() - t:.0f}s")
    if not ok:
        raise SystemExit("STEP write failed")

    if a.verify:
        import verify_step
        sys.argv = ["verify_step.py", out, os.path.splitext(out)[0] + "_preview.png"]
        res = verify_step.main()
        if a.stage == 2 and res and res.get("invalid"):
            # read-back repair: solids valid in memory but invalid once read back (1 in ~10,000; v4 jobs were rejected
            # for 1-22 of them). Pass 2 writes those instances as placed copies; pass 3 leaves out any still invalid.
            import to_step2
            for attempt in (1, 2):
                names = set(verify_step.invalid_labels(out))
                if not names:
                    break
                print(f"  read-back repair pass {attempt}: {len(names)} invalid solid(s): {sorted(names)[:5]}")
                if attempt == 1:
                    to_step2.FORCE_FLAT = names
                else:
                    to_step2.DROP_LABELS = names
                to_step2.reset()
                ok, _ = to_step2.convert(job, out, shared=not a.flat)
                sys.argv = ["verify_step.py", out, os.path.splitext(out)[0] + "_preview.png"]
                res = verify_step.main()
                if not res.get("invalid"):
                    break
        if a.stage == 2 and res:
            import manifest
            man = manifest.update_readback(os.path.splitext(out)[0] + "_manifest.json",
                                           {k: res.get(k) for k in ("top_level_shapes", "solids", "valid", "invalid",
                                                                    "invalid_names", "load_errors", "bbox_in")})
            if man:
                print(f"  manifest after read-back: class {man['class']} corpus {man['corpus']} "
                      f"({'; '.join(man['class_reasons'][:4])})")


if __name__ == "__main__":
    main()
