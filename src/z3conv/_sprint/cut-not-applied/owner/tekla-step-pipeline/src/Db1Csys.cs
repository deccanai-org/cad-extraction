using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;

namespace Tek
{
    /// In newer engines the part record stopped inlining its coordinate frame and points
    /// at a `coordsys` row instead (id, csys_attr_id, x1, y1, z1, length) - a table that
    /// already exists in the 6.87 schema. This locates it and then finds which field of
    /// the part record references it.
    public static class Db1Csys
    {
        public static void Main(string[] args)
        {
            byte[] b = Db1Reader.Load(args[0]);
            Console.WriteLine("engine : " + Encoding.ASCII.GetString(b, 0, 12).Replace('\0', ' '));

            var known = Db1Reader.Read(args[0]);
            var CS = new HashSet<int>(known.T("coordsys_attr").Select(r => r.I("id")));
            var PT = new HashSet<int>(known.T("point").Select(r => r.I("id")));
            Console.WriteLine("coordsys_attr ids: " + CS.Count + "   point ids: " + PT.Count);

            // ---- find coordsys: id, ref into coordsys_attr, then 3 coords + a length ----
            Console.WriteLine();
            Console.WriteLine("=== locating `coordsys` (id, csys_attr_id, x1, y1, z1, length) ===");
            for (int oRef = 4; oRef <= 12; oRef += 4)
                for (int oXyz = oRef + 4; oXyz <= oRef + 20; oXyz += 4)
                {
                    var hits = new List<int>();
                    for (int i = 0; i + oXyz + 32 <= b.Length; i++)
                    {
                        int id = BitConverter.ToInt32(b, i);
                        if (id <= 0 || id > 20000000) continue;
                        if (!CS.Contains(BitConverter.ToInt32(b, i + oRef))) continue;
                        double x = BitConverter.ToDouble(b, i + oXyz);
                        double y = BitConverter.ToDouble(b, i + oXyz + 8);
                        double z = BitConverter.ToDouble(b, i + oXyz + 16);
                        double L = BitConverter.ToDouble(b, i + oXyz + 24);
                        if (!Fin(x) || !Fin(y) || !Fin(z)) continue;
                        if (double.IsNaN(L) || L < 0 || L > 1e6) continue;
                        if (Math.Abs(x) < 1e-9 && Math.Abs(y) < 1e-9 && Math.Abs(z) < 1e-9) continue;
                        hits.Add(i);
                        i += 16;
                    }
                    if (hits.Count < 200) continue;
                    int stride = Mode(hits);
                    Console.WriteLine("   ref@+" + oRef + " xyz@+" + oXyz + "   hits=" + hits.Count.ToString("N0") + "  stride=" + stride);
                    if (hits.Count > 1000 && stride > 0)
                    {
                        var ids = new HashSet<int>();
                        foreach (var h in hits) ids.Add(BitConverter.ToInt32(b, h));
                        Console.WriteLine("      distinct ids: " + ids.Count.ToString("N0"));
                        FindPartRef(b, PT, ids);
                        return;
                    }
                }
            Console.WriteLine("   no coordsys table found with those shapes");
        }

        /// Which int field of the part record points at a coordsys row?
        static void FindPartRef(byte[] b, HashSet<int> PT, HashSet<int> CSYS)
        {
            Console.WriteLine();
            Console.WriteLine("=== part record: locating the coordsys reference ===");
            var starts = new List<int>();
            for (int i = 0; i + 24 <= b.Length; i += 4)
            {
                int id = BitConverter.ToInt32(b, i);
                if (id <= 0 || id > 20000000) continue;
                if (!PT.Contains(BitConverter.ToInt32(b, i + 16))) continue;
                if (!PT.Contains(BitConverter.ToInt32(b, i + 20))) continue;
                starts.Add(i);
            }
            Console.WriteLine("   part candidates (p1@16 p2@20): " + starts.Count.ToString("N0") + "  stride=" + Mode(starts));
            var sample = starts.Take(6000).ToList();
            for (int k = 0; k <= 160; k += 4)
            {
                int hit = 0;
                foreach (var s in sample)
                {
                    if (s + k + 4 > b.Length) continue;
                    if (CSYS.Contains(BitConverter.ToInt32(b, s + k))) hit++;
                }
                if (hit > sample.Count * 0.5)
                    Console.WriteLine("      coordsys ref @ +" + k + "   " + hit + "/" + sample.Count);
            }
        }

        static bool Fin(double v) { return !double.IsNaN(v) && !double.IsInfinity(v) && Math.Abs(v) < 1e8; }
        static int Mode(List<int> h)
        {
            var g = new Dictionary<int, int>();
            for (int i = 1; i < h.Count; i++)
            {
                int d = h[i] - h[i - 1];
                if (d <= 0 || d > 4096) continue;
                int c; g.TryGetValue(d, out c); g[d] = c + 1;
            }
            return g.Count == 0 ? 0 : g.OrderByDescending(k => k.Value).First().Key;
        }
    }
}
