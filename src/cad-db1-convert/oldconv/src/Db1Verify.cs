using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;

namespace Tek
{
    /// Checks the .db1 reader against the ASCII dump of the same model, field by field.
    /// The dump prints 6 decimals, so numeric comparison is to that precision.
    public static class Db1Verify
    {
        public static void Main(string[] args)
        {
            string db1 = args[0], dmp = args[1];

            var got = Db1Reader.Read(db1);
            Console.WriteLine("db1 engine header : " + Db1Reader.Version);
            var want = Dump.Parse(dmp);

            var tables = new[] { "part", "part_attr", "point", "coordsys_attr", "partpolygon", "relation", "object", "assembly" };
            var keyOf = new Dictionary<string, Func<Row, string>>
            {
                { "partpolygon", r => r.S("id") + "/" + r.S("no") },
            };

            int grandFields = 0, grandOk = 0;
            Console.WriteLine();
            Console.WriteLine("table".PadRight(16) + "dump".PadLeft(7) + "read".PadLeft(7) + "matched".PadLeft(9) +
                              "  fields ok / compared");

            foreach (var t in tables)
            {
                var w = want.T(t);
                var g = got.T(t);
                Func<Row, string> key = keyOf.ContainsKey(t) ? keyOf[t] : (r => r.S("id"));

                var gi = new Dictionary<string, Row>();
                foreach (var r in g) { string k = key(r); if (k.Length > 0 && !gi.ContainsKey(k)) gi[k] = r; }

                int matched = 0, fOk = 0, fTot = 0;
                var badFields = new Dictionary<string, int>();
                foreach (var r in w)
                {
                    Row o;
                    if (!gi.TryGetValue(key(r), out o)) continue;
                    matched++;
                    foreach (var kv in r)
                    {
                        string v;
                        if (!o.TryGetValue(kv.Key, out v)) continue;
                        fTot++;
                        if (Same(kv.Value, v)) fOk++;
                        else { int c; badFields.TryGetValue(kv.Key, out c); badFields[kv.Key] = c + 1; }
                    }
                }
                grandFields += fTot; grandOk += fOk;
                Console.WriteLine(t.PadRight(16) + w.Count.ToString().PadLeft(7) + g.Count.ToString().PadLeft(7) +
                                  matched.ToString().PadLeft(9) + "  " + fOk + " / " + fTot +
                                  (fTot > 0 ? "  (" + (100.0 * fOk / fTot).ToString("F2") + "%)" : ""));
                foreach (var bf in badFields.OrderByDescending(x => x.Value).Take(4))
                    Console.WriteLine("        mismatch: " + bf.Key + " x" + bf.Value);
            }

            Console.WriteLine();
            Console.WriteLine("OVERALL FIELD ACCURACY: " + grandOk + " / " + grandFields +
                              "  (" + (100.0 * grandOk / Math.Max(1, grandFields)).ToString("F3") + "%)");

            // spot check the part we have been tracking all along
            var p = got.T("part").FirstOrDefault(r => r.I("id") == 231325);
            if (p != null)
            {
                Console.WriteLine();
                Console.WriteLine("spot check, part 231325 read straight from the .db1:");
                foreach (var k in new[] { "part_attr_id", "p1", "p2", "polygon_id", "csys_attr_id", "csys_x", "csys_y", "csys_z", "csys_length" })
                    Console.WriteLine("   " + k.PadRight(14) + " = " + p.S(k));
            }
        }

        static bool Same(string a, string b)
        {
            if (a == b) return true;
            double x, y;
            if (double.TryParse(a, NumberStyles.Float, CultureInfo.InvariantCulture, out x) &&
                double.TryParse(b, NumberStyles.Float, CultureInfo.InvariantCulture, out y))
                return Math.Abs(x - y) <= Math.Max(1e-6, Math.Abs(x) * 1e-6);
            return string.Equals(a.Trim(), b.Trim(), StringComparison.Ordinal);
        }
    }
}
