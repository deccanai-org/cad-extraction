# Tekla `.db1` → STEP pipeline

Converts Tekla Structures models to STEP **without Tekla** — no licence, no GUI, no
`model.dmp`. Reads the `.db1` directly. ~2–8 s per model, parallel, with an automated QA
gate against each model's own Tekla reports.

```bash
pipeline.exe "D:\TeklaArchive" "D:\StepOut" -j 8      # batch
pipeline.exe "D:\TeklaArchive" "D:\StepOut" -inventory-only   # read-only survey
db1tostep.exe model.db1 out.step report.txt schedule.csv      # single model
verify.exe out.step preview.png                               # integrity + render
```

| option | |
|---|---|
| `-j N` | parallel workers (default `min(CPU, 8)`) |
| `-limit N` | convert only the first N — pilot runs |
| `-timeout N` | per-model seconds, default 900 |
| `-inventory-only` | stage 0 only, converts nothing |
| `-resume` | skip models whose STEP already exists |
| `-nobolts` | omit bolts, smaller files |

Exit `0` if everything converted and passed QA, `1` if anything needs review.

## Engine version support — read this first

`.db1` is the Xsteel engine's fixed-record store, and **the record layout changes between
engine versions**. Each one must be derived separately.

| engine | era | status |
|---|---|---|
| **6.87** | 2011 | **verified** — 99.75 % field accuracy vs Tekla's own dump |
| **7.01** | 2011-12 | **working** |
| **7.24** | 2015-16 | **working** — layout discovered, not independently verified |
| 7.64 | 2015-16 | **not supported** |
| 8.07 | 2019-20 | **not supported** |

Unsupported versions are detected from the header and reported as **`UNSUPPORTED`** in
`_manifest.csv` with the engine string — they never emit geometry. That matters: a decoder
that half-works produces plausible-but-wrong solids, which across thousands of models is
far worse than producing none.

### What is known about 7.64, and what is missing

Real findings, recorded in `src\Db1Reader.cs`:

```
point          stride 41                       (6.87: 33)
coordsys_attr  stride 61, id @ +56             (6.87: 53, id @ +48)
coordsys       stride 65, csys_attr_id @ +4, x1/y1/z1/length @ +8
part           stride ~164, id@0 part_attr_id@4 p1@16 p2@20
part_attr      stride ~324 from profile-string spacing, field offsets UNKNOWN
```

Two things block it:

1. **`part_attr` is not located.** It holds `prof` and `mat` — the profile and material
   strings. Without them there is no cross-section, so no geometry at all. The
   profile-string spacing gives a stride but the record start could not be pinned: no
   offset behind the string behaves like a distinct plausible id.
2. **No coordinate source for `part`.** 6.87 and 7.24 inline `csys_x/y/z/length` in the
   part record; in 7.64 they are absent. A separate `coordsys` table was found (1,444 rows)
   but no part field references it, so the link is still unidentified.

8.07 has an extra obstacle before any of this: a large model decompresses to **~4 GB**
(Lehigh University: 90 MB → 3.96 GB), past the single-array limit. That reader needs
memory-mapping first.

Honest estimate: a day or so per engine version, and the binding constraint is
**validation, not discovery**. 6.87 was tractable only because the 2011 MoldTek models ship
a `.db1` *and* a matching `model.dmp` — a Rosetta Stone. 7.64+ have no dumps, so a derived
layout can only be checked through the QA gate against `.xsr` reports, which is weaker.

## Extending to a new version

Five tools in `tools\`, roughly in order of use:

| tool | what it does |
|---|---|
| `bootstrap.exe <db1>` | finds table strides with **no** ground truth, from layout-independent signatures: coordinate systems are six doubles forming two orthonormal vectors; points are an id plus three plausible coordinates; part attributes contain profile-looking ASCII |
| `profile.exe <db1>` | derives field offsets *inside* those records — e.g. found `coordsys_attr.id @ +56` for 7.64 |
| `csysprobe.exe <db1>` | hunts a separate `coordsys` table and the part field that references it |
| `discover.exe <db1>` | once some tables decode, pins the `part` layout by referential integrity — only a real part record has ids that all resolve at consistent offsets |
| `layout.exe <dmp> <raw>` | if a model has an ASCII dump, derives every field offset exactly by scoring each byte position as int32/double/float32/ASCII. This is how 6.87 was pinned |
| `db1verify.exe <db1> <dmp>` | field-by-field accuracy check against a dump |

Then add a `PartLayout` entry keyed off the engine number in `src\Db1Reader.cs`, and
**verify before trusting it** — several models passing QA against their own `.xsr` reports.

## Output layout

```
<outputRoot>\
  _inventory.csv   every model folder, engine version, route, sizes
  _manifest.csv    per model: counts, mass, bbox, QA verdict, engine, timing
  _failures.csv    the review queue
  _summary.txt     run totals and throughput
  models\<name>\   <model>.step, conversion_report.txt, part_schedule.csv, qa.txt
```

## The QA gate

Every Tekla model folder carries the reports the detailer issued (`*.xsr`, `*.xls`). The
gate parses their `Totals For:` lines and compares **mass per metre per profile**.

Mass per metre, not total mass — Tekla reports are often filtered to a subset. In the
reference archive the hot-rolled report lists one ladder's 27 `D20` rungs where the model
holds four identical ladders, 108 rungs; totals disagree 4× for reasons unrelated to
geometry. Mass per metre is pure cross-sectional area, immune to that.

PASS ≤ 5 %, WARN ≤ 15 %, FAIL above, SKIP when no report exists. A 1–2 % shortfall is
expected — rolled fillets are not modelled. Rows under 5 kg or 500 mm are shown but not
scored: Tekla prints mass to 0.1 kg, so a 125 mm `PD32*3` at "0.3 kg" implies 2.0–2.8 kg/m.

The gate caught a real 3.8 % error on round bars from inscribed-polygon faceting, now fixed
by scaling facet radius so polygon area equals true circle area.

## Verified results

Eight models converted from `.db1`, no code changes between them:

| model | engine | parts | solids | STEP | time |
|---|---|---|---|---|---|
| 1620-D-028 | 6.87 | 1301 | 1208 | 42.4 MB | 3.8 s |
| 1620-D-034 | 6.87 | 1102 | 946 | 34.3 MB | 2.5 s |
| 1620-D-008 | 7.01 | 654 | 488 | 22.9 MB | 3.1 s |
| 1620-D-009 | 6.87 | 652 | 498 | 16.7 MB | 1.4 s |
| 1220-D-010 | 6.87 | 595 | 532 | 32.4 MB | 2.3 s |
| 1620-D-110 | 6.87 | 489 | 374 | 12.1 MB | 1.7 s |
| 1640-D-012 | 6.87 | 474 | 352 | 12.8 MB | 1.5 s |
| 1620-D-002A | 6.87 | 365 | 314 | 12.4 MB | 1.3 s |

plus N-S Rack and Husky_Ultraformer1 on 7.24.

Two models have dumps, so the reader was checked field by field against Tekla's own export:
**1220-D-010 at 99.750 %**, **1620-D-034 at 99.196 %** — `part`, `part_attr`,
`partpolygon`, `relation`, `assembly` all at 100.00 %.

STEP integrity on 1220-D-010: 651,999 entities, 786,756 references, **zero dangling**,
25,898 faces, no degenerate loops.

## Geometry limitations

- Rolled fillets not modelled — angles/channels run 1–2 % light. Dimensions and positions
  are correct.
- Bolt holes not cut; bolts are solid shaft + hex head + nut at correct positions.
- Circles faceted 16–48 segments by diameter, with facet radius scaled so **area is exact**
  at any count (~1.3 % on diameter).
- Curved members rebuilt as arcs about a detected vessel axis — right for circular access
  platforms, and it does not engage otherwise.
- `form_type 4` paths swept only when the mapping verifies against the part's own
  endpoints; otherwise flat plates.

**Watch for placeholder geometry.** Some models represent the vessel as a solid round bar
(`D2450`, `D2433` in 1620-D-034) — those two parts alone are 371 of that model's 381 tonnes.
Faithful to the source, not a bug, but filter by profile or material before using output
for takeoff.

## Building

No dependencies beyond the .NET Framework compiler already on Windows.

```bash
C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe /optimize+ /main:Tek.Pipeline /out:pipeline.exe src\Dump.cs src\Profiles.cs src\Geom.cs src\Step.cs src\Converter.cs src\Db1Reader.cs src\Qa.cs src\Inventory.cs src\Pipeline.cs
```

```bash
C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe /optimize+ /main:Tek.Db1ToStep /out:db1tostep.exe src\Dump.cs src\Profiles.cs src\Geom.cs src\Step.cs src\Converter.cs src\Db1Reader.cs src\Db1ToStep.cs
```

```bash
C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe /optimize+ /main:Tek.Verify /r:System.Drawing.dll /out:verify.exe src\Geom.cs src\Verify.cs
```
