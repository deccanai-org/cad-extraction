using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;

namespace Tek
{
    public class ProfileTotal { public string Profile; public double LengthMm, Kg; public double KgPerM { get { return LengthMm > 1 ? Kg / (LengthMm / 1000.0) : 0; } } }

    public class QaResult
    {
        public string Verdict = "SKIP";          // PASS / WARN / FAIL / SKIP
        public int ProfilesCompared;
        public double MaxDeviation;              // fractional, on kg per metre
        public string WorstProfile = "";
        public List<string> Notes = new List<string>();
        public string Detail = "";
    }

    /// Checks a conversion against the Tekla reports that sit in the model folder.
    ///
    /// The comparison is mass per metre per profile, not total mass. Tekla's reports are
    /// often filtered to a subset of the model (this archive's hot-rolled report lists one
    /// ladder's 27 rungs where the model holds four identical ladders), so totals differ
    /// for reasons that have nothing to do with geometry. Mass per metre is pure
    /// cross-section area and is immune to that.
    public static class Qa
    {
        static readonly Regex Totals = new Regex(@"Totals?\s+For\s*:", RegexOptions.IgnoreCase);

        public static Dictionary<string, ProfileTotal> ReadTeklaReports(string modelFolder)
        {
            var res = new Dictionary<string, ProfileTotal>(StringComparer.OrdinalIgnoreCase);
            if (!Directory.Exists(modelFolder)) return res;

            var files = new List<string>();
            foreach (var pat in new[] { "*.xsr", "*.xls", "*.xLS", "*.rep", "*.txt" })
            {
                try { files.AddRange(Directory.GetFiles(modelFolder, pat, SearchOption.TopDirectoryOnly)); }
                catch { }
            }

            foreach (var f in files.Distinct())
            {
                string[] lines;
                try { lines = File.ReadAllLines(f); } catch { continue; }
                foreach (var raw in lines)
                {
                    var m = Totals.Match(raw);
                    if (!m.Success) continue;
                    string rest = raw.Substring(m.Index + m.Length);
                    // Columns are separated by runs of two or more spaces; the profile name
                    // itself contains digits and '*' so splitting on whitespace will not do.
                    var cols = Regex.Split(rest.Trim(), @"\s{2,}").Where(s => s.Length > 0).ToArray();
                    if (cols.Length < 2) continue;
                    string prof = cols[0].Trim();
                    if (prof.Length == 0) continue;

                    var nums = new List<double>();
                    for (int i = 1; i < cols.Length; i++)
                    {
                        double v;
                        string t = cols[i].Trim().TrimEnd('k', 'g', 'K', 'G').Trim();
                        if (double.TryParse(t, NumberStyles.Float, CultureInfo.InvariantCulture, out v)) nums.Add(v);
                    }
                    if (nums.Count < 2) continue;

                    double len = nums[0], kg = nums[nums.Count - 1];
                    if (len <= 0 || kg <= 0) continue;

                    ProfileTotal pt;
                    if (!res.TryGetValue(prof, out pt)) { pt = new ProfileTotal { Profile = prof }; res[prof] = pt; }
                    // Keep the largest report entry for a profile; repeated reports restate
                    // the same totals and we do not want to double count.
                    if (len > pt.LengthMm) { pt.LengthMm = len; pt.Kg = kg; }
                }
            }
            return res;
        }

        public static QaResult Check(ConvertResult conv, string modelFolder)
        {
            var qa = new QaResult();
            var sb = new StringBuilder();

            if (conv == null || !conv.Ok)
            {
                qa.Verdict = "FAIL";
                qa.Notes.Add("conversion did not produce solids");
                qa.Detail = "conversion failed";
                return qa;
            }

            if (conv.FailedSolids > 0)
                qa.Notes.Add(conv.FailedSolids + " parts produced no solid");
            if (conv.CutsLinked > 0 && conv.CutsRejected > conv.CutsLinked * 0.2)
                qa.Notes.Add(conv.CutsRejected + " of " + conv.CutsLinked + " cuts rejected");

            var tekla = ReadTeklaReports(modelFolder);
            sb.AppendLine("QA - mass per metre vs Tekla's own reports");
            sb.AppendLine("model folder: " + modelFolder);
            sb.AppendLine("report profiles found: " + tekla.Count);
            sb.AppendLine();

            if (tekla.Count == 0)
            {
                qa.Verdict = conv.FailedSolids > 0 ? "WARN" : "SKIP";
                qa.Notes.Add("no Tekla report found to check against");
                sb.AppendLine("No Tekla report totals found in the model folder - geometry is unchecked.");
                qa.Detail = sb.ToString();
                return qa;
            }

            // Tekla prints mass to 0.1 kg, so a row totalling a fraction of a kilo carries
            // more rounding than signal - a 125 mm PD32*3 at "0.3 kg" implies anywhere from
            // 2.0 to 2.8 kg/m. Rows below the significance floor are shown but not scored,
            // otherwise the review queue fills with noise.
            const double MinKg = 5.0, MinLenMm = 500.0;

            sb.AppendLine("profile".PadRight(24) + "tekla kg/m".PadLeft(12) + "mine kg/m".PadLeft(12) + "dev".PadLeft(10) + "  scored");
            double worst = 0; string worstProf = ""; int n = 0;
            foreach (var kv in conv.ByProfile.OrderBy(k => k.Key, StringComparer.OrdinalIgnoreCase))
            {
                if (kv.Value.KgPerM <= 0) continue;
                ProfileTotal t;
                if (!tekla.TryGetValue(kv.Key, out t) || t.KgPerM <= 0) continue;
                double dev = Math.Abs(kv.Value.KgPerM - t.KgPerM) / t.KgPerM;
                bool scored = t.Kg >= MinKg && t.LengthMm >= MinLenMm;
                if (scored)
                {
                    n++;
                    if (dev > worst) { worst = dev; worstProf = kv.Key; }
                }
                sb.AppendLine(kv.Key.PadRight(24) + t.KgPerM.ToString("F2").PadLeft(12) +
                              kv.Value.KgPerM.ToString("F2").PadLeft(12) + dev.ToString("P1").PadLeft(10) +
                              (scored ? "  yes" : "  no (below " + MinKg.ToString("F0") + " kg)"));
            }

            qa.ProfilesCompared = n;
            qa.MaxDeviation = worst;
            qa.WorstProfile = worstProf;

            if (n == 0)
            {
                qa.Verdict = "SKIP";
                qa.Notes.Add("no profile names matched between model and report");
            }
            else if (worst <= 0.05) qa.Verdict = "PASS";
            else if (worst <= 0.15) qa.Verdict = "WARN";
            else qa.Verdict = "FAIL";

            if (qa.Verdict == "PASS" && qa.Notes.Count > 0) qa.Verdict = "WARN";

            sb.AppendLine();
            sb.AppendLine("profiles compared : " + n);
            sb.AppendLine("worst deviation   : " + worst.ToString("P1") + (worstProf.Length > 0 ? "  on " + worstProf : ""));
            sb.AppendLine("verdict           : " + qa.Verdict);
            foreach (var note in qa.Notes) sb.AppendLine("  note: " + note);
            sb.AppendLine();
            sb.AppendLine("Tolerances: PASS <= 5%, WARN <= 15%, FAIL above. A 1-2% shortfall is");
            sb.AppendLine("expected - rolled-section root fillets are not modelled.");

            qa.Detail = sb.ToString();
            return qa;
        }
    }
}
