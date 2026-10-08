# Lessons (learned the hard way)

Sources: `docs/history/memory/feedback_*.md`, `docs/history/BUGS.md`, `docs/history/CONTEXT_live_log.md`.

## Extraction
- **Never let 7-Zip prompt**: pass `-p` (empty password). Password-protected *nested* zips stalled extraction 13 h.
  Test at the failing nesting level (`context` field), not the top-level archive.
- Write the dedup marker **after** the upload, or verify the target on a marker hit (data-4: 433 contents lost → worker o + repair).
- Non-UTF-8 member names (cp1252 key + raw hex in manifest); > 255-byte names via `7z e -so` fallback.
- Claim takeover must be by job liveness, and the takeover scan must sample randomly (else orphans stay orphaned).
- Files < 64 KB stored per archive (no global marker) — faster, explains stored > unique.

## Fleet
- One Python process is GIL-bound (~1.7 cores): run several processes per box (and fan big SDS/2 zips out).
- Under SSM, start background work with `setsid nohup … < /dev/null &`.
- Boot scripts that shut down on exit turn a `pkill` into an instance termination — use a restart loop + DONE marker.
- OOM reboots leave boxes idle (user-data runs at first boot only) — per-boot hook.
- Hot reload: restart idle workers on new code; versioned stop flag; `os.execv` does not replace a process on Windows.
- Reservations from measured p95 per size bucket; the watchdog kills the job furthest above its reservation.
- Botocore `standard` retries, not `adaptive` (adaptive crawled on S3 SlowDown).
- Don't add tiny boxes for big DB1 models (a 30 MB model starved on i4i.2xlarge).
- Check running jobs/heartbeats twice before terminating "idle" boxes.
- Mumbai capacity is shared with other teams: stay under the CAD cap.
- macOS deletes old `/tmp` files: keep scripts in the repo (`z3conv/tools/`).

## Control / safety
- Agents never write shared control files; read with `aws s3 cp s3://… -`, never `- s3://…` (a fixer emptied
  `pybin.txt` that way; restored from versioning).
- `--quiet` hid an AccessDenied: always check the result of a write.
- Redo entries need `codes`, canary results must count as "done", or re-runs loop forever.
- `splitlines()` splits on U+2028/U+0085 → JSONDecodeError on valid manifests; use `split('\n')`.

## Verification / reporting
- Verify against what the user sees (reproduce through his UI / the actual artifact before reporting a defect).
- Count each shortfall once per model, over the packaged model ids.
- NC1 headers may carry a `** file.nc1` comment line after ST that shifts every field.
- Manifests under-report gaps (5/5 partial samples); DB1/SDS2 "perfect" is circular without an independent truth layer.

## Dedup policy
- Never re-store content an earlier disk already stored; keep existing copies; ask before bulk deletes.
