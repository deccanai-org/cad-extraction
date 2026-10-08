using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;

namespace Tek
{
    public class ModelEntry
    {
        public string Folder = "", Name = "", RelPath = "";
        public string Db1Path = "", DmpPath = "";
        public long Db1Bytes, DmpBytes;
        public string Version = "", LastSave = "", DumpHeader = "";
        public bool MultiUser, HasIfc;
        public string Engine = "";
        public int ReportFiles;
        public string Route = "";      // DB1 | DUMP | NO_MODEL
        public string Note = "";
    }

    /// Stage 0. Read-only walk of an archive: what models are there, what version,
    /// and - the number that decides the whole architecture - which ones carry a
    /// model.dmp that can be converted without a Tekla licence.
    public static class Inventory
    {
        static readonly Regex VersionRe = new Regex(@"^\s*\*\*\*\s*Version:\s*(.+?)\s*$", RegexOptions.Multiline);
        static readonly Regex SaveRe = new Regex(@"^\s*\*\*\*\s*Save\s+(.+?)\s*$", RegexOptions.Multiline);

        public static List<ModelEntry> Scan(string root, Action<string> progress)
        {
            var found = new List<ModelEntry>();
            var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            int dirs = 0;

            var stack = new Stack<string>();
            stack.Push(root);
            while (stack.Count > 0)
            {
                string dir = stack.Pop();
                dirs++;
                if (progress != null && dirs % 500 == 0) progress("scanned " + dirs + " folders, found " + found.Count + " models");

                string[] files, subs;
                try { files = Directory.GetFiles(dir); } catch { continue; }
                try { subs = Directory.GetDirectories(dir); } catch { subs = new string[0]; }

                bool isModel = files.Any(f =>
                {
                    string n = Path.GetFileName(f);
                    return (n.EndsWith(".db1", StringComparison.OrdinalIgnoreCase) &&
                            !n.Equals("xslib.db1", StringComparison.OrdinalIgnoreCase))
                        || n.Equals("save_history.log", StringComparison.OrdinalIgnoreCase)
                        || n.Equals("model.dmp", StringComparison.OrdinalIgnoreCase);
                });

                if (isModel && seen.Add(dir))
                    found.Add(Describe(dir, root, files));

                // A model folder still has sub-folders (drawings, attributes) but they are
                // never models themselves, so do not descend into one.
                if (!isModel)
                    foreach (var s in subs) stack.Push(s);
            }
            return found;
        }

        static ModelEntry Describe(string dir, string root, string[] files)
        {
            var e = new ModelEntry { Folder = dir };
            try { e.RelPath = dir.Length > root.Length ? dir.Substring(root.Length).TrimStart('\\', '/') : Path.GetFileName(dir); }
            catch { e.RelPath = dir; }
            e.Name = Path.GetFileName(dir);

            foreach (var f in files)
            {
                string n = Path.GetFileName(f);
                if (n.EndsWith(".db1", StringComparison.OrdinalIgnoreCase) &&
                    !n.Equals("xslib.db1", StringComparison.OrdinalIgnoreCase) && e.Db1Path.Length == 0)
                {
                    e.Db1Path = f;
                    try { e.Db1Bytes = new FileInfo(f).Length; } catch { }
                    e.Name = Path.GetFileNameWithoutExtension(f);
                }
                else if (n.Equals("model.dmp", StringComparison.OrdinalIgnoreCase))
                {
                    e.DmpPath = f;
                    try { e.DmpBytes = new FileInfo(f).Length; } catch { }
                }
                else if (n.Equals(".This_is_multiuser_model", StringComparison.OrdinalIgnoreCase))
                    e.MultiUser = true;
                else if (n.EndsWith(".ifc", StringComparison.OrdinalIgnoreCase))
                    e.HasIfc = true;
                else if (n.EndsWith(".xsr", StringComparison.OrdinalIgnoreCase) ||
                         n.EndsWith(".xls", StringComparison.OrdinalIgnoreCase))
                    e.ReportFiles++;
            }

            string hist = Path.Combine(dir, "save_history.log");
            if (File.Exists(hist))
            {
                try
                {
                    string txt = ReadTail(hist, 64 * 1024);
                    var vm = VersionRe.Matches(txt);
                    if (vm.Count > 0) e.Version = vm[vm.Count - 1].Groups[1].Value;
                    var sm = SaveRe.Matches(txt);
                    if (sm.Count > 0) e.LastSave = sm[sm.Count - 1].Groups[1].Value;
                }
                catch { }
            }

            if (e.DmpPath.Length > 0)
            {
                try
                {
                    using (var sr = new StreamReader(e.DmpPath))
                    {
                        var buf = new char[64];
                        int k = sr.Read(buf, 0, buf.Length);
                        e.DumpHeader = new string(buf, 0, Math.Max(0, k)).Split('\n')[0].Trim();
                    }
                }
                catch { }
            }

            // The .db1 is read directly now, so it is the primary route; a model.dmp is
            // only a fallback for the rare folders that have one.
            if (e.Db1Path.Length > 0 && e.Db1Bytes > 1024)
            {
                e.Route = "DB1";
                e.Engine = Db1Engine(e.Db1Path);
                if (e.Engine.Length > 0) e.Note = e.Engine;
            }
            else if (e.DmpPath.Length > 0 && e.DmpBytes > 1024) { e.Route = "DUMP"; }
            else { e.Route = "NO_MODEL"; e.Note = "no .db1 and no dump"; }

            return e;
        }

        /// Reads the engine banner without inflating the whole file.
        static string Db1Engine(string path)
        {
            try
            {
                using (var fs = File.OpenRead(path))
                {
                    int b0 = fs.ReadByte(), b1 = fs.ReadByte();
                    fs.Seek(0, SeekOrigin.Begin);
                    Stream s = fs;
                    if (b0 == 0x1F && b1 == 0x8B)
                        s = new System.IO.Compression.GZipStream(fs, System.IO.Compression.CompressionMode.Decompress);
                    var buf = new byte[12];
                    int n = s.Read(buf, 0, 12);
                    if (n < 12) return "";
                    var sb = new StringBuilder();
                    foreach (var c in buf) sb.Append(c >= 32 && c <= 126 ? (char)c : ' ');
                    string v = sb.ToString().Trim();
                    return v.StartsWith("Xsteel") ? v : "";
                }
            }
            catch { return ""; }
        }

        static string ReadTail(string path, int bytes)
        {
            using (var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
            {
                long start = Math.Max(0, fs.Length - bytes);
                fs.Seek(start, SeekOrigin.Begin);
                using (var sr = new StreamReader(fs)) return sr.ReadToEnd();
            }
        }

        public static void WriteCsv(List<ModelEntry> list, string path)
        {
            var sb = new StringBuilder();
            sb.AppendLine("model,rel_path,route,engine,tekla_version,last_save,multiuser,db1_mb,dump_mb,report_files,has_ifc,note,folder");
            foreach (var e in list.OrderBy(x => x.RelPath, StringComparer.OrdinalIgnoreCase))
                sb.AppendLine(string.Join(",", new[]{
                    Q(e.Name), Q(e.RelPath), e.Route, Q(e.Engine), Q(e.Version), Q(e.LastSave), e.MultiUser ? "yes" : "no",
                    (e.Db1Bytes/1048576.0).ToString("F2",CultureInfo.InvariantCulture),
                    (e.DmpBytes/1048576.0).ToString("F2",CultureInfo.InvariantCulture),
                    e.ReportFiles.ToString(), e.HasIfc ? "yes" : "no", Q(e.Note), Q(e.Folder)}));
            File.WriteAllText(path, sb.ToString());
        }

        internal static string Q(string s)
        {
            if (s == null) return "";
            return s.IndexOfAny(new[] { ',', '"', '\n', '\r' }) >= 0 ? "\"" + s.Replace("\"", "\"\"") + "\"" : s;
        }
    }
}

