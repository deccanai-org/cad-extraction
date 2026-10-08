using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;

namespace Tek
{
    /// Derives the byte layout of .db1 table records automatically.
    ///
    /// Records are located by a signature built from the ASCII dump of the same model.
    /// Each candidate offset is then tested as int32 / double / ASCII against every
    /// probed row. Rows whose value is zero or empty are ignored when scoring, otherwise
    /// any run of padding "agrees" with them and the answer is meaningless.
    public static class Db1Layout
    {
        static byte[] Bin;

        class Spec
        {
            public string Table;
            public string[] LocInts = new string[0];
            public string[] LocDbls = new string[0];
            public int Stride;
        }

        public static void Main(string[] args)
        {
            Bin = File.ReadAllBytes(args[1]);
            var dump = Dump.Parse(args[0]);
            Console.WriteLine("db1: " + Bin.Length.ToString("N0") + " bytes");

            var specs = new[]
            {
                // hash_id is a 32-bit hash, distinctive enough to pin a polygon record.
                new Spec { Table="partpolygon",   LocInts=new[]{"hash_id"} },
                // six direction cosines, not three: 0/Â±1 repeat far too often.
                new Spec { Table="coordsys_attr", LocDbls=new[]{"xdir_x","xdir_y","xdir_z","ydir_x","ydir_y","ydir_z"} },
            };

            foreach (var s in specs) Derive(dump, s);
        }

        static void Derive(Dump dump, Spec spec)
        {
            var rows = dump.T(spec.Table);
            Console.WriteLine();
            Console.WriteLine("================ " + spec.Table + "   rows " + rows.Count);
            if (rows.Count == 0) { Console.WriteLine("  (empty)"); return; }

            var located = new List<KeyValuePair<Row, long>>();
            foreach (var r in rows.Take(150))
            {
                long off;
                if (spec.LocDbls.Length > 0)
                {
                    // The dump prints doubles to 6 decimals, so the stored bits differ.
                    // Locate by value within a tolerance instead of matching bytes.
                    var want = spec.LocDbls.Select(f => r.D(f)).ToArray();
                    if (want.All(v => Math.Abs(v) < 1e-9)) continue;      // all-zero row is not locatable
                    off = FindDoubles(want, 1e-4);
                }
                else
                {
                    var pat = new List<byte>();
                    foreach (var f in spec.LocInts) pat.AddRange(BitConverter.GetBytes(r.I(f)));
                    if (pat.Count == 0) continue;
                    off = Find(pat.ToArray());
                }
                if (off >= 0) located.Add(new KeyValuePair<Row, long>(r, off));
            }
            Console.WriteLine("located " + located.Count + " of " + Math.Min(150, rows.Count) + " probed");
            if (located.Count < 8) { Console.WriteLine("  too few - locator needs rework"); return; }

            // stride from consecutive record offsets
            var offs = located.Select(x => x.Value).OrderBy(x => x).ToList();
            var gaps = new Dictionary<long, int>();
            for (int i = 1; i < offs.Count; i++)
            {
                long d = offs[i] - offs[i - 1];
                if (d <= 0 || d > 8192) continue;
                int c; gaps.TryGetValue(d, out c); gaps[d] = c + 1;
            }
            long stride = gaps.Count > 0 ? gaps.OrderByDescending(k => k.Value).First().Key : 0;
            Console.WriteLine("stride: " + stride + "   region " + offs[0].ToString("N0") + " .. " + offs[offs.Count - 1].ToString("N0"));

            var fields = new List<string>();
            foreach (var kv in located) foreach (var k in kv.Key.Keys) if (!fields.Contains(k)) fields.Add(k);

            int win = (int)Math.Max(stride, 64) + 16;
            Console.WriteLine();
            Console.WriteLine("field".PadRight(20) + "type".PadRight(8) + "off".PadLeft(6) + "   agree  informative");
            foreach (var f in fields)
            {
                string kind = null; int bOff = 0, bHit = 0, bInf = 0;
                for (int off = -16; off + 8 <= win; off++)
                {
                    int okI = 0, okD = 0, okS = 0, okF = 0, infI = 0, infD = 0, infS = 0;
                    foreach (var kv in located)
                    {
                        long b = kv.Value + off;
                        if (b < 0 || b + 8 > Bin.Length) continue;
                        string sv = kv.Key.S(f);
                        if (sv.Length == 0) continue;

                        int iv; double dv;
                        bool isInt = int.TryParse(sv, out iv);
                        bool isDbl = double.TryParse(sv, NumberStyles.Float, CultureInfo.InvariantCulture, out dv);

                        if (isInt && iv != 0) { infI++; if (BitConverter.ToInt32(Bin, (int)b) == iv) okI++; }
                        if (isDbl && Math.Abs(dv) > 1e-12)
                        {
                            infD++;
                            if (Math.Abs(BitConverter.ToDouble(Bin, (int)b) - dv) < 1e-6) okD++;
                            // 32-bit float too: some arrays are stored single-precision
                            float fv = BitConverter.ToSingle(Bin, (int)b);
                            if (!float.IsNaN(fv) && Math.Abs(fv - dv) < Math.Max(1e-3, Math.Abs(dv) * 1e-6)) okF++;
                        }
                        if (!isDbl) { infS++; if (MatchAscii(b, sv)) okS++; }
                    }
                    if (infI >= 8 && okI > bHit) { bHit = okI; bInf = infI; kind = "int32"; bOff = off; }
                    if (infD >= 8 && okD > bHit) { bHit = okD; bInf = infD; kind = "double"; bOff = off; }
                    if (infD >= 8 && okF > bHit) { bHit = okF; bInf = infD; kind = "float32"; bOff = off; }
                    if (infS >= 5 && okS > bHit) { bHit = okS; bInf = infS; kind = "ascii"; bOff = off; }
                }
                if (kind != null && bInf > 0 && bHit >= bInf * 0.95)
                    Console.WriteLine(f.PadRight(20) + kind.PadRight(8) + bOff.ToString().PadLeft(6) + "   " +
                                      bHit + "/" + bInf);
                else
                    Console.WriteLine(f.PadRight(20) + "-".PadRight(8) + "".PadLeft(6) + "   " +
                                      (kind == null ? "no informative rows" : "best " + bHit + "/" + bInf + " as " + kind + " @" + bOff));
            }
        }

        static bool MatchAscii(long b, string s)
        {
            if (b + s.Length > Bin.Length) return false;
            for (int i = 0; i < s.Length; i++) if (Bin[b + i] != (byte)s[i]) return false;
            return true;
        }

        // Finds a run of consecutive doubles matching the wanted values within tol.
        static long FindDoubles(double[] want, double tol)
        {
            int need = want.Length * 8;
            for (int i = 0; i + need <= Bin.Length; i++)
            {
                bool ok = true;
                for (int j = 0; j < want.Length; j++)
                {
                    double v = BitConverter.ToDouble(Bin, i + j * 8);
                    if (double.IsNaN(v) || Math.Abs(v - want[j]) > tol) { ok = false; break; }
                }
                if (ok) return i;
            }
            return -1;
        }

        static long Find(byte[] pat)
        {
            byte f = pat[0];
            for (int i = 0; i + pat.Length <= Bin.Length; i++)
            {
                if (Bin[i] != f) continue;
                bool ok = true;
                for (int j = 1; j < pat.Length; j++) if (Bin[i + j] != pat[j]) { ok = false; break; }
                if (ok) return i;
            }
            return -1;
        }
    }
}

