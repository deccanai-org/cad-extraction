using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;

namespace Tek
{
    /// Derives field offsets inside records for an engine version with no ASCII dump.
    /// Anchors come from layout-independent signatures; offsets are then chosen by which
    /// candidate position behaves like the field should across thousands of records
    /// (ids distinct and plausible, strings printable, enums in range).
    public static class Db1Profile
    {
        public static void Main(string[] args)
        {
            byte[] b = Db1Reader.Load(args[0]);
            Console.WriteLine("engine : " + Encoding.ASCII.GetString(b, 0, 12).Replace('\0', ' '));
            Console.WriteLine("size   : " + b.Length.ToString("N0"));

            CoordSys(b);
            Points(b);
            PartAttr(b);
            PolyGon(b);
        }

        // ---------- coordsys_attr ----------
        static void CoordSys(byte[] b)
        {
            var hits = new List<int>();
            for (int i = 0; i + 48 <= b.Length; i++)
            {
                if (!Unit(b, i) || !Unit(b, i + 24)) continue;
                if (Math.Abs(Dot(b, i, i + 24)) > 1e-6) continue;
                hits.Add(i); i += 47;
            }
            int stride = Mode(hits);
            Console.WriteLine();
            Console.WriteLine("=== coordsys_attr  hits=" + hits.Count.ToString("N0") + "  stride=" + stride);
            if (hits.Count < 50) return;
            for (int k = 44; k <= stride + 4 && k <= 76; k += 4)
            {
                int ok = 0; var seen = new HashSet<int>();
                foreach (var h in hits.Take(3000))
                {
                    if (h + k + 4 > b.Length) continue;
                    int v = BitConverter.ToInt32(b, h + k);
                    if (v > 0 && v <= 20000000) { ok++; seen.Add(v); }
                }
                int n = Math.Min(hits.Count, 3000);
                if (ok > n * 0.95 && seen.Count > n * 0.9)
                    Console.WriteLine("   id @ +" + k + "   plausible " + ok + "/" + n + "  distinct " + seen.Count);
            }
        }

        // ---------- point ----------
        static void Points(byte[] b)
        {
            var hits = new List<int>();
            for (int i = 0; i + 32 <= b.Length; i++)
            {
                int id = BitConverter.ToInt32(b, i);
                if (id <= 0 || id > 20000000) continue;
                int vis = BitConverter.ToInt32(b, i + 4);
                if (vis < 0 || vis > 64) continue;
                bool ok = true, any = false;
                for (int k = 8; k <= 24; k += 8)
                {
                    double v = BitConverter.ToDouble(b, i + k);
                    if (double.IsNaN(v) || double.IsInfinity(v) || Math.Abs(v) > 1e7) { ok = false; break; }
                    if (Math.Abs(v) > 1e-6) any = true;
                }
                if (ok && any) { hits.Add(i); i += 31; }
            }
            Console.WriteLine();
            Console.WriteLine("=== point  hits=" + hits.Count.ToString("N0") + "  stride=" + Mode(hits) +
                              "   (layout id@0 vis@4 x@8 y@16 z@24 assumed from anchor)");
        }

        // ---------- part_attr ----------
        static void PartAttr(byte[] b)
        {
            // anchor on profile-looking text
            var hits = new List<int>();
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
            int stride = Mode(hits);
            Console.WriteLine();
            Console.WriteLine("=== part_attr  profile-string hits=" + hits.Count.ToString("N0") + "  stride=" + stride);
            if (hits.Count < 50 || stride <= 0) return;

            // Record start is some fixed distance before the profile string. Find the
            // offset back to a field that behaves like a distinct, plausible id.
            Console.WriteLine("   searching back from the profile string for the record id ...");
            for (int back = 4; back <= Math.Min(stride, 320); back += 4)
            {
                int ok = 0; var seen = new HashSet<int>();
                int n = 0;
                foreach (var h in hits.Take(3000))
                {
                    int o = h - back;
                    if (o < 0 || o + 4 > b.Length) continue;
                    n++;
                    int v = BitConverter.ToInt32(b, o);
                    if (v > 0 && v <= 20000000) { ok++; seen.Add(v); }
                }
                if (n > 100 && ok > n * 0.98 && seen.Count > n * 0.95)
                    Console.WriteLine("      id @ profile-" + back + "   " + ok + "/" + n + " distinct " + seen.Count);
            }
            // where do the other strings sit relative to the profile string?
            Console.WriteLine("   other printable slots near the profile string:");
            for (int d = -320; d <= 320; d += 2)
            {
                if (d == 0) continue;
                int ok = 0, n = 0;
                foreach (var h in hits.Take(2000))
                {
                    int o = h + d;
                    if (o < 0 || o + 3 > b.Length) continue;
                    n++;
                    if (b[o] >= 32 && b[o] <= 126 && b[o + 1] >= 32 && b[o + 1] <= 126 && b[o + 2] >= 32 && b[o + 2] <= 126) ok++;
                }
                if (n > 100 && ok > n * 0.95) Console.WriteLine("      text @ profile" + (d > 0 ? "+" : "") + d + "   " + ok + "/" + n);
            }
        }

        // ---------- partpolygon ----------
        static void PolyGon(byte[] b)
        {
            // ten float32 that look like local coordinates, preceded by a plausible id
            var hits = new List<int>();
            for (int i = 0; i + 60 <= b.Length; i += 1)
            {
                int id = BitConverter.ToInt32(b, i);
                if (id <= 0 || id > 20000000) continue;
                int no = BitConverter.ToInt32(b, i + 4);
                if (no < 0 || no > 64) continue;
                int good = 0;
                for (int k = 12; k < 52; k += 4)
                {
                    float v = BitConverter.ToSingle(b, i + k);
                    if (!float.IsNaN(v) && !float.IsInfinity(v) && Math.Abs(v) < 1e7) good++;
                }
                if (good == 10) { hits.Add(i); i += 59; }
            }
            Console.WriteLine();
            Console.WriteLine("=== partpolygon-like  hits=" + hits.Count.ToString("N0") + "  stride=" + Mode(hits));
        }

        static bool Unit(byte[] b, int o)
        {
            double x = BitConverter.ToDouble(b, o), y = BitConverter.ToDouble(b, o + 8), z = BitConverter.ToDouble(b, o + 16);
            if (double.IsNaN(x) || double.IsNaN(y) || double.IsNaN(z)) return false;
            if (Math.Abs(x) > 1.0000001 || Math.Abs(y) > 1.0000001 || Math.Abs(z) > 1.0000001) return false;
            return Math.Abs(x * x + y * y + z * z - 1) < 1e-6;
        }
        static double Dot(byte[] b, int a, int c)
        {
            return BitConverter.ToDouble(b, a) * BitConverter.ToDouble(b, c) +
                   BitConverter.ToDouble(b, a + 8) * BitConverter.ToDouble(b, c + 8) +
                   BitConverter.ToDouble(b, a + 16) * BitConverter.ToDouble(b, c + 16);
        }
        static int Mode(List<int> hits)
        {
            var g = new Dictionary<int, int>();
            for (int i = 1; i < hits.Count; i++)
            {
                int d = hits[i] - hits[i - 1];
                if (d <= 0 || d > 4096) continue;
                int c; g.TryGetValue(d, out c); g[d] = c + 1;
            }
            return g.Count == 0 ? 0 : g.OrderByDescending(k => k.Value).First().Key;
        }
    }
}
