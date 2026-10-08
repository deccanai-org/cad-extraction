using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;

namespace Tek
{
    // A cross-section, expressed in the part's local (y, z) plane and centred on
    // the bounding box of the section. Tekla's convention is profile height h
    // along local Z and width b along local Y.
    public class Section
    {
        public string Kind = "?";
        public double B;              // width, along local Y
        public double H;              // height, along local Z
        public double T;              // wall / thickness where meaningful
        public List<double[]> Outline = new List<double[]>();   // (y, z), centred
        public List<List<double[]>> Holes = new List<List<double[]>>();
        public bool Ok { get { return Outline.Count >= 3; } }
    }

    public static class Profiles
    {
        // Facet count scaled to the diameter, so a 20 mm bar stays cheap while a
        // 1440 mm tube still looks round (chord error stays under ~1 mm).
        static int Segs(double d)
        {
            int n = (int)Math.Ceiling(Math.PI * d / 12.0);
            // The area-preserving radius above makes mass exact at any count, so this
            // only trades visual roundness against file size. 16 costs 1.3% on diameter.
            return Math.Max(16, Math.Min(48, n));
        }

        static double[] Nums(string s)
        {
            var parts = s.Split('*');
            var v = new List<double>();
            foreach (var p in parts)
            {
                double d;
                if (double.TryParse(p.Trim(), NumberStyles.Float, CultureInfo.InvariantCulture, out d)) v.Add(d);
                else return null;
            }
            return v.ToArray();
        }

        static List<double[]> Rect(double b, double h)
        {
            return new List<double[]> {
                new[]{-b/2,-h/2}, new[]{ b/2,-h/2}, new[]{ b/2, h/2}, new[]{-b/2, h/2}
            };
        }

        public static List<double[]> Circle(double d, double cy, double cz, bool ccw)
        {
            return Circle(d, cy, cz, ccw, Segs(d));
        }

        public static List<double[]> Circle(double d, double cy, double cz, bool ccw, int segs)
        {
            // An inscribed polygon loses area - 4.5% at 12 sides, which showed up as a
            // 3.8% mass error on the D20 rungs. Nudge the radius out so the polygon's
            // area equals the true circle's; at 24 sides that costs 0.6% on diameter and
            // makes mass exact, which is the better trade for takeoff and QA.
            double theta = 2 * Math.PI / segs;
            double r = (d / 2) * Math.Sqrt(theta / Math.Sin(theta));
            var l = new List<double[]>();
            for (int i = 0; i < segs; i++)
            {
                double a = theta * (ccw ? i : (segs - i) % segs);
                l.Add(new[] { cy + r * Math.Cos(a), cz + r * Math.Sin(a) });
            }
            return l;
        }

        // Angle: legs h (along Z) and b (along Y), thickness t, heel at (-b/2,-h/2).
        static List<double[]> Angle(double b, double h, double t)
        {
            double y0 = -b / 2, z0 = -h / 2;
            return new List<double[]> {
                new[]{y0,      z0},
                new[]{y0 + b,  z0},
                new[]{y0 + b,  z0 + t},
                new[]{y0 + t,  z0 + t},
                new[]{y0 + t,  z0 + h},
                new[]{y0,      z0 + h}
            };
        }

        // Channel. B is the section depth (along local Y), H the flange width
        // (along local Z); the web sits at the -Z face and the flanges open to +Z.
        static List<double[]> Channel(double B, double H, double tw, double tf)
        {
            double y0 = -B / 2, z0 = -H / 2;
            return new List<double[]> {
                new[]{y0,        z0},
                new[]{y0 + B,    z0},
                new[]{y0 + B,    z0 + H},
                new[]{y0 + B-tf, z0 + H},
                new[]{y0 + B-tf, z0 + tw},
                new[]{y0 + tf,   z0 + tw},
                new[]{y0 + tf,   z0 + H},
                new[]{y0,        z0 + H}
            };
        }

        // I/H section. B is the depth (along local Y), H the flange width (along Z).
        static List<double[]> IShape(double B, double H, double tw, double tf)
        {
            double y0 = -B / 2, z0 = -H / 2;
            double k = (H - tw) / 2;
            return new List<double[]> {
                new[]{y0,        z0},
                new[]{y0 + tf,   z0},
                new[]{y0 + tf,   z0 + k},
                new[]{y0 + B-tf, z0 + k},
                new[]{y0 + B-tf, z0},
                new[]{y0 + B,    z0},
                new[]{y0 + B,    z0 + H},
                new[]{y0 + B-tf, z0 + H},
                new[]{y0 + B-tf, z0 + k + tw},
                new[]{y0 + tf,   z0 + k + tw},
                new[]{y0 + tf,   z0 + H},
                new[]{y0,        z0 + H}
            };
        }

        // Bolt shank diameter from a Tekla bolt profile string, e.g. MM16*45/...
        public static bool BoltDims(string prof, out double dia, out double len)
        {
            dia = 0; len = 0;
            if (string.IsNullOrEmpty(prof) || !prof.StartsWith("MM")) return false;
            string head = prof.Split('/')[0].Substring(2);
            var n = Nums(head);
            if (n == null || n.Length < 2) return false;
            dia = n[0]; len = n[1];
            return dia > 0 && len > 0;
        }

        // Thickness of a plate-style profile, used for contour plates and cuts.
        public static double PlateThickness(string prof)
        {
            var s = Parse(prof);
            return s != null && s.H > 0 ? s.H : 0;
        }

        public static Section Parse(string prof)
        {
            if (string.IsNullOrEmpty(prof)) return null;
            string p = prof.Trim().ToUpperInvariant();
            var s = new Section();

            // Bolts are handled separately.
            if (p.StartsWith("MM")) return null;

            // Channel: [h*b*tw*tf
            if (p.StartsWith("["))
            {
                var n = Nums(p.Substring(1));
                if (n != null && n.Length >= 4)
                {
                    s.Kind = "C"; s.B = n[0]; s.H = n[1]; s.T = n[2];
                    s.Outline = Channel(n[0], n[1], n[2], n[3]);
                    return s;
                }
                return null;
            }

            // Angle: L h*b*t
            if (p.StartsWith("L") && p.Contains("*"))
            {
                var n = Nums(p.Substring(1));
                if (n != null && n.Length >= 3)
                {
                    s.Kind = "L"; s.B = n[0]; s.H = n[1]; s.T = n[2];
                    s.Outline = Angle(n[0], n[1], n[2]);
                    return s;
                }
                return null;
            }

            // I / H sections: I h*b*tw*tf
            if ((p.StartsWith("I") || p.StartsWith("HE") || p.StartsWith("W")) && p.Contains("*"))
            {
                var n = Nums(new string(p.SkipWhile(c => !char.IsDigit(c)).ToArray()));
                if (n != null && n.Length >= 4)
                {
                    s.Kind = "I"; s.B = n[0]; s.H = n[1]; s.T = n[2];
                    s.Outline = IShape(n[0], n[1], n[2], n[3]);
                    return s;
                }
                return null;
            }

            // Tapered/eccentric round duct: EPD d1x*d1y*d2x*d2y*t  -> largest diameter
            if (p.StartsWith("EPD"))
            {
                var n = Nums(p.Substring(3));
                if (n != null && n.Length >= 5)
                {
                    double d = Math.Max(n[0], n[2]); double t = n[4];
                    s.Kind = "TUBE"; s.B = d; s.H = d; s.T = t;
                    s.Outline = Circle(d, 0, 0, true);
                    if (t > 0 && t < d / 2) s.Holes.Add(Circle(d - 2 * t, 0, 0, false, Segs(d)));
                    return s;
                }
                return null;
            }

            // Round tube: PD d*t  /  O d*t
            if (p.StartsWith("PD") || (p.StartsWith("O") && p.Contains("*")))
            {
                var n = Nums(p.Substring(p.StartsWith("PD") ? 2 : 1));
                if (n != null && n.Length >= 2)
                {
                    double d = n[0], t = Math.Min(n[1], n[0] / 2);
                    s.Kind = "TUBE"; s.B = d; s.H = d; s.T = t;
                    s.Outline = Circle(d, 0, 0, true);
                    if (t > 0 && t < d / 2 - 1e-9) s.Holes.Add(Circle(d - 2 * t, 0, 0, false, Segs(d)));
                    return s;
                }
                return null;
            }

            // Round bar: D d
            if (p.StartsWith("D") && !p.Contains("*"))
            {
                var n = Nums(p.Substring(1));
                if (n != null && n.Length >= 1 && n[0] > 0)
                {
                    s.Kind = "BAR"; s.B = n[0]; s.H = n[0];
                    s.Outline = Circle(n[0], 0, 0, true);
                    return s;
                }
                return null;
            }

            // Plate families. Note the two orderings Tekla uses:
            //   PL b*t, PLATE b*t, BL t          -> width first
            //   PLT t*b, FLT t*b                 -> thickness first
            string[] widthFirst = { "PLATE", "PL" };
            string[] thickFirst = { "PLT", "FLT", "FL", "BL" };

            foreach (var pre in new[] { "PLATE", "PLT", "FLT", "PL", "FL", "BL" })
            {
                if (!p.StartsWith(pre)) continue;
                var n = Nums(p.Substring(pre.Length));
                if (n == null || n.Length == 0) return null;
                bool tFirst = thickFirst.Contains(pre);

                if (n.Length == 1)
                {
                    // Contour plate / cut: only the thickness is known here.
                    s.Kind = "CONTOUR"; s.H = n[0]; s.B = 0;
                    return s;
                }
                double b = tFirst ? n[1] : n[0];
                double t = tFirst ? n[0] : n[1];
                s.Kind = "PLATE"; s.B = b; s.H = t; s.T = t;
                s.Outline = Rect(b, t);
                return s;
            }

            return null;
        }
    }
}
