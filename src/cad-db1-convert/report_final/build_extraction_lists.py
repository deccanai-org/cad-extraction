"""Extraction leftovers with exact locations, from the EC2 extraction pipeline's per-archive failure records
(raw/extraction_failures.jsonl, 1,113 archives it processed; the 2,507 archives of the earlier baseline pipeline
recorded only explicit errors, raw/ledger.jsonl.gz).

Writes ./out/:
  extraction_encrypted_nested_zips.csv       password-protected nested zips: where, how many files locked, which
  extraction_unopenable_nested_archives.csv  nested archives 7-Zip cannot open at all: exact path inside the archive
  extraction_damaged_nested_archives.csv     nested archives that are damaged (cut short, CRC/data or header errors):
                                             everything readable was extracted; the files that failed are listed
  leftovers_extraction.json                  counts
Paths are shown inside their source archive; a path inside a nested archive is written  outer.zip → inner/path."""
import csv, gzip, json, os, re, collections

HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, "out"); RAW = os.path.join(HERE, "raw")
R = [json.loads(l) for l in open(os.path.join(RAW, "extraction_failures.jsonl"))]
L = [json.loads(l) for l in gzip.open(os.path.join(RAW, "ledger.jsonl.gz"), "rt")]
SCRATCH = re.compile(r"^/scratch/[^/]+/shard-\d+/[0-9a-f]{64}/extracted/")


def inner(p):
    """path inside the source archive; nested levels joined with an arrow"""
    p = SCRATCH.sub("", p.strip())
    return re.sub(r"__nested/", " → ", p)


def classes(d):
    c = d["classification"]
    return set(c) if isinstance(c, list) else ({c} if c else set())


enc, uno, dmg = [], [], []
seen_u, seen_d = set(), set()
for r in R:
    src, disk = r["source_key"], r["disk"]
    for b in r["encrypted_blocked"]:
        enc.append(dict(source_archive=src, disk=disk, nested_zip=inner(b["archive"]), depth=b["context"],
                        locked_files=b["encrypted_member_count"], locked_files_sample="; ".join(b["encrypted_members_sample"][:10])))
    for d in r["extract_diagnostics"]:
        c = classes(d); tail = d["stderr_tail"] or ""
        lines = [x.strip() for x in tail.splitlines() if x.strip()]
        if "password_required" in c:
            continue                                  # listed per nested zip in the encrypted list
        paths = [inner(x[len("ERROR: "):]) for x in lines if x.startswith("ERROR: /")]
        msgs = [x for x in lines if not x.startswith("ERROR: /") and not x.startswith("/")]
        opened_msg = "; ".join(dict.fromkeys(m for m in msgs if m not in ("ERRORS:",)))[:300]
        if "unsupported_archive" in c or any("Cannot open the file as" in x or "Is not archive" in x for x in lines):
            for p in dict.fromkeys(paths) or [""]:
                k = (src, p)
                if k in seen_u: continue
                seen_u.add(k)
                uno.append(dict(source_archive=src, disk=disk, nested_archive=p or "(path not recorded)", depth=d["context"],
                                problem="7-Zip cannot open it as an archive (unsupported or damaged format)", seven_zip_message=opened_msg))
            continue
        failed = [x.split(" : ", 1)[1] for x in lines if x.startswith("ERROR:") and " : " in x]
        kind = ("cut short (unexpected end of archive)" if "truncated_archive" in c else "") + \
               ("; " if "truncated_archive" in c and ("data_error" in c or "headers_error" in c) else "") + \
               ("data / CRC error" if "data_error" in c else "") + (" header error" if "headers_error" in c else "")
        if not c or c == {"unclassified"}:
            kind = "extra data after the end of the archive (content before it extracted)"
        k = (src, d["context"], tuple(failed), kind)
        if k in seen_d: continue
        seen_d.add(k)
        dmg.append(dict(source_archive=src, disk=disk, depth=d["context"], problem=kind.strip() or "damaged",
                        files_not_extracted="; ".join(failed[:20]) or "(none named: the archive's end or header is damaged)",
                        seven_zip_message=opened_msg))


def w(name, rows):
    with open(os.path.join(OUT, name), "w", newline="") as fh:
        cw = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); cw.writeheader(); cw.writerows(rows)


enc.sort(key=lambda x: (x["source_archive"], x["nested_zip"])); uno.sort(key=lambda x: (x["source_archive"], x["nested_archive"]))
dmg.sort(key=lambda x: (x["source_archive"], x["problem"]))
w("extraction_encrypted_nested_zips.csv", enc); w("extraction_unopenable_nested_archives.csv", uno); w("extraction_damaged_nested_archives.csv", dmg)
rc2 = [dict(source_archive=r["source_key"], disk=r["disk"], rc2_events=r["rc2_fatal_accepted"], stored_files=r["stored_files"]) for r in R if r.get("rc2_fatal_accepted")]
w("extraction_7zip_fatal_partial.csv", rc2)
explicit = [x for x in L if x.get("explicit_events")]
summary = dict(extraction=dict(
    archives_total=3620, archives_scanned_ec2_era=len(R), archives_baseline_era=3620 - len(R),
    encrypted=dict(archives=len({x["source_archive"] for x in enc}), nested_zips=len(enc), member_files_locked=sum(x["locked_files"] for x in enc)),
    unopenable_nested_archives=dict(archives=len({x["source_archive"] for x in uno}), nested=len(uno)),
    damaged_nested_archives=dict(archives=len({x["source_archive"] for x in dmg}), entries=len(dmg),
                                 files_named_not_extracted=sum(0 if x["files_not_extracted"].startswith("(") else len(x["files_not_extracted"].split("; ")) for x in dmg)),
    sevenzip_fatal_accepted_partial=dict(archives=len(rc2), events=sum(x["rc2_events"] for x in rc2)),
    baseline_explicit_failure_events=len(explicit)))
json.dump(summary, open(os.path.join(OUT, "leftovers_extraction.json"), "w"), indent=1)
print(json.dumps(summary, indent=1))
