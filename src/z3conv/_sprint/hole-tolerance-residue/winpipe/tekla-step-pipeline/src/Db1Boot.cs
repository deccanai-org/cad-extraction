using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;

namespace Tek
{
    /// Bootstraps table strides for an engine version with no ASCII dump and no working
    /// anchors, using signatures that are true regardless of layout:
    ///   coordsys_attr - six doubles forming two orthonormal vectors
    ///   point         - three finite doubles preceded by a small positive id
    ///   part_attr     - records containing profile/material-looking ASCII
    /// Stride falls out of the spacing between consecutive hits.
    public static class Db1Boot
    {
        public static void Main(string[] args)
        {
            byte[] b = Db1Reader.Load(args[0]);
            Console.WriteLine("engine : " + Encoding.ASCII.GetString(b, 0, 12).Replace('\0', ' '));
            Console.WriteLine("size   : " + b.Length.ToString("N0"));

            Report("coordsys_attr", Orthonormal(b), 24);
            Report("point-like", PointLike(b), 24);
            Report("part_attr (profile strings)", ProfileStrings(b), 24);
        }

        static void Report(string what, List<long> hits, int top)
        {
            Console.WriteLine();
            Console.WriteLine("=== " + what + " : " + hits.Count.ToString("N0") + " hits");
            if (hits.Count < 10) { Console.WriteLine("   too few"); return; }
            hits.Sort();
            var gaps = new Dictionary<long, int>();
            for (int i = 1; i < hits.Count; i++)
            {
                long d = hits[i] - hits[i - 1];
                if (d <= 0 || d > 4096) continue;
                int c; gaps.TryGetValue(d, out c); gaps[d] = c + 1;
            }
            Console.WriteLine("   span " + hits[0].ToString("N0") + " .. " + hits[hits.Count - 1].ToString("N0"));
            foreach (var kv in gaps.OrderByDescending(k => k.Value).Take(6))
                Console.WriteLine("   stride " + kv.Key.ToString().PadLeft(6) + "  x" + kv.Value);
        }

        /// Six doubles: two unit vectors that are perpendicular to each other.
        static List<long> Orthonormal(byte[] b)
        {
            var hits = new List<long>();
            for (int i = 0; i + 48 <= b.Length; i++)
            {
                double ax = BitConverter.ToDouble(b, i), ay = BitConverter.ToDouble(b, i + 8), az = BitConverter.ToDouble(b, i + 16);
                if (!Ok(ax) || !Ok(ay) || !Ok(az)) continue;
                double la = ax * ax + ay * ay + az * az;
                if (Math.Abs(la - 1) > 1e-6) continue;
                double bx = BitConverter.ToDouble(b, i + 24), by = BitConverter.ToDouble(b, i + 32), bz = BitConverter.ToDouble(b, i + 40);
                if (!Ok(bx) || !Ok(by) || !Ok(bz)) continue;
                double lb = bx * bx + by * by + bz * bz;
                if (Math.Abs(lb - 1) > 1e-6) continue;
                if (Math.Abs(ax * bx + ay * by + az * bz) > 1e-6) continue;
                hits.Add(i);
                i += 47;
            }
            return hits;
        }

        /// A positive id, a small flag, then three plausible model coordinates.
        static List<long> PointLike(byte[] b)
        {
            var hits = new List<long>();
            for (int i = 0; i + 32 <= b.Length; i += 1)
            {
                int id = BitConverter.ToInt32(b, i);
                if (id <= 0 || id > 20000000) continue;
                int vis = BitConverter.ToInt32(b, i + 4);
                if (vis < 0 || vis > 64) continue;
                bool ok = true; bool any = false;
                for (int k = 8; k <= 24; k += 8)
                {
                    double v = BitConverter.ToDouble(b, i + k);
                    if (double.IsNaN(v) || double.IsInfinity(v) || Math.Abs(v) > 1e7) { ok = false; break; }
                    if (Math.Abs(v) > 1e-6) any = true;
                }
                if (ok && any) { hits.Add(i); i += 31; }
            }
            return hits;
        }

        /// Text that looks like a steel profile: digits plus '*' inside a printable run.
        static List<long> ProfileStrings(byte[] b)
        {
            var hits = new List<long>();
            int start = -1;
            for (int i = 0; i < b.Length; i++)
            {
                byte c = b[i];
                bool p = c >= 32 && c <= 126;
                if (p) { if (start < 0) start = i; }
                else
                {
                    if (start >= 0 && i - start >= 5 && i - start <= 40)
                    {
                        string s = Encoding.ASCII.GetString(b, start, i - start);
                        if (s.Contains("*") && s.Any(char.IsDigit) && s.Any(char.IsLetter)) hits.Add(start);
                    }
                    start = -1;
                }
            }
            return hits;
        }

        static bool Ok(double v) { return !double.IsNaN(v) && !double.IsInfinity(v) && Math.Abs(v) <= 1.0000001; }
    }
}
