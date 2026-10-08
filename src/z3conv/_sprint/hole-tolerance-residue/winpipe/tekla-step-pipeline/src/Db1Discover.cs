using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;

namespace Tek
{
    /// Discovers the `part`, `relation` and `assembly` record layouts for a .db1 engine
    /// version that has no ASCII dump to check against.
    ///
    /// The lever is referential integrity. A genuine part record points at a part_attr,
    /// two points and a coordinate system, and those tables decode already. Only a real
    /// record has four ids that all resolve at consistent offsets, so the layout falls
    /// out of the data instead of being guessed.
    public static class Db1Discover
    {
        public static void Main(string[] args)
        {
            byte[] b = Db1Reader.Load(args[0]);
            string ver = Encoding.ASCII.GetString(b, 0, 12);
            Console.WriteLine("file   : " + Path.GetFileName(args[0]));
            Console.WriteLine("engine : " + ver.Replace('\0', ' '));
            Console.WriteLine("size   : " + b.Length.ToString("N0"));

            var known = Db1Reader.Read(args[0]);
            var PA = new HashSet<int>(known.T("part_attr").Select(r => r.I("id")));
            var PT = new HashSet<int>(known.T("point").Select(r => r.I("id")));
            var CS = new HashSet<int>(known.T("coordsys_attr").Select(r => r.I("id")));
            var PG = new HashSet<int>(known.T("partpolygon").Select(r => r.I("id")));
            Console.WriteLine("anchors: part_attr=" + PA.Count + " point=" + PT.Count +
                              " coordsys_attr=" + CS.Count + " partpolygon=" + PG.Count);
            if (PT.Count < 10 || CS.Count < 5)
            {
                Console.WriteLine("not enough anchor tables decoded - cannot discover");
                return;
            }

            // ---- step 1: where do part_attr_id / p1 / p2 sit relative to the record id? ----
            // Try every plausible triple of offsets. The right one hits thousands of times.
            Console.WriteLine();
            Console.WriteLine("scanning for (part_attr_id, p1, p2) offset triple ...");
            var best = new List<Tuple<int, int, int, int>>();   // count, oAttr, oP1, oP2
            for (int oAttr = 4; oAttr <= 24; oAttr += 4)
                for (int oP1 = oAttr + 4; oP1 <= oAttr + 32; oP1 += 4)
                {
                    int oP2 = oP1 + 4;
                    int hits = 0;
                    for (int i = 0; i + oP2 + 4 <= b.Length; i += 4)
                    {
                        int id = BitConverter.ToInt32(b, i);
                        if (id <= 0 || id > 20000000) continue;
                        if (PA.Count > 200 && !PA.Contains(BitConverter.ToInt32(b, i + oAttr))) continue;
                        if (!PT.Contains(BitConverter.ToInt32(b, i + oP1))) continue;
                        if (!PT.Contains(BitConverter.ToInt32(b, i + oP2))) continue;
                        hits++;
                    }
                    if (hits > 0) best.Add(Tuple.Create(hits, oAttr, oP1, oP2));
                }
            foreach (var t in best.OrderByDescending(x => x.Item1).Take(5))
                Console.WriteLine("   attr@+" + t.Item2 + " p1@+" + t.Item3 + " p2@+" + t.Item4 + "  hits=" + t.Item1);
            if (best.Count == 0) { Console.WriteLine("   none found"); return; }

            var win = best.OrderByDescending(x => x.Item1).First();
            int aOff = win.Item2, p1Off = win.Item3, p2Off = win.Item4;

            // ---- step 2: record starts and stride ----
            var starts = new List<int>();
            for (int i = 0; i + p2Off + 4 <= b.Length; i += 4)
            {
                int id = BitConverter.ToInt32(b, i);
                if (id <= 0 || id > 20000000) continue;
                if (PA.Count > 200 && !PA.Contains(BitConverter.ToInt32(b, i + aOff))) continue;
                if (!PT.Contains(BitConverter.ToInt32(b, i + p1Off))) continue;
                if (!PT.Contains(BitConverter.ToInt32(b, i + p2Off))) continue;
                starts.Add(i);
            }
            var gaps = new Dictionary<int, int>();
            for (int i = 1; i < starts.Count; i++)
            {
                int d = starts[i] - starts[i - 1];
                if (d <= 0 || d > 2048) continue;
                int c; gaps.TryGetValue(d, out c); gaps[d] = c + 1;
            }
            Console.WriteLine();
            Console.WriteLine("candidate part records: " + starts.Count);
            Console.WriteLine("most common strides:");
            foreach (var kv in gaps.OrderByDescending(k => k.Value).Take(6))
                Console.WriteLine("   " + kv.Key.ToString().PadLeft(6) + "  x" + kv.Value);
            if (gaps.Count == 0) return;
            int stride = gaps.OrderByDescending(k => k.Value).First().Key;

            // ---- step 3: the four coordinate doubles, and the remaining id fields ----
            Console.WriteLine();
            Console.WriteLine("field offsets that hold consistently across candidates:");
            int probe = Math.Min(starts.Count, 4000);
            var sample = starts.Take(probe).ToList();

            for (int k = 0; k + 32 <= stride + 16; k += 4)
            {
                int good = 0;
                foreach (var s in sample)
                {
                    if (s + k + 32 > b.Length) continue;
                    double x = BitConverter.ToDouble(b, s + k);
                    double y = BitConverter.ToDouble(b, s + k + 8);
                    double z = BitConverter.ToDouble(b, s + k + 16);
                    double L = BitConverter.ToDouble(b, s + k + 24);
                    if (Fin(x) && Fin(y) && Fin(z) && !double.IsNaN(L) && L >= 0 && L < 1e6 &&
                        (Math.Abs(x) > 1e-9 || Math.Abs(y) > 1e-9 || Math.Abs(z) > 1e-9)) good++;
                }
                if (good > sample.Count * 0.5)
                    Console.WriteLine("   csys_x/y/z/length @ +" + k + "   " + good + "/" + sample.Count);
            }
            for (int k = 0; k + 4 <= stride; k += 4)
            {
                int inCs = 0, inPg = 0;
                foreach (var s in sample)
                {
                    if (s + k + 4 > b.Length) continue;
                    int v = BitConverter.ToInt32(b, s + k);
                    if (CS.Contains(v)) inCs++;
                    if (v == 0 || PG.Contains(v)) inPg++;
                }
                if (inCs > sample.Count * 0.5) Console.WriteLine("   csys_attr_id       @ +" + k + "   " + inCs + "/" + sample.Count);
                else if (inPg > sample.Count * 0.98 && k != 0) Console.WriteLine("   polygon_id (or 0)  @ +" + k + "   " + inPg + "/" + sample.Count);
            }

            Console.WriteLine();
            Console.WriteLine("SUMMARY  engine=" + ver.Trim() + "  part stride=" + stride +
                              "  id@0 part_attr_id@" + aOff + " p1@" + p1Off + " p2@" + p2Off);
        }

        static bool Fin(double v) { return !double.IsNaN(v) && !double.IsInfinity(v) && Math.Abs(v) < 1e8; }
    }
}


