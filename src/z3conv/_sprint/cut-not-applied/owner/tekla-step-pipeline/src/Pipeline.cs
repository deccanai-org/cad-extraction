using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace Tek
{
    class Job
    {
        public ModelEntry Entry;
        public ConvertResult Conv;
        public QaResult Qa;
        public string Status = "PENDING";     // OK / FAILED / TIMEOUT / SKIPPED
        public string Error = "";
        public string OutDir = "";
        public double Seconds;
    }

    public static class Pipeline
    {
        const int StackBytes = 256 * 1024 * 1024;   // CSG recursion needs room

        public static int Main(string[] args)
        {
            if (args.Length < 2)
            {
                Console.WriteLine(@"Tekla .db1 -> STEP batch pipeline

  pipeline.exe <archiveRoot> <outputRoot> [options]

    -j N             parallel workers            (default: min(CPU, 8))
    -limit N         convert only the first N    (pilot runs)
    -timeout N       per-model seconds           (default 900)
    -inventory-only  stage 0 only, convert nothing
    -resume          skip models whose STEP already exists
    -nobolts         omit bolts

Outputs under <outputRoot>:
    _inventory.csv   every model folder found, engine version, and route
    _manifest.csv    one row per converted model, with its QA verdict
    _failures.csv    only the rows needing attention
    _summary.txt     run totals
    models\<name>\   the STEP, the conversion report, the part schedule, the QA sheet");
                return 2;
            }

            string root = Path.GetFullPath(args[0]);
            string outRoot = Path.GetFullPath(args[1]);
            int workers = Math.Min(Environment.ProcessorCount, 8);
            int limit = int.MaxValue, timeout = 900;
            bool inventoryOnly = false, resume = false, withBolts = true;

            for (int i = 2; i < args.Length; i++)
            {
                switch (args[i].ToLowerInvariant())
                {
                    case "-j": workers = int.Parse(args[++i]); break;
                    case "-limit": limit = int.Parse(args[++i]); break;
                    case "-timeout": timeout = int.Parse(args[++i]); break;
                    case "-inventory-only": inventoryOnly = true; break;
                    case "-resume": resume = true; break;
                    case "-nobolts": withBolts = false; break;
                    default: Console.WriteLine("unknown option: " + args[i]); return 2;
                }
            }

            if (!Directory.Exists(root)) { Console.WriteLine("no such folder: " + root); return 2; }
            Directory.CreateDirectory(outRoot);
            string modelsDir = Path.Combine(outRoot, "models");
            Directory.CreateDirectory(modelsDir);

            var runClock = System.Diagnostics.Stopwatch.StartNew();

            // ---- stage 0: inventory ----
            Console.WriteLine("stage 0  scanning " + root);
            var entries = Inventory.Scan(root, m => Console.WriteLine("         " + m));
            Inventory.WriteCsv(entries, Path.Combine(outRoot, "_inventory.csv"));

            int withDump = entries.Count(e => e.Route == "DUMP");
            Console.WriteLine("         " + entries.Count + " model folders");
            Console.WriteLine("         " + withDump + " with model.dmp (fallback route)");
            Console.WriteLine("         " + entries.Count(e => e.Route == "DB1") + " readable as .db1 directly");
            Console.WriteLine("         " + entries.Count(e => e.Route == "NO_MODEL") + " with neither");
            var versions = entries.Where(e => e.Version.Length > 0).GroupBy(e => e.Version).OrderByDescending(g => g.Count());
            foreach (var v in versions.Take(12)) Console.WriteLine("         version " + v.Key + " : " + v.Count());

            if (inventoryOnly)
            {
                Console.WriteLine("inventory only - stopping. see " + Path.Combine(outRoot, "_inventory.csv"));
                return 0;
            }

            // ---- stage 1+2: convert and QA ----
            var todo = entries.Where(e => e.Route == "DB1" || e.Route == "DUMP").Take(limit).ToList();
            Console.WriteLine();
            Console.WriteLine("stage 1  converting " + todo.Count + " models on " + workers + " workers");

            var jobs = new ConcurrentBag<Job>();
            int done = 0;
            object gate = new object();

            Parallel.ForEach(todo, new ParallelOptions { MaxDegreeOfParallelism = workers }, e =>
            {
                var job = new Job { Entry = e };
                string safe = MakeSafe(e.RelPath.Length > 0 ? e.RelPath : e.Name);
                job.OutDir = Path.Combine(modelsDir, safe);

                try
                {
                    Directory.CreateDirectory(job.OutDir);
                    string step = Path.Combine(job.OutDir, e.Name + ".step");

                    if (resume && File.Exists(step) && new FileInfo(step).Length > 1024)
                    {
                        job.Status = "SKIPPED";
                        job.Error = "already converted";
                    }
                    else
                    {
                        var clock = System.Diagnostics.Stopwatch.StartNew();
                        ConvertResult cr = null;
                        Exception failure = null;
                        var t = new Thread(() =>
                        {
                            try
                            {
                                var loaded = e.Route == "DB1" ? Db1Reader.Read(e.Db1Path) : Dump.Parse(e.DmpPath);
                                if (e.Route == "DB1" && Db1Reader.Unsupported)
                                    throw new NotSupportedException("unsupported engine " + Db1Reader.Version);
                                cr = Converter.Convert(loaded, e.Route == "DB1" ? e.Db1Path : e.DmpPath, step,
                                        Path.Combine(job.OutDir, "conversion_report.txt"),
                                        Path.Combine(job.OutDir, "part_schedule.csv"),
                                        e.Name, withBolts);
                            }
                            catch (Exception ex) { failure = ex; }
                        }, StackBytes);
                        t.IsBackground = true;
                        t.Start();

                        if (!t.Join(timeout * 1000))
                        {
                            job.Status = "TIMEOUT";
                            job.Error = "exceeded " + timeout + "s";
                        }
                        else if (failure != null)
                        {
                            job.Status = failure is NotSupportedException ? "UNSUPPORTED" : "FAILED";
                            job.Error = failure is NotSupportedException ? failure.Message : failure.GetType().Name + ": " + failure.Message;
                        }
                        else if (cr == null || !cr.Ok)
                        {
                            job.Status = "FAILED";
                            job.Error = cr == null ? "no result" : cr.Error;
                            job.Conv = cr;
                        }
                        else
                        {
                            job.Conv = cr;
                            job.Status = "OK";
                        }
                        clock.Stop();
                        job.Seconds = clock.Elapsed.TotalSeconds;
                    }

                    if (job.Status == "OK")
                    {
                        job.Qa = Qa.Check(job.Conv, e.Folder);
                        File.WriteAllText(Path.Combine(job.OutDir, "qa.txt"), job.Qa.Detail);
                    }
                }
                catch (Exception ex)
                {
                    job.Status = "FAILED";
                    job.Error = ex.GetType().Name + ": " + ex.Message;
                }

                jobs.Add(job);
                lock (gate)
                {
                    done++;
                    Console.WriteLine(string.Format("  [{0}/{1}] {2,-9} {3,-7} {4,6:F1}s  {5}",
                        done, todo.Count, job.Status,
                        job.Qa != null ? job.Qa.Verdict : "",
                        job.Seconds, e.Name));
                }
            });

            var all = jobs.ToList();
            WriteManifest(all, Path.Combine(outRoot, "_manifest.csv"));
            WriteFailures(all, Path.Combine(outRoot, "_failures.csv"));

            runClock.Stop();
            var summary = BuildSummary(root, outRoot, entries, all, workers, runClock.Elapsed);
            File.WriteAllText(Path.Combine(outRoot, "_summary.txt"), summary);
            Console.WriteLine();
            Console.WriteLine(summary);

            int bad = all.Count(j => j.Status == "FAILED" || j.Status == "TIMEOUT" ||
                                     (j.Qa != null && j.Qa.Verdict == "FAIL"));
            return bad == 0 ? 0 : 1;
        }

        static string MakeSafe(string s)
        {
            var sb = new StringBuilder();
            foreach (char c in s) sb.Append(Path.GetInvalidFileNameChars().Contains(c) || c == '\\' || c == '/' ? '_' : c);
            string r = sb.ToString().Trim('_', ' ', '.');
            return r.Length == 0 ? "model" : (r.Length > 120 ? r.Substring(r.Length - 120) : r);
        }

        static void WriteManifest(List<Job> jobs, string path)
        {
            var sb = new StringBuilder();
            sb.AppendLine("model,status,qa_verdict,qa_profiles_compared,qa_max_dev_pct,qa_worst_profile," +
                          "parts,straight,curved,plates,polybeams,bolt_groups,bolts,failed_solids,solids_written," +
                          "cuts_linked,cuts_applied,cuts_rejected,steel_kg,bolt_kg,bbox_x_mm,bbox_y_mm,bbox_z_mm," +
                          "step_mb,seconds,engine,tekla_version,error,step_path");
            foreach (var j in jobs.OrderBy(x => x.Entry.Name, StringComparer.OrdinalIgnoreCase))
            {
                var c = j.Conv;
                sb.AppendLine(string.Join(",", new[]{
                    Inventory.Q(j.Entry.Name), j.Status,
                    j.Qa != null ? j.Qa.Verdict : "",
                    j.Qa != null ? j.Qa.ProfilesCompared.ToString() : "",
                    j.Qa != null ? (j.Qa.MaxDeviation*100).ToString("F1",CultureInfo.InvariantCulture) : "",
                    j.Qa != null ? Inventory.Q(j.Qa.WorstProfile) : "",
                    N(c, x=>x.Parts), N(c, x=>x.Straight), N(c, x=>x.Curved), N(c, x=>x.Plates),
                    N(c, x=>x.PolyBeams), N(c, x=>x.BoltGroups), N(c, x=>x.Bolts),
                    N(c, x=>x.FailedSolids), N(c, x=>x.SolidsWritten),
                    N(c, x=>x.CutsLinked), N(c, x=>x.CutsApplied), N(c, x=>x.CutsRejected),
                    c != null ? c.SteelKg.ToString("F1",CultureInfo.InvariantCulture) : "",
                    c != null ? c.BoltKg.ToString("F1",CultureInfo.InvariantCulture) : "",
                    c != null ? (c.BBoxMax[0]-c.BBoxMin[0]).ToString("F0",CultureInfo.InvariantCulture) : "",
                    c != null ? (c.BBoxMax[1]-c.BBoxMin[1]).ToString("F0",CultureInfo.InvariantCulture) : "",
                    c != null ? (c.BBoxMax[2]-c.BBoxMin[2]).ToString("F0",CultureInfo.InvariantCulture) : "",
                    c != null ? (c.StepBytes/1048576.0).ToString("F2",CultureInfo.InvariantCulture) : "",
                    j.Seconds.ToString("F1",CultureInfo.InvariantCulture),
                    Inventory.Q(j.Entry.Engine), Inventory.Q(j.Entry.Version), Inventory.Q(j.Error),
                    Inventory.Q(c != null ? c.StepPath : "")}));
            }
            File.WriteAllText(path, sb.ToString());
        }

        static string N(ConvertResult c, Func<ConvertResult, int> f) { return c == null ? "" : f(c).ToString(); }

        static void WriteFailures(List<Job> jobs, string path)
        {
            var bad = jobs.Where(j => j.Status == "FAILED" || j.Status == "TIMEOUT" ||
                                      (j.Qa != null && (j.Qa.Verdict == "FAIL" || j.Qa.Verdict == "WARN"))).ToList();
            var sb = new StringBuilder();
            sb.AppendLine("model,status,qa_verdict,max_dev_pct,worst_profile,notes,error,model_folder");
            foreach (var j in bad.OrderBy(x => x.Entry.Name, StringComparer.OrdinalIgnoreCase))
                sb.AppendLine(string.Join(",", new[]{
                    Inventory.Q(j.Entry.Name), j.Status,
                    j.Qa != null ? j.Qa.Verdict : "",
                    j.Qa != null ? (j.Qa.MaxDeviation*100).ToString("F1",CultureInfo.InvariantCulture) : "",
                    j.Qa != null ? Inventory.Q(j.Qa.WorstProfile) : "",
                    j.Qa != null ? Inventory.Q(string.Join("; ", j.Qa.Notes)) : "",
                    Inventory.Q(j.Error), Inventory.Q(j.Entry.Folder)}));
            File.WriteAllText(path, sb.ToString());
        }

        static string BuildSummary(string root, string outRoot, List<ModelEntry> entries,
                                   List<Job> jobs, int workers, TimeSpan elapsed)
        {
            var sb = new StringBuilder();
            sb.AppendLine("Tekla .db1 -> STEP  batch run");
            sb.AppendLine("archive : " + root);
            sb.AppendLine("output  : " + outRoot);
            sb.AppendLine("workers : " + workers);
            sb.AppendLine("wall    : " + elapsed.TotalSeconds.ToString("F1") + " s");
            sb.AppendLine();
            sb.AppendLine("inventory");
            sb.AppendLine("  model folders found    : " + entries.Count);
            sb.AppendLine("  readable .db1          : " + entries.Count(e => e.Route == "DB1"));
            sb.AppendLine("  model.dmp fallback     : " + entries.Count(e => e.Route == "DUMP"));
            sb.AppendLine("  neither                : " + entries.Count(e => e.Route == "NO_MODEL"));
            sb.AppendLine();
            sb.AppendLine("conversion");
            foreach (var g in jobs.GroupBy(j => j.Status).OrderByDescending(g => g.Count()))
                sb.AppendLine("  " + g.Key.PadRight(22) + " : " + g.Count());
            sb.AppendLine();
            sb.AppendLine("QA (mass per metre vs Tekla's own reports)");
            foreach (var g in jobs.Where(j => j.Qa != null).GroupBy(j => j.Qa.Verdict).OrderByDescending(g => g.Count()))
                sb.AppendLine("  " + g.Key.PadRight(22) + " : " + g.Count());
            var ok = jobs.Where(j => j.Status == "OK" && j.Conv != null).ToList();
            if (ok.Count > 0)
            {
                sb.AppendLine();
                sb.AppendLine("throughput");
                sb.AppendLine("  models converted       : " + ok.Count);
                sb.AppendLine("  mean seconds per model : " + ok.Average(j => j.Seconds).ToString("F1"));
                sb.AppendLine("  slowest                : " + ok.Max(j => j.Seconds).ToString("F1") + " s  (" +
                              ok.OrderByDescending(j => j.Seconds).First().Entry.Name + ")");
                sb.AppendLine("  total STEP written     : " + (ok.Sum(j => j.Conv.StepBytes) / 1048576.0).ToString("F1") + " MB");
                sb.AppendLine("  total steel modelled   : " + (ok.Sum(j => j.Conv.SteelKg) / 1000.0).ToString("F1") + " tonnes");
                double perModel = elapsed.TotalSeconds / Math.Max(1, ok.Count);
                sb.AppendLine("  projected for 1000     : " + (perModel * 1000 / 3600.0).ToString("F1") + " h at this width");
            }
            sb.AppendLine();
            sb.AppendLine("see _manifest.csv for every model, _failures.csv for the review queue.");
            return sb.ToString();
        }
    }
}




