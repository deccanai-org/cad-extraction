using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;

namespace Tek
{
    public class Row : Dictionary<string, string>
    {
        public string S(string k) { string v; return TryGetValue(k, out v) ? v : ""; }
        public double D(string k)
        {
            string v; if (!TryGetValue(k, out v)) return 0;
            double r; return double.TryParse(v, NumberStyles.Float, CultureInfo.InvariantCulture, out r) ? r : 0;
        }
        public int I(string k)
        {
            string v; if (!TryGetValue(k, out v)) return 0;
            int r; return int.TryParse(v, NumberStyles.Integer, CultureInfo.InvariantCulture, out r) ? r : 0;
        }
    }

    // Reads the ASCII "Xsteel dump" produced by Tekla's database dump command.
    // Only the leading Model block is of interest; everything from the first
    // Drawing block onwards is drawing data and is skipped.
    public class Dump
    {
        public Dictionary<string, List<Row>> Tables = new Dictionary<string, List<Row>>();

        public List<Row> T(string name)
        {
            List<Row> r; return Tables.TryGetValue(name, out r) ? r : new List<Row>();
        }

        public static Dump Parse(string path)
        {
            var d = new Dump();
            List<Row> cur = null;
            Row row = null;
            using (var sr = new StreamReader(path))
            {
                string line;
                while ((line = sr.ReadLine()) != null)
                {
                    string t = line.Trim();
                    if (t.Length == 0) continue;
                    if (t.StartsWith("Drawing '")) break;

                    if (t.StartsWith("Table "))
                    {
                        int i = t.IndexOf(" -", StringComparison.Ordinal);
                        string name = (i > 0 ? t.Substring(6, i - 6) : t.Substring(6)).Trim();
                        if (!d.Tables.TryGetValue(name, out cur)) { cur = new List<Row>(); d.Tables[name] = cur; }
                        row = null;
                        continue;
                    }
                    if (t == "row") { row = new Row(); continue; }
                    if (row != null && t == "}")
                    {
                        if (cur != null) cur.Add(row);
                        row = null;
                        continue;
                    }
                    if (row != null)
                    {
                        int eq = t.IndexOf(" = ", StringComparison.Ordinal);
                        if (eq > 0)
                        {
                            string k = t.Substring(0, eq);
                            string v = t.Substring(eq + 3).Trim();
                            if (v.Length >= 2 && v[0] == '\'' && v[v.Length - 1] == '\'')
                                v = v.Substring(1, v.Length - 2);
                            row[k] = v;
                        }
                    }
                }
            }
            return d;
        }

        public static Dictionary<int, Row> Index(List<Row> rows, string key)
        {
            var m = new Dictionary<int, Row>();
            foreach (var r in rows) { int id = r.I(key); if (id != 0) m[id] = r; }
            return m;
        }
    }
}
