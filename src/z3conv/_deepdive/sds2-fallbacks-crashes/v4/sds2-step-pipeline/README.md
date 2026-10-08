# SDS2 → STEP

Converts an SDS2 job folder (the binary `main/`, `mem/`, `subm/` files — SDS2 itself is not needed) to STEP AP214.

```
python decode/sds2_to_step.py "<job folder>" -o out/Job_stage2.step --stage 2 --verify
```

- `--stage 1` — one solid per structural member (AISC profile along the work line). Fast, small.
- `--stage 2` (default) — one solid per fabricated piece: main material at detailed cut length, connection plates,
  bent plates, angles, weld studs, bolts, anchor rods and concrete footings/grade beams. Members with no pieces
  (joists) are kept as stage-1 envelopes.
- `--verify` — reads the STEP back, checks solid count / BRep validity, writes `<out>_preview.png`.
- `--approx` — stage 2 without the exact piece B-rep (the older prism builders only); `--no-holes` — don't cut bolt holes.
- `--flat` — write every piece instance as its own solid. By default stage 2 writes each unique exact piece (and each
  bolt size) once and places it per instance as a STEP assembly component (Kincora: 360 MB -> 24 MB; identical
  solids, volumes and bbox on read-back). Before writing, every unique part goes once through a temporary STEP
  assembly at its first real placement; parts that read back invalid that way (SCHUCKERS: 6 of 288, C12x20.7 and
  PIPE 1 1/2 STD, although valid as placed copies) are written as placed copies instead (`parts_written_flat`).

Stage 2 builds each piece from SDS2's own boundary representation in `subm/<id>` (exact faceted solid: copes,
clips, bevels, bent plates, fillets as SDS2 draws them) and cuts its bolt holes and slots; the approximate
builders are only a fallback (no piece file, unparseable, or volume outside 0.6-1.6x of SDS2's weight). The run
prints `steel pieces: solids X t vs SDS2 piece weights Y t` so every conversion reconciles itself.

Requires Python 3.12: `pip install -r requirements.txt`.

## Running at scale (`batch/run_batch.py`)

One entry point for every supported version (7.0xx-8.0xx; layouts are detected per job). Jobs run in parallel,
each conversion in its own process with a timeout; results are appended to `results.jsonl` so an interrupted run
resumes where it stopped.

```
python batch/run_batch.py --s3 --plan                                  # what would run (no S3 access)
python batch/run_batch.py --s3 --out D:/step_out --work D:/step_work    # all of Disk-2 (inventory/disk2_models.csv)
python batch/run_batch.py --s3 --versions "7.0,7.1" --limit 20 --out D:/step_out
python batch/run_batch.py --local D:/sds2_jobs --out D:/step_out --stage both
```

- Sources: `--s3` reads archives from `s3://bim-proprietary-data/Disk-2/` (default boto3 credentials) and extracts
  only each job's `main/ mem/ subm/` (zips over 1 GB via ranged reads, 7z via py7zr); `--local ROOT` takes job
  folders and `.zip` / `.7z` archives under ROOT.
- Parallelism: `--convert-jobs N` conversions at once (default cores-1, capped at free RAM / 3 GB; the largest jobs
  need ~3-4 GB while verifying), `--downloads N` concurrent downloads, `--workers N` archives in flight. A
  conversion only starts while `--min-free-gb` RAM and `--min-disk-gb` disk are free.
- Output: `OUT/<version>/<job>_<hash>/<job>_stage2.step` (+ pieces csv, preview png, log), `OUT/results.jsonl`,
  `OUT/summary.csv` (per job: status, version, exact / plate / rolled / fastener / bolt counts, holes, steel ratio,
  solids valid, seconds, STEP MB, error) and `OUT/summary.md` (per version).
- .7z archives: the 7-Zip CLI (`7zz` / `7z` / `7za`, installed by `ec2_setup.sh`) is used when present - it reads
  every codec (py7zr can't decode BCJ2, 7-Zip's default filter for archives holding executables) and is faster;
  py7zr is the fallback, and a py7zr failure is retried with the CLI. A 7z larger than `--stream-gb` is
  downloaded for the CLI only if the scratch disk keeps 20 GB free afterwards, else py7zr streams it from S3.
  Tested locally: BCJ2 archive (fails with py7zr alone), bracket/space folder names, streamed-archive fallback.
  `--no-7z-cli` forces py7zr.
- Stage 2 failures fall back to stage 1 (status `ok_stage1`) unless `--no-fallback`; `--retry-failed` redoes
  failures; `--flat`, `--no-holes`, `--no-bolts`, `--no-verify` pass through to the converter.
- Filters: `--versions` (prefixes, quoted list in PowerShell), `--match REGEX`, `--include-junk`, `--min-members`,
  `--limit`, `--items items.json` ([version, archive, job_root] rows).
- Tested locally: 7 jobs (7.0-8.0, one from a nested .zip) in 1.6 min with 5 conversions at once, all solids valid;
  partial extractions fall back cleanly; a resumed run skips finished jobs.

Accuracy verdict per job (`qa` / `qa_reasons` in `summary.csv`, counts and reasons in `summary.md`), from the
converter's own checks, so thousands of outputs can be trusted or triaged without opening them:
- **fail**: conversion error (grouped by cause: archive unreadable, no job folder, unsupported layout, timeout,
  out of memory, S3 access, ...), more than max(5, 0.1%) invalid solids, or steel weight outside 0.75-1.3 x SDS2;
- **warn**: stage-1 fallback, any invalid solid, steel weight outside 0.9-1.1 x SDS2, > 1% of pieces not built,
  < 90% of plates / rolled pieces with exact geometry, no SDS2 piece weights, or no fabricated pieces;
- **pass**: none of the above.
Working through a mass run: fix the most frequent failure / warning classes first (each row names an example
archive), then `--retry-failed` redoes only failures; re-grading (`summary.*`) uses the current rules every time.

`inventory/regen_exact.py <root> [out] [regex|-] [N]` re-converts the local test jobs, N in parallel.

### On EC2

1. Instance: Ubuntu 24.04, in the same region as `bim-proprietary-data` (no transfer charges; add an S3 gateway
   endpoint to the VPC). Memory sets the parallelism (a conversion peaks at ~3-4 GB while verifying): e.g.
   m6i.8xlarge (32 vCPU / 128 GB, ~30 conversions) or r6i.4xlarge (16 vCPU / 128 GB, ~15). Attach a gp3 volume
   of ~300 GB at `/data` (downloads of up to `--downloads` 7z archives <= `--stream-gb` each, extracted jobs, and
   outputs until they are uploaded; larger zips and 7z are read from S3 in place).
2. IAM instance role: `s3:GetObject` on `bim-proprietary-data/Disk-2/*` (+ `s3:ListBucket`), and
   `s3:PutObject` / `s3:GetObject` on the output prefix.
3. Copy this folder (incl. `inventory/disk2_models.csv` and `inventory/disk2_archives.jsonl`), then
   `bash batch/ec2_setup.sh`.
4. `bash batch/ec2_run.sh s3://YOUR-BUCKET/sds2-step --limit 20` as a smoke test, then without `--limit`.
   Outputs go to `s3://YOUR-BUCKET/sds2-step/<version>/<job>/`, with `results.jsonl`, `summary.csv`,
   `summary.md` beside them. Spot instances are fine: a new instance running the same command resumes from the
   uploaded `results.jsonl` (jobs in flight at the interruption are redone).

Rough scale (from the local test jobs, not measured on EC2): 2,651 jobs x ~2-4 min of single-core conversion
+ verification each = ~90-180 core-hours, i.e. ~3-6 h on 30 parallel conversions plus the 2.1 TB transfer
(overlapped); ~180 MB of STEP per job on average (~0.5 TB in total). `--no-verify` saves ~30% of the time.

Linux notes: archive member names are normalized on extraction (`\` separators, upper-case `MAIN/`, `Mem_Idx`
...), so the case-sensitive file system sees the layout the decoder expects; the `\\?\` long-path handling only
applies on Windows. Production modules: `decode/{sds2_to_step,sds2job,piece_table,instances,to_step,to_step2,brep,bolts,
verify_step,preflight}.py`; the other files in `decode/` are format-exploration tools.

## Format support

| SDS2 | status |
|---|---|
| 7.0xx | members + pieces; SUNY (7.021) and RCMS (7.039, two copies) converted; same family as 7.1xx |
| 7.1xx | members + pieces; 7.122 (Marion County, Long Branch), 7.132/7.135 (7 jobs) converted; members validated 100% against a converted twin |
| 7.2xx | members + pieces; validated on 50_Binney (7.243) against its IFC; 7.245/7.258 converted |
| 7.3xx | members + pieces; 7.312/7.331 jobs converted (Disk-2 samples) |
| 7.4xx | members + pieces; TRI NORTH (7.425), 7.433 converted ("2015.xx" folders are 7.4xx inside) |
| 7.5xx / 7.6xx | members + pieces; 9 jobs (7.516/7.605/7.613) pass preflight at stage 2, 4 converted end to end |
| 7.3xx (7.310) | NASA Tower converted (1.023 of SDS2's weight) |
| 7.7xx / 8.0xx (SDS2 2018+) | same layout; 7.708 (Center Grove Natatorium) and 8.007 (SampleJob, Morgan State, 350 Summer Street 2021) converted |

`decode/preflight.py <job>` scores any job (stage2 / stage1 / no) against its own data without writing a STEP.

7.1xx layout (all big-endian; set `sds2job.ALLOW_71 = False` to refuse these jobs):
- `job_mtrl`: 178-B records, f32 dims at +0x1A, numbered from the first named record (two blank header records).
- `mem_idx`: 1416-B slots; type at +4, end points 3 x f32 at +266 / +316, section i16 at +366, roll f32 (rad) at +370.
- `subm_idx`: 440-B slots; name +0x11A, section i16 +0x10A, f32 weight +0x130, L +0x146, W +0x14A, T +0x14E.
- `mem/<n>`: 512-B placement blocks, rotation 9 x f64 at B+0x0C, origin 3 x f64 at B+0x54, piece id u16 at B+0x6C.
- `subm/<id>`: u32 vertex count at 0x0E, then packed 3 x f64 vertices from 0x1E.

Validation: Merriam (7.135) against its 7.3-layout copy: 699/699 member end points, 341/341 sections, 699/699 rolls,
1,166/1,166 placements identical; on 7 jobs sections match their own main-piece names 88-100%, total steel
0.99-1.06 of SDS2's piece weights, 75-97% of unique pieces within 10%.

7.425 differences handled: `job_mtrl` is a little-endian boost archive with variable-length records;
`subm_idx` slots are 902 bytes; piece vertex tag bytes vary (1 rolled, 2 plate, 3 round HSS, 11 bent plate).

TRI NORTH checks (no IFC in the job, so validated against the job's own data): all 135 section indices used by
pieces match the decoded section table; member cross-section areas are 98–99% of AISC (fillets not modelled);
every structural member gets solids; total stage-2 steel 589.5 t vs 586.4 t from SDS2's own piece weights (+0.5%);
92.5% of the 2,626 unique pieces within 10% of their recorded weight (W 99%, C 98%, HSS 95%, L 93%, bent plate
~89%, flat plate ~85%).

Fixes made for 7.425 that also apply to older jobs: hollow sections (HSS/pipe) were built as solid bars; vertex
records with high-byte ids were skipped and trailing hole/dimension records were read as vertices; bent plates
were convex-hull blocks; members without pieces (joists) were dropped from stage 2. Re-run 7.2/7.3 jobs to pick
these up (not re-validated here — those jobs aren't on this machine).

Pieces with no vertex outline are built from their mesh (tag-0 records) or piece-table size: weld studs, threaded
studs, bolts and anchor rods as stacked cylinders (shaft + head/nut; TRI NORTH: studs and rods 100%, bolts 83%
within 10% of weight, hex heads/nuts modelled round); concrete as its L x W x T prism at the bottom of its mesh
(volume matches the cubic yards in its name); mesh-only round HSS and bent plates go through the normal builders.

7.0xx: the 7.1xx family with smaller records. `mem_idx` 1280-B slots, type at +68, f32 end points at +266/+316,
section i16 +366, roll f32 +370 (no key match: the member file's reference point is at +0x50, so calibration falls
back to these offsets); `subm_idx` 384-B slots, the 7.1 record with L/W/T at +0x142/+0x146/+0x14A; piece files have
the 7.1 vertex list with the header 8 bytes shorter (count u32 at 0x06, vertices from 0x16); small member files put
the main placement block 4 bytes before the file start (rotation at 0x08, origin 0x50, piece u16 at 0x68).
Validated: sections equal the member's longest rolled piece 99.7% (SUNY) / 92.1% (RCMS); column rolls match the
7-8 / 37-38 degree grid; total steel 1.005-1.030 of SDS2's weights, 95-98% of unique pieces within 10%.
Some Disk-2 archives listed with an unknown version are 7.039 copies (e.g. `023_Stone City/RCMS_JOB.7z`).

8.0xx (SDS2 2019+, jsetup "version 8.007"): same file set as 7.613. `mem_idx` has a 7456-byte header and 3600-B
slots (end points f64 +274/+390, section +508, roll +514 as in 7.4+); `subm_idx` keeps 1024-B slots but the record is
rearranged: name +0x3C0 (metric +0x3D7), section i32 +0x114, net weight f64 +0x134, L/W/T +0x15C/+0x164/+0x16C
(`piece_table.LAYOUTS["8.0"]`). SampleJob (the SDS2 sample building, = 7.613 Building_101j) converts to the same
613 solids and bounding box as its 7.613 copy.

Section table (7.4+): joist records embed their chord angles as nested strings with the same length prefix; they are
now skipped (the byte after the name is 0x17 or 0 instead of a type code). Counting them shifted every section index
after the first joist: 8.007 Morgan State 89% -> 100% of pieces' sections resolved, 7.613 Valley Health 94-97% ->
100%. Re-run 7.5+/8.0 conversions made before this fix.

Damaged jobs are reported, not converted: e.g. `Completed_Jobs_Data/OTHERS/16-18_ARUNDEL_ES_JOB.7z`, whose `mem_idx`
holds a bill-of-material report and whose `jsetup` is binary.

7.5xx / 7.6xx (SDS2 2016/2017): members and placement blocks as in 7.4xx; `subm_idx` is the 7.2 record shifted by
4 bytes in 1024-B slots (name +0x132, section i32 +0x114, net weight f64 +0x148, L/W/T +0x170/+0x178/+0x180; +0x3F6
holds the nominal L x W x T weight). On 9 jobs: section index 100% of 23,407 rolled pieces, T 99.9% of plates.

Piece fallbacks added on 7.5/7.6 jobs (all layouts): rolled pieces whose file holds no geometry are built as the
nominal section over their length; main material stored as a flat 2D outline uses the member's stage-1 solid;
bent plates whose start face lists only part of the outline use a concave hull of both end faces; rolled pieces
with marker points far beyond their length are trimmed when both end faces are intact (HENRY FORD: 1.128 -> 1.039
of SDS2's weight; TRI NORTH unchanged at 1.006).

Member section field: calibration now picks the offset whose section equals each member's own main-piece name
(mem/<n>+0xE8 -> subm_idx) wherever the piece table is readable. The older "beams resolve to W shapes" score chose
an adjacent field on 3 of 9 7.5/7.6 jobs (0% agreement); with the check all 9 agree 82-100%. `preflight.py` reports
it as `sections_vs_main_piece`.

Connection material attached to a member but owned by the connecting member (owner word = another member's id) is
included; before this it was dropped (TRI NORTH: 1,144 placements, 3.2 t). Re-run older conversions to pick it up.

Some jobs model concrete walls/slabs as huge plates (e.g. PL10x251 at 2,514 in long on Merriam); SDS2 weighs them
as steel and the converter reproduces them as-is.

## Exact piece geometry (decode/brep.py)

Piece file topology, 7.1xx-8.0xx (big-endian): u32 holes, hole groups, extra blocks at 0x00/0x04/0x08; u32 nv, nf,
ne at 0x1C; vertex records of 28 B (3 x f64 + tag) from 0x2C; ne loop entries of 10 B (u32 vertex index + flags);
nf face records of 22 B (u16 at +2 = number of loop entries the face takes, in order; kind byte at +4, 7 = work-line /
mid-plane marker face). A face's entries may hold several loops, each closed by repeating its first vertex (outer +
inner loop of hollow-section end faces). 7.0xx: counts at 0x06, 24-B vertices, 8-B loop entries, 16-B face records
(count at +0, marker faces have kind & 0xE0 = 0xE0). Faces are sewn per body (faces joined across edges used by
exactly two faces), so multi-body pieces (joists: chord angles + filler + seats; bolts: nut / washer rings) stay
separate solids.

Holes (after the face records): 46-B hole records (centre 3 x f64, depth = material thickness, u8 group at +33) and
146-B group records (3x3 orientation, row 3 = hole axis; hole diameter, bolt diameter, slot length, slot angle; the
slot runs along cos(a)·X + sin(a)·Y of the group frame), then 172-B blocks that aren't holes. The tail length equals
46·holes + 146·groups + 172·blocks on all 15,629 TRI NORTH piece files. Holes run from the centre along -axis.

Validation:
- TRI NORTH (7.425), 800 random pieces, exact solid volume vs SDS2 net weight: PL 91% within 2% / 100% within 10%,
  bent plates 100% within 2%, HSS 100% within 2%, L 100% / C 100% / FB 100% within 10%; 1 bent plate of 800 not
  sewable (falls back). W shapes are 1.5-6% heavier because SDS2 draws them with its detailing fillet (W14x22:
  k = 1.0625, end-face area 6.84 in² vs AISC 6.49) while its weight is nominal lb/ft × length (1.000 on every W).
- Placement: bbox of the exact solid vs the older prism, 218 TRI NORTH instances: median/p90 difference 0.000 in.
- Coverage per family (300 random plate/rolled pieces each; failures are pieces without a piece file):
  7.021 97%, 7.039 94%, 7.135 42% (58% have no file), 7.310-7.331 83-99%, 7.425 100%, 7.516 98%, 7.613 84% (16% no
  file), 7.708 98%, 8.007 100%; all within the 0.6-1.6 weight guard, 92-100% within 10% of SDS2's weight.
- Holes: 1,786 / 1,787 sampled hole mid-points lie inside the exact solid; slot ends inside the material 99%
  (1,480 / 1,496) with the cos/sin rule vs 81% with the swapped rule; removed volume = π r² depth (+ slot) for 99.5%
  of 193 pieces. TRI NORTH: 7,867 holes cut in 1,319 unique pieces, none failed; +17 s conversion time.
- Joists (7.7xx/8.0xx store them as pieces): solid weight vs SDS2 within 0.2% on every Morgan State joist sampled
  (30K10 4,379.8 vs 4,371.4 lb). 7.0-7.6 jobs have no joist pieces and 7.4 joist records carry no chord names, so
  those joists stay depth x width envelopes.
- Bolt pieces (BLT: nuts, heads, washers) are exact hex / ring solids (TRI NORTH 1.000 median); weld studs, threaded
  studs and rods keep true cylinders (their B-rep is a 12-gon, 0.958 of weight).

Later additions from regenerating every local test job:
- Early 7.1xx piece files (SCHIEL, HARRISON 7.135; Long Branch, Marion County 7.122) use the 7.0 records with the
  counts at 0x0E (`brep.LAYOUTS[2]`); SCHIEL went from 0 to 3,150 exact pieces.
- Some 8.007 builds (Morgan State) end each piece file with a 45-byte trailer; hole decoding allows it (1,953 / 1,953
  hole mid-points inside the material, 1,370 holes cut).
- Pieces whose exact volume is 3.1-3.45x their weight at steel density are concrete weighed at 150 pcf (350 Summer
  Street 5 in slabs "5x494": 21,868 lb as concrete vs SDS2 21,870). They keep their exact geometry, are labelled
  concrete and are left out of the steel tally; the job went from 1.114 (approximate) to 1.024.
- Approximate solids more than 5x SDS2's weight (and > 1,000 lb over) are reported, not written (Center Grove: a
  7 5/8 x 384 wall "plate" whose vertices coincide became a 50-million-lb mesh box).
- Bar grating (GT...) is written as its solid panel but left out of the steel tally (SDS2 weighs the open mesh).
- The tally skips corrupt piece weights (Centene has one of 3e311 lb). When the ratio is off by > 5% the run prints
  the three pieces with the largest weight difference.
- 7.0xx and early-7.1xx hole records (`brep._holes_40`): u16 holes, groups at 0x00; tail = 40·holes + 128·groups
  exactly on every file of RCMS, SUNY, SCHIEL, Long Branch and Merriam (Doing Steel copy). Hole: centre 3 x f64,
  depth f32 at +24, group = high nibble of byte +29. Group: 3x3 orientation f64 (row 3 = axis), hole diameter,
  bolt diameter, slot length, slot angle as f32 at +96/+100/+104/+108. Mapped against the Merriam 7.135 twin whose
  other copy has the 7.1+ records: 1,300 / 1,300 holes identical in every field (955 / 955 group indices on
  multi-group pieces). On true 7.0 jobs without a twin: all hole mid-points inside the material (RCMS 1,026,
  SUNY 211, Long Branch 1,495), cut volume = hole volume on 99.5-100%. Slot direction uses the 7.1 rule; the only
  slots it leaves outside the material (22 on RCMS, all on two L3x3 clips) sit 0.25 in from the leg edge, where
  even the round hole breaks out. The 40/128 decoder claims none of the 20,234 files of the 7.1+ test jobs.
  Holes now cut on 13 7.0 / early-7.1 jobs (e.g. SUNY 5,232, Saralee 6,431, Long Branch 5,165, the Merriam Doing
  Steel copy 826 = its twin); all solids valid after read-back.
- Hole cuts return the single solid rather than the boolean's one-solid compound; with compounds the STEP transfer
  was far slower (SUNY 1,315 s -> 82 s, same holes and weight).

TRI NORTH stage 2 (`out/TriNorth_stage2.step`): 13,427 solids, all BRep-valid after STEP read-back, 9,217 pieces
exact (bolts included), 7,867 holes cut, 0 skipped, steel 600.6 t vs SDS2 590.7 t (1.017); 292 s; the previous
approximate output is kept as `out/TriNorth_stage2_approx.step`. All local test jobs are in `out/samples_exact/`
(`inventory/regen_exact.py`, table in `summary.md` / `summary_rerun.md`).

B-rep repair passes (`brep.solid` retries when the stored faces don't close):
- `conform`: merge coincident vertices and split edges at T-junctions (cope / clip corners on 7.0-record W beams);
- `drop_covered`: drop faces lying inside a larger coplanar face, and duplicate faces (one copy if their edges have 3
  users, both if 4 = internal wall between touching bodies);
- faces OCC's plane fit rejects (collinear leading points) are built on their Newell plane explicitly.
- Plates below 0.6x SDS2's weight are accepted when their extents equal the table L x W x T (cut stiffeners weighed
  as rectangular stock: SUNY PL1/2x3 1/2 at 0.495).
Share of placed steel built exact, before -> after: SCHIEL 56% -> 99.4%, SUNY 74% -> 99.9%, Centene 79% -> 99.6%,
Saralee 81% -> 99.8%, UPMC 82% -> 100%, Seminole 85% -> 99.0%; repaired pieces 94-100% within 10% of SDS2's weight
(median 1.03-1.05, the W fillet effect). TRI NORTH unchanged per family. The remaining Centene PIPE "parse" failures
are 216-byte piece files with no geometry (nominal section builder).

Bolts from SDS2's own records (`decode/bolts.py`). Each bolt is one record in its member file: 3x3 orientation (row
3 = bolt axis), head-side point in the member's main-material frame, then diameter, length and grip (f64 at
+96/+104/+120 and a type byte at +152 indexing `jsetup` `bolts.bolt_list[]` on 7.1xx-8.0xx; f32 at +96/+100/+108 on
7.0xx / early 7.1xx). Found by searching member files for the known hole-stack positions (682-byte records on
7.425), then matched by signature, so record sizes don't matter. Validation on 12 jobs (7.021-8.007):
- decoded heads that land on a hole-stack end are parallel to it with the same diameter; grip equals the stack
  thickness for 92-100% of them on most jobs (55-74% on Henry Ford / Morgan State / NFCU, where stacks miss plies
  without decoded holes);
- 99.9% of lengths are on 1/4 in steps; length - grip is 1.0-1.5 in (nut + washer + stick-out); types are real
  (A325SC, A325N);
- Merriam's two copies (early-7.1 f32 records vs 7.1 f64 records) give the same 1,097 bolts with identical statistics;
- about half of the records sit on no decoded hole (bolts through pieces without hole data: MISC members, joists);
  their fields are just as plausible, so they are kept.
7.0xx: SUNY puts only 5.5% and RCMS 22% of f32-record bolt heads on a hole face with no consistent offset, so for
a job whose f32 records land on holes < 35% of the time only those that do are used (`bolt_records_f32_on_holes`).
Records stored by both connected members are written once. TRI NORTH: 8,956 SDS2 bolts (A325SC / A325N) + 2,970
nominal; 55,433 placed solids, all valid.

Nominal bolts (hole stacks no record covers): every hole carries position, axis and bolt diameter. Holes of
different pieces that line up (same bolt diameter, parallel axes, < 1/16 in apart) form a ply stack; each stack of
>= 2 pieces gets a heavy-hex bolt (head, shank, nut; ASTM A325 head/nut heights, across flats 1.5 d + 1/8) with its
grip = the stack thickness, written once per (diameter, grip) as a shared part. TRI NORTH: 71% of 18,416 placed holes
are in such stacks (median grip 0.69 in); single-ply holes (anchor rods, members without piece geometry) get no
bolt. Kincora: 3,429 bolts, all valid. Head side, washers and bolt length rounding are not in the data.

Investigated and not possible from the data:
- Welds: no weld geometry in readable form (member files only name welded connection classes; `meta/properties`
  holds project flags such as ErectionWelded), and nothing to validate a binary decode against.
- Pre-2018 joist chords: the 7.4 joist records are identical within a series apart from depth (48LH10 = 48LH17),
  i.e. series defaults (seat depth 2.5 / 5 in ...), not chord sizes.

## Known limitations

- Welds are not modelled (see above). Bolts come from SDS2's records (length, grip, grade name on 7.1+); head
  side follows the record's axis, washers are not modelled, and hole stacks without a record get nominal bolts.
  On 7.0 jobs most bolt records can't be validated and are replaced by nominal ones.
- Pieces without a piece file (up to 58% on 7.135 Merriam) still use the approximate builders (no holes).
- 7.0-7.6 joists are solid depth × width envelopes (no chord geometry stored).
- About 1 solid in 10,000 (NFCU piece 2226, one on Centene) passes BRepCheck in its own frame and after a local STEP
  round trip but fails the check once placed at the job's world coordinates; it is still written, and `--verify`
  names it.
- Approximate builders (fallback only): plates stored as a flat 2D outline are extruded by their table thickness;
  plates whose vertex outlines disagree with their table size are built from the vertices.
