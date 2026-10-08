using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;

namespace Tek
{
    // Reads back the STEP this tool wrote, checks every reference resolves, rebuilds
    // the faces from the topology and renders them. If this round-trips, the file is
    // structurally sound rather than merely plausible-looking text.
    public static class Verify
    {
        class Ent { public string Type; public string Args; }

        public static void Main(string[] args)
        {
            string path = args[0];
            var ents = new Dictionary<int, Ent>();
            var order = new List<int>();

            var buf = new StringBuilder();
            using (var sr = new StreamReader(path))
            {
                string line;
                bool inData = false;
                while ((line = sr.ReadLine()) != null)
                {
                    if (line.StartsWith("DATA;")) { inData = true; continue; }
                    if (!inData) continue;
                    if (line.StartsWith("ENDSEC")) break;
                    buf.Append(line);
                    if (line.TrimEnd().EndsWith(";"))
                    {
                        string s = buf.ToString().Trim(); buf.Clear();
                        if (!s.StartsWith("#")) continue;
                        int eq = s.IndexOf('=');
                        int id = int.Parse(s.Substring(1, eq - 1));
                        string rhs = s.Substring(eq + 1).TrimEnd(';').Trim();
                        int par = rhs.IndexOf('(');
                        var e = new Ent();
                        if (rhs.StartsWith("("))
                        {
                            e.Type = "COMPLEX"; e.Args = rhs;
                        }
                        else
                        {
                            e.Type = rhs.Substring(0, par).Trim();
                            e.Args = rhs.Substring(par + 1, rhs.LastIndexOf(')') - par - 1);
                        }
                        ents[id] = e;
                        order.Add(id);
                    }
                }
            }

            // reference integrity
            int refs = 0, bad = 0;
            var badList = new List<string>();
            foreach (var kv in ents)
                foreach (var r in Refs(kv.Value.Args))
                {
                    refs++;
                    if (!ents.ContainsKey(r)) { bad++; if (badList.Count < 10) badList.Add("#" + kv.Key + " -> #" + r); }
                }

            var counts = ents.Values.GroupBy(e => e.Type).ToDictionary(g => g.Key, g => g.Count());
            Console.WriteLine("entities           : " + ents.Count);
            Console.WriteLine("references         : " + refs);
            Console.WriteLine("dangling references: " + bad + (badList.Count > 0 ? "  e.g. " + string.Join(", ", badList) : ""));
            foreach (var k in new[] { "PRODUCT", "MANIFOLD_SOLID_BREP", "CLOSED_SHELL", "ADVANCED_FACE", "EDGE_CURVE", "VERTEX_POINT", "CARTESIAN_POINT", "NEXT_ASSEMBLY_USAGE_OCCURRENCE", "STYLED_ITEM", "ADVANCED_BREP_SHAPE_REPRESENTATION" })
                Console.WriteLine(k.PadRight(36) + ": " + (counts.ContainsKey(k) ? counts[k] : 0));

            // rebuild faces
            var pts = new Dictionary<int, V3>();
            foreach (var kv in ents.Where(k => k.Value.Type == "CARTESIAN_POINT"))
            {
                var m = kv.Value.Args;
                int a = m.IndexOf('('), b = m.LastIndexOf(')');
                var n = m.Substring(a + 1, b - a - 1).Split(',').Select(s => double.Parse(s.Trim(), CultureInfo.InvariantCulture)).ToArray();
                pts[kv.Key] = new V3(n[0], n[1], n[2]);
            }
            var vtx = new Dictionary<int, V3>();
            foreach (var kv in ents.Where(k => k.Value.Type == "VERTEX_POINT"))
            {
                var r = Refs(kv.Value.Args).ToList();
                if (r.Count > 0 && pts.ContainsKey(r[0])) vtx[kv.Key] = pts[r[0]];
            }
            var edge = new Dictionary<int, int[]>();
            foreach (var kv in ents.Where(k => k.Value.Type == "EDGE_CURVE"))
            {
                var r = Refs(kv.Value.Args).ToList();
                if (r.Count >= 2) edge[kv.Key] = new[] { r[0], r[1] };
            }

            var tris = new List<V3[]>();
            int faceCount = 0, openLoops = 0;
            foreach (var kv in ents.Where(k => k.Value.Type == "ADVANCED_FACE"))
            {
                faceCount++;
                var r = Refs(kv.Value.Args).ToList();
                foreach (var bref in r)
                {
                    Ent be; if (!ents.TryGetValue(bref, out be)) continue;
                    if (be.Type != "FACE_OUTER_BOUND") continue;
                    var lr = Refs(be.Args).ToList();
                    if (lr.Count == 0) continue;
                    Ent loop; if (!ents.TryGetValue(lr[0], out loop) || loop.Type != "EDGE_LOOP") continue;
                    var poly = new List<V3>();
                    foreach (var oeid in Refs(loop.Args))
                    {
                        Ent oe; if (!ents.TryGetValue(oeid, out oe) || oe.Type != "ORIENTED_EDGE") continue;
                        bool fwd = oe.Args.TrimEnd().EndsWith(".T.");
                        var er = Refs(oe.Args).ToList();
                        if (er.Count == 0 || !edge.ContainsKey(er[0])) continue;
                        var ec = edge[er[0]];
                        int vstart = fwd ? ec[0] : ec[1];
                        if (vtx.ContainsKey(vstart)) poly.Add(vtx[vstart]);
                    }
                    if (poly.Count < 3) { openLoops++; continue; }
                    for (int i = 1; i + 1 < poly.Count; i++) tris.Add(new[] { poly[0], poly[i], poly[i + 1] });
                }
            }
            Console.WriteLine("faces rebuilt      : " + faceCount + "   triangles: " + tris.Count + "   degenerate loops: " + openLoops);

            if (tris.Count == 0) { Console.WriteLine("nothing to draw"); return; }
            var all = tris.SelectMany(t => t).ToList();
            Console.WriteLine("bbox X " + all.Min(p => p.X).ToString("F0") + ".." + all.Max(p => p.X).ToString("F0") +
                              "  Y " + all.Min(p => p.Y).ToString("F0") + ".." + all.Max(p => p.Y).ToString("F0") +
                              "  Z " + all.Min(p => p.Z).ToString("F0") + ".." + all.Max(p => p.Z).ToString("F0"));

            Render(tris, args[1], new V3(1, -1.1, 0.55), 1700, 1400);
            if (args.Length > 2) Render(tris, args[2], new V3(0.15, -1, 0.12), 1700, 1400);
            Console.WriteLine("rendered");
        }

        static IEnumerable<int> Refs(string s)
        {
            for (int i = 0; i < s.Length; i++)
            {
                if (s[i] != '#') continue;
                int j = i + 1; while (j < s.Length && char.IsDigit(s[j])) j++;
                if (j > i + 1) yield return int.Parse(s.Substring(i + 1, j - i - 1));
                i = j - 1;
            }
        }

        static void Render(List<V3[]> tris, string outPng, V3 viewDir, int W, int H)
        {
            V3 f = viewDir.Unit;
            V3 up = new V3(0, 0, 1);
            V3 right = f.Cross(up).Unit;
            V3 camUp = right.Cross(f).Unit;

            var proj = new List<double[]>(tris.Count);
            double minU = 1e18, maxU = -1e18, minV = 1e18, maxV = -1e18;
            foreach (var t in tris)
            {
                double[] q = new double[9];
                for (int i = 0; i < 3; i++)
                {
                    double u = t[i].Dot(right), v = t[i].Dot(camUp), dd = t[i].Dot(f);
                    q[i * 3] = u; q[i * 3 + 1] = v; q[i * 3 + 2] = dd;
                    if (u < minU) minU = u; if (u > maxU) maxU = u;
                    if (v < minV) minV = v; if (v > maxV) maxV = v;
                }
                proj.Add(q);
            }
            double sx = (W - 60) / (maxU - minU), sy = (H - 60) / (maxV - minV);
            double s = Math.Min(sx, sy);
            double ox = 30 - minU * s + ((W - 60) - (maxU - minU) * s) / 2;
            double oy = 30 - minV * s + ((H - 60) - (maxV - minV) * s) / 2;

            var idx = Enumerable.Range(0, proj.Count).ToList();
            idx.Sort((a, b) =>
            {
                double da = (proj[a][2] + proj[a][5] + proj[a][8]) / 3;
                double db = (proj[b][2] + proj[b][5] + proj[b][8]) / 3;
                return db.CompareTo(da);      // far first
            });

            V3 light = new V3(0.4, -0.7, 0.6).Unit;
            using (var bmp = new Bitmap(W, H, PixelFormat.Format24bppRgb))
            using (var g = Graphics.FromImage(bmp))
            {
                g.Clear(Color.FromArgb(250, 250, 248));
                g.SmoothingMode = SmoothingMode.AntiAlias;
                var pen = new Pen(Color.FromArgb(70, 40, 45, 55), 0.6f);
                foreach (int i in idx)
                {
                    var t = tris[i];
                    V3 n = (t[1] - t[0]).Cross(t[2] - t[0]);
                    if (n.Len < 1e-9) continue;
                    n = n.Unit;
                    double lam = Math.Abs(n.Dot(light));
                    int c = (int)(70 + 165 * (0.25 + 0.75 * lam));
                    c = Math.Max(0, Math.Min(255, c));
                    var col = Color.FromArgb(c, (int)(c * 0.99), (int)(c * 0.94));
                    var q = proj[i];
                    var pf = new[]{
                        new PointF((float)(q[0]*s+ox), (float)(H-(q[1]*s+oy))),
                        new PointF((float)(q[3]*s+ox), (float)(H-(q[4]*s+oy))),
                        new PointF((float)(q[6]*s+ox), (float)(H-(q[7]*s+oy)))};
                    using (var br = new SolidBrush(col)) g.FillPolygon(br, pf);
                    g.DrawPolygon(pen, pf);
                }
                bmp.Save(outPng, ImageFormat.Png);
            }
        }
    }
}
