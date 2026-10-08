using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;

namespace Tek
{
    class PartRec
    {
        public int Id;
        public Row P, A;
        public V3 O, Ex, Ey, Ez;
        public double Len;
        public string Prof, Mat, Ben, Name, AsmMark = "", PartMark = "";
        public int ObjType;
        public bool IsCut, IsBolt;
        public V3? P1, P2;
        public List<double[]> Poly;
        public List<Solid> Sols = new List<Solid>();
        public double Vol, VolRaw;
        public double PathLen;           // extruded / swept length, for the kg-per-metre check
        public string Path = "";
        public Solid Sol { get { return Sols.Count == 1 ? Sols[0] : null; } }
    }

    public class ProfileStat
    {
        public int Count;
        public double LengthMm;      // only accumulated for members with a real cross-section
        public double GrossKg, NetKg;
        public double KgPerM { get { return LengthMm > 1 ? GrossKg / (LengthMm / 1000.0) : 0; } }
    }

    public class ConvertResult
    {
        public bool Ok;
        public string Error = "";
        public string ModelName = "", DumpPath = "", StepPath = "";
        public int Parts, Straight, Curved, Plates, PolyBeams, BoltGroups, Bolts, FailedSolids, SolidsWritten;
        public int CutsLinked, CutsApplied, CutsNoEffect, CutsRejected;
        public double SteelKg, BoltKg;
        public double[] BBoxMin = new double[3], BBoxMax = new double[3];
        public Dictionary<string, ProfileStat> ByProfile = new Dictionary<string, ProfileStat>();
        public double Seconds;
        public long StepBytes;
        public List<string> Warnings = new List<string>();
    }

    public static class Converter
    {
        public const double Density = 7.85e-6;   // kg per mm^3

        public static ConvertResult Convert(string dmp, string outStep, string outReport,
                                            string outCsv, string modelName, bool withBolts)
        {
            return Convert(Dump.Parse(dmp), dmp, outStep, outReport, outCsv, modelName, withBolts);
        }

        /// Same pipeline, but from an already-loaded model. Lets the .db1 reader feed the
        /// converter directly, since it produces the same table shape as the ASCII dump.
        public static ConvertResult Convert(Dump dump, string sourceLabel, string outStep,
                                            string outReport, string outCsv, string modelName, bool withBolts)
        {
            string dmp = sourceLabel;
            var res = new ConvertResult { ModelName = modelName, DumpPath = dmp, StepPath = outStep };
            var clock = System.Diagnostics.Stopwatch.StartNew();
            var log = new StringBuilder();

            if (dump.T("part").Count == 0)
            {
                res.Error = "no part table in dump";
                return res;
            }

            var attrs = Dump.Index(dump.T("part_attr"), "id");
            var csa = Dump.Index(dump.T("coordsys_attr"), "id");
            var objs = Dump.Index(dump.T("object"), "id");
            var asms = Dump.Index(dump.T("assembly"), "id");
            var pts = Dump.Index(dump.T("point"), "id");

            var polyRows = new Dictionary<int, List<Row>>();
            foreach (var r in dump.T("partpolygon"))
            {
                int id = r.I("id");
                List<Row> l;
                if (!polyRows.TryGetValue(id, out l)) { l = new List<Row>(); polyRows[id] = l; }
                l.Add(r);
            }

            var recs = new Dictionary<int, PartRec>();
            foreach (var p in dump.T("part"))
            {
                Row a; if (!attrs.TryGetValue(p.I("part_attr_id"), out a)) continue;
                Row c; if (!csa.TryGetValue(p.I("csys_attr_id"), out c)) continue;

                var r = new PartRec();
                r.Id = p.I("id"); r.P = p; r.A = a;
                r.O = new V3(p.D("csys_x"), p.D("csys_y"), p.D("csys_z"));
                r.Ex = new V3(c.D("xdir_x"), c.D("xdir_y"), c.D("xdir_z")).Unit;
                r.Ey = new V3(c.D("ydir_x"), c.D("ydir_y"), c.D("ydir_z")).Unit;
                r.Ez = r.Ex.Cross(r.Ey).Unit;
                r.Len = p.D("csys_length");
                r.Prof = a.S("prof"); r.Mat = a.S("mat"); r.Ben = a.S("ben");
                r.ObjType = a.I("obj_type");
                r.IsCut = r.Mat == "ANTIMATERIAL";
                r.IsBolt = r.ObjType == 10 && !r.IsCut;
                Row w1, w2;
                if (pts.TryGetValue(p.I("p1"), out w1)) r.P1 = new V3(w1.D("x"), w1.D("y"), w1.D("z"));
                if (pts.TryGetValue(p.I("p2"), out w2)) r.P2 = new V3(w2.D("x"), w2.D("y"), w2.D("z"));

                int npts = a.I("npoints");
                int pid = p.I("polygon_id");
                if (pid != 0 && npts > 0 && polyRows.ContainsKey(pid))
                {
                    var raw = new List<double[]>();
                    foreach (var pr in polyRows[pid].OrderBy(x => x.I("no")))
                        for (int i = 1; i <= 10 && raw.Count < npts; i++)
                            raw.Add(new[] { pr.D("x" + i), pr.D("y" + i), pr.D("z" + i) });
                    Func<double[], double[], bool> same = (u, v) =>
                        Math.Abs(u[0] - v[0]) < 1e-7 && Math.Abs(u[1] - v[1]) < 1e-7 && Math.Abs(u[2] - v[2]) < 1e-7;
                    var cl = new List<double[]>();
                    foreach (var q in raw)
                        if (cl.Count == 0 || !same(cl[cl.Count - 1], q)) cl.Add(q);
                    if (cl.Count > 1 && same(cl[0], cl[cl.Count - 1])) cl.RemoveAt(cl.Count - 1);
                    r.Poly = cl;
                }

                string asmMark = "";
                Row o;
                if (objs.TryGetValue(r.Id, out o))
                {
                    Row asm;
                    if (asms.TryGetValue(o.I("assembly"), out asm))
                        asmMark = (asm.S("pos") + asm.I("fpos")).Trim();
                }
                string partMark = (p.S("pos") + (p.I("fpos") > 0 ? p.I("fpos").ToString() : "")).Trim();
                r.AsmMark = asmMark; r.PartMark = partMark;
                var nm = new List<string>();
                if (asmMark.Length > 0 && asmMark != "0") nm.Add(asmMark);
                if (partMark.Length > 0 && partMark != "0") nm.Add(partMark);
                nm.Add(string.IsNullOrEmpty(r.Ben) ? "PART" : r.Ben);
                nm.Add(r.Prof);
                nm.Add(r.Mat);
                r.Name = string.Join(" ", nm) + " [" + r.Id + "]";

                recs[r.Id] = r;
            }
            res.Parts = recs.Count;

            // A circular platform wrapped round a vertical vessel is the one case where
            // the dump's missing curved-beam data can be recovered: the arc centre is the
            // shell axis. Only engages when such a shell is actually present.
            var shellXY = new List<double[]>();
            foreach (var r in recs.Values)
            {
                var sec = Profiles.Parse(r.Prof);
                if (sec != null && sec.Kind == "TUBE" && sec.B > 500 && Math.Abs(r.Ex.Z) > 0.99)
                    shellXY.Add(new[] { r.O.X, r.O.Y });
            }
            bool haveAxis = shellXY.Count > 0;
            double axX = haveAxis ? shellXY.Average(v => v[0]) : 0;
            double axY = haveAxis ? shellXY.Average(v => v[1]) : 0;
            var curvedLog = new List<string>();

            int nStraight = 0, nPoly = 0, nBoltGrp = 0, nBolts = 0, nFail = 0, nCurved = 0, nPolyBeam = 0;
            var failures = new List<string>();
            foreach (var r in recs.Values)
            {
                try
                {
                    if (r.IsBolt)
                    {
                        r.Path = "bolt";
                        if (withBolts) { r.Sols = BuildBolt(r, ref nBolts); nBoltGrp++; }
                    }
                    else
                    {
                        Solid pb = (r.Poly != null && r.Poly.Count >= 2 && r.A.I("form_type") == 4)
                                   ? BuildPolyBeam(r) : null;
                        if (pb != null) { r.Path = "polybeam"; Add1(r, pb); nPolyBeam++; }
                        else if (r.Poly != null && r.Poly.Count >= 3) { r.Path = "plate"; Add1(r, BuildPolyPlate(r)); nPoly++; }
                        else
                        {
                            Solid curved = haveAxis ? BuildCurved(r, axX, axY, curvedLog) : null;
                            if (curved != null) { r.Path = "curved"; Add1(r, curved); nCurved++; }
                            else { r.Path = "straight"; Add1(r, BuildStraight(r)); nStraight++; r.PathLen = r.Len; }
                        }
                    }
                }
                catch (Exception ex) { failures.Add(r.Id + " " + r.Prof + ": " + ex.Message); }
                r.Sols = r.Sols.Where(s => s != null && s.Faces.Count >= 4).ToList();
                if (r.Sols.Count == 0 && (!r.IsBolt || withBolts))
                {
                    nFail++;
                    if (failures.Count < 40) failures.Add(r.Id + " " + r.Prof + " " + r.Ben + " (no solid)");
                }
            }

            foreach (var r in recs.Values)
                if (!r.IsCut) r.VolRaw = r.Sols.Sum(s => Math.Abs(Geom.Volume(Geom.ToPolys(s))));

            var cutsFor = new Dictionary<int, List<int>>();
            foreach (var rel in dump.T("relation"))
            {
                if (rel.I("type") != 11) continue;
                int parent = rel.I("id1"), child = rel.I("id2");
                PartRec cr;
                if (!recs.TryGetValue(child, out cr) || !cr.IsCut) continue;
                if (!recs.ContainsKey(parent)) continue;
                List<int> l;
                if (!cutsFor.TryGetValue(parent, out l)) { l = new List<int>(); cutsFor[parent] = l; }
                l.Add(child);
            }

            int cutsApplied = 0, cutsNoEffect = 0, cutsFailed = 0;
            foreach (var kv in cutsFor)
            {
                PartRec par = recs[kv.Key];
                if (par.Sol == null) continue;
                var polys = Geom.ToPolys(par.Sol);
                double v0 = Math.Abs(Geom.Volume(polys));
                foreach (int cid in kv.Value)
                {
                    var cut = recs[cid];
                    if (cut.Sol == null) { cutsFailed++; continue; }
                    try
                    {
                        var r2 = Bsp.Subtract(polys, Geom.ToPolys(cut.Sol));
                        double v1 = Math.Abs(Geom.Volume(r2));
                        if (r2.Count < 4 || v1 <= 1e-6 || v1 > v0 * 1.05) { cutsFailed++; continue; }
                        if (v0 - v1 < v0 * 1e-4) cutsNoEffect++; else cutsApplied++;
                        polys = r2;
                        v0 = v1;
                    }
                    catch { cutsFailed++; }
                }
                par.Sols = new List<Solid> { Geom.FromPolys(polys) };
            }

            double totVol = 0, steelVol = 0, boltVol = 0;
            var bbMin = new V3(1e18, 1e18, 1e18); var bbMax = new V3(-1e18, -1e18, -1e18);

            foreach (var r in recs.Values)
            {
                if (r.IsCut || r.Sols.Count == 0) continue;
                r.Vol = r.Sols.Sum(s => Math.Abs(Geom.Volume(Geom.ToPolys(s))));
                totVol += r.Vol;
                if (r.IsBolt) boltVol += r.Vol; else steelVol += r.Vol;

                ProfileStat st;
                if (!res.ByProfile.TryGetValue(r.Prof, out st)) { st = new ProfileStat(); res.ByProfile[r.Prof] = st; }
                st.Count++;
                st.NetKg += r.Vol * Density;
                st.GrossKg += r.VolRaw * Density;
                st.LengthMm += r.PathLen;

                foreach (var s in r.Sols)
                    foreach (var f in s.Faces)
                        foreach (var v in f.Outer)
                        {
                            bbMin = new V3(Math.Min(bbMin.X, v.X), Math.Min(bbMin.Y, v.Y), Math.Min(bbMin.Z, v.Z));
                            bbMax = new V3(Math.Max(bbMax.X, v.X), Math.Max(bbMax.Y, v.Y), Math.Max(bbMax.Z, v.Z));
                        }
            }

            var sw = new StepWriter(outStep, modelName, "Tekla Structures model dump");
            int written = 0;
            foreach (var r in recs.Values.OrderBy(x => x.Name, StringComparer.Ordinal))
            {
                if (r.IsCut || r.Sols.Count == 0) continue;
                double[] rgb = r.IsBolt ? new[] { 0.25, 0.25, 0.28 }
                             : r.Mat == "SA53-B" ? new[] { 0.55, 0.60, 0.66 }
                             : new[] { 0.70, 0.72, 0.75 };
                sw.AddPart(r.Name, r.Sols, rgb);
                written++;
            }
            sw.Close();

            res.Straight = nStraight; res.Curved = nCurved; res.Plates = nPoly;
            res.PolyBeams = nPolyBeam; res.BoltGroups = nBoltGrp; res.Bolts = nBolts;
            res.FailedSolids = nFail; res.SolidsWritten = written;
            res.CutsLinked = cutsFor.Values.Sum(l => l.Count);
            res.CutsApplied = cutsApplied; res.CutsNoEffect = cutsNoEffect; res.CutsRejected = cutsFailed;
            res.SteelKg = steelVol * Density; res.BoltKg = boltVol * Density;
            res.BBoxMin = new[] { bbMin.X, bbMin.Y, bbMin.Z };
            res.BBoxMax = new[] { bbMax.X, bbMax.Y, bbMax.Z };
            res.StepBytes = new FileInfo(outStep).Length;

            log.AppendLine("Tekla model dump -> STEP");
            log.AppendLine("model  : " + modelName);
            log.AppendLine("source : " + dmp);
            log.AppendLine("output : " + outStep);
            log.AppendLine();
            log.AppendLine("parts in database        : " + recs.Count);
            log.AppendLine("  straight members       : " + nStraight);
            log.AppendLine("  curved members (arcs)  : " + nCurved);
            log.AppendLine("  polygon plates / cuts  : " + nPoly);
            log.AppendLine("  swept polybeams        : " + nPolyBeam);
            log.AppendLine("  bolt groups            : " + nBoltGrp + "  (" + nBolts + " individual bolts)");
            log.AppendLine("  solids that failed     : " + nFail);
            log.AppendLine();
            log.AppendLine("cuts linked (relation 11): " + res.CutsLinked);
            log.AppendLine("  applied, removed metal : " + cutsApplied);
            log.AppendLine("  applied, no effect     : " + cutsNoEffect);
            log.AppendLine("  rejected               : " + cutsFailed);
            log.AppendLine();
            log.AppendLine("bounding box (mm)");
            log.AppendLine("  X " + bbMin.X.ToString("F0") + " .. " + bbMax.X.ToString("F0"));
            log.AppendLine("  Y " + bbMin.Y.ToString("F0") + " .. " + bbMax.Y.ToString("F0"));
            log.AppendLine("  Z " + bbMin.Z.ToString("F0") + " .. " + bbMax.Z.ToString("F0"));
            log.AppendLine();
            log.AppendLine("mass at 7850 kg/m3:  steel " + res.SteelKg.ToString("F1") +
                           " kg   bolts " + res.BoltKg.ToString("F1") + " kg");
            log.AppendLine();
            log.AppendLine("by profile   (gross = before cuts, net = after cuts)");
            log.AppendLine("count".PadLeft(6) + "  " + "gross kg".PadLeft(10) + "  " + "net kg".PadLeft(10) + "  " + "kg/m".PadLeft(8) + "  profile");
            foreach (var kv in res.ByProfile.OrderByDescending(k => k.Value.NetKg))
                log.AppendLine(kv.Value.Count.ToString().PadLeft(6) + "  " +
                               kv.Value.GrossKg.ToString("F1").PadLeft(10) + "  " +
                               kv.Value.NetKg.ToString("F1").PadLeft(10) + "  " +
                               (kv.Value.KgPerM > 0 ? kv.Value.KgPerM.ToString("F2") : "-").PadLeft(8) + "  " + kv.Key);
            if (curvedLog.Count > 0)
            {
                log.AppendLine();
                log.AppendLine("curved members rebuilt as arcs about (" + axX.ToString("F1") + ", " + axY.ToString("F1") + ")");
                foreach (var l in curvedLog.OrderBy(x => x)) log.AppendLine(l);
            }
            if (failures.Count > 0)
            {
                log.AppendLine();
                log.AppendLine("issues:");
                foreach (var f in failures) log.AppendLine("  " + f);
                res.Warnings.AddRange(failures.Take(10));
            }
            log.AppendLine();
            log.AppendLine("solids written to STEP   : " + written);

            File.WriteAllText(outReport, log.ToString());

            var csv = new StringBuilder();
            csv.AppendLine("part_id,assembly_mark,part_mark,name,profile,material,obj_type,form_type,build_path,length_mm,gross_kg,net_kg,solids");
            foreach (var r in recs.Values.Where(x => !x.IsCut).OrderBy(x => x.Prof, StringComparer.Ordinal).ThenBy(x => x.Id))
                csv.AppendLine(string.Join(",", new[]{
                    r.Id.ToString(), Csv(r.AsmMark), Csv(r.PartMark), Csv(r.Ben), Csv(r.Prof), Csv(r.Mat),
                    r.ObjType.ToString(), r.A.S("form_type"), r.Path,
                    r.Len.ToString("F1",CultureInfo.InvariantCulture),
                    (r.VolRaw*Density).ToString("F2",CultureInfo.InvariantCulture),
                    (r.Vol*Density).ToString("F2",CultureInfo.InvariantCulture),
                    r.Sols.Count.ToString()}));
            File.WriteAllText(outCsv, csv.ToString());

            clock.Stop();
            res.Seconds = clock.Elapsed.TotalSeconds;
            res.Ok = written > 0;
            if (!res.Ok) res.Error = "no solids written";
            return res;
        }

        static Solid BuildStraight(PartRec r)
        {
            if (r.Len < 1e-3) return null;
            var sec = Profiles.Parse(r.Prof);
            if (sec == null || !sec.Ok) return null;
            return Geom.Extrude(sec.Outline, sec.Holes, r.O, r.Ex, r.Ey, r.Ez, 0, r.Len);
        }

        const double MinSagitta = 120.0;
        const double MaxRadiusDiff = 3.0;

        static Solid BuildCurved(PartRec r, double axX, double axY, List<string> logLines)
        {
            if (r.Len < 200) return null;
            var sec = Profiles.Parse(r.Prof);
            if (sec == null || !sec.Ok) return null;
            if (Math.Abs(r.Ex.Z) > 0.09) return null;

            V3 e = r.O + r.Ex * r.Len;
            double r1 = Math.Sqrt(Sq(r.O.X - axX) + Sq(r.O.Y - axY));
            double r2 = Math.Sqrt(Sq(e.X - axX) + Sq(e.Y - axY));
            if (Math.Abs(r1 - r2) > MaxRadiusDiff || r1 < 100) return null;

            double R = (r1 + r2) / 2;
            double mx = (r.O.X + e.X) / 2, my = (r.O.Y + e.Y) / 2;
            double sag = R - Math.Sqrt(Sq(mx - axX) + Sq(my - axY));
            if (sag < MinSagitta) return null;

            double a0 = Math.Atan2(r.O.Y - axY, r.O.X - axX);
            double a1 = Math.Atan2(e.Y - axY, e.X - axX);
            double d = a1 - a0;
            while (d > Math.PI) d -= 2 * Math.PI;
            while (d < -Math.PI) d += 2 * Math.PI;

            int n = Math.Max(8, (int)Math.Ceiling(Math.Abs(d) / (5 * Math.PI / 180)));
            var stations = new List<Geom.Frame>();
            for (int i = 0; i <= n; i++)
            {
                double ang = d * i / n;
                double turn = ang - d / 2;   // section is square to the chord, not the tangent
                stations.Add(new Geom.Frame
                {
                    O = RotZ(r.O, axX, axY, ang),
                    Eu = RotZ(r.Ey, turn),
                    Ev = RotZ(r.Ez, turn)
                });
            }
            r.PathLen = R * Math.Abs(d);

            var sol = Geom.Sweep(sec.Outline, sec.Holes, stations);
            double area = Math.Abs(Shoelace(sec.Outline));
            foreach (var h in sec.Holes) area -= Math.Abs(Shoelace(h));
            double expect = area * R * Math.Abs(d);
            double actual = Math.Abs(Geom.Volume(Geom.ToPolys(sol)));
            logLines.Add("  " + r.Id + "  " + r.Prof.PadRight(16) + (r.Ben ?? "").PadRight(12) +
                         " R=" + R.ToString("F0").PadLeft(6) + "  sweep=" + (Math.Abs(d) * 180 / Math.PI).ToString("F1").PadLeft(6) +
                         " deg  chord=" + r.Len.ToString("F1").PadLeft(8) + "  arc=" + (R * Math.Abs(d)).ToString("F1").PadLeft(8) +
                         "  vol/expected=" + (expect > 0 ? (actual / expect).ToString("F4") : "-"));
            return sol;
        }

        static double Sq(double v) { return v * v; }
        static double Shoelace(List<double[]> p)
        {
            double a = 0;
            for (int i = 0; i < p.Count; i++) { var u = p[i]; var v = p[(i + 1) % p.Count]; a += u[0] * v[1] - v[0] * u[1]; }
            return a / 2;
        }
        static V3 RotZ(V3 v, double a)
        {
            double c = Math.Cos(a), s = Math.Sin(a);
            return new V3(v.X * c - v.Y * s, v.X * s + v.Y * c, v.Z);
        }
        static V3 RotZ(V3 p, double cx, double cy, double a)
        {
            double c = Math.Cos(a), s = Math.Sin(a);
            double dx = p.X - cx, dy = p.Y - cy;
            return new V3(cx + dx * c - dy * s, cy + dx * s + dy * c, p.Z);
        }

        static Solid BuildPolyBeam(PartRec r)
        {
            var sec = Profiles.Parse(r.Prof);
            if (sec == null || !sec.Ok) return null;
            if (r.P1 == null || r.P2 == null) return null;
            V3 target = r.P2.Value - r.P1.Value;
            if (target.Len < 1e-6) return null;

            var axes = new[] { r.Ex, r.Ey, r.Ez };
            int[][] perms = {
                new[]{0,1,2}, new[]{1,2,0}, new[]{2,0,1},
                new[]{0,2,1}, new[]{1,0,2}, new[]{2,1,0}
            };
            int[] use = null;
            double bestErr = double.MaxValue;
            var d0 = new[] { r.Poly[1][0] - r.Poly[0][0], r.Poly[1][1] - r.Poly[0][1], r.Poly[1][2] - r.Poly[0][2] };
            foreach (var pm in perms)
            {
                V3 v = axes[pm[0]] * d0[0] + axes[pm[1]] * d0[1] + axes[pm[2]] * d0[2];
                double err = (v - target).Len;
                if (err < bestErr) { bestErr = err; use = pm; }
            }
            if (use == null || bestErr > 5.0) return null;

            var p = r.Poly.Select(q => r.O + axes[use[0]] * q[0] + axes[use[1]] * q[1] + axes[use[2]] * q[2]).ToList();
            var path = new List<V3>();
            foreach (var q in p) if (path.Count == 0 || (q - path[path.Count - 1]).Len > 1e-4) path.Add(q);
            if (path.Count < 2) return null;

            var tan = new List<V3>();
            for (int i = 0; i + 1 < path.Count; i++) tan.Add((path[i + 1] - path[i]).Unit);
            double plen = 0;
            for (int i = 0; i + 1 < path.Count; i++) plen += (path[i + 1] - path[i]).Len;
            r.PathLen = plen;

            var normals = new List<V3>();
            for (int i = 0; i < path.Count; i++)
            {
                V3 n;
                if (i == 0) n = tan[0];
                else if (i == path.Count - 1) n = tan[tan.Count - 1];
                else { n = (tan[i - 1] + tan[i]); n = n.Len < 1e-9 ? tan[i] : n.Unit; }
                normals.Add(n);
            }

            V3 eu = r.Ey - normals[0] * normals[0].Dot(r.Ey);
            if (eu.Len < 1e-6) eu = r.Ez - normals[0] * normals[0].Dot(r.Ez);
            if (eu.Len < 1e-6) eu = new V3(1, 0, 0) - normals[0] * normals[0].Dot(new V3(1, 0, 0));
            eu = eu.Unit;

            var stations = new List<Geom.Frame>();
            for (int i = 0; i < path.Count; i++)
            {
                V3 n = normals[i];
                V3 u = eu - n * n.Dot(eu);
                if (u.Len < 1e-6) continue;
                u = u.Unit;
                eu = u;
                stations.Add(new Geom.Frame { O = path[i], Eu = u, Ev = n.Cross(u) });
            }
            if (stations.Count < 2) return null;
            return Geom.Sweep(sec.Outline, sec.Holes, stations);
        }

        static Solid BuildPolyPlate(PartRec r)
        {
            double t = Profiles.PlateThickness(r.Prof);
            if (t < 1e-3) return null;

            bool useZ = r.A.I("form_type") == 2;
            var p3 = r.Poly.Select(q => r.O + r.Ex * q[0] + r.Ey * q[1] + r.Ez * (useZ ? q[2] : 0)).ToList();
            V3 n = Geom.Newell(p3);
            if (n.Len < 0.5) { n = r.Ez; p3 = r.Poly.Select(q => r.O + r.Ex * q[0] + r.Ey * q[1]).ToList(); }

            V3 eu = Math.Abs(n.X) < 0.9 ? new V3(1, 0, 0) : new V3(0, 1, 0);
            eu = (eu - n * n.Dot(eu)).Unit;
            V3 ev = n.Cross(eu);
            double d = p3.Average(q => q.Dot(n));

            var flat = p3.Select(q => new[] { q.Dot(eu), q.Dot(ev) }).ToList();
            return Geom.Extrude(flat, null, n * d, n, eu, ev, -t / 2, t / 2);
        }

        static string Csv(string s)
        {
            if (s == null) return "";
            return s.IndexOfAny(new[] { ',', '"', '\n' }) >= 0 ? "\"" + s.Replace("\"", "\"\"") + "\"" : s;
        }

        static void Add1(PartRec r, Solid s) { if (s != null) r.Sols.Add(s); }

        static List<Solid> BuildBolt(PartRec r, ref int count)
        {
            var outp = new List<Solid>();
            double d, L;
            if (!Profiles.BoltDims(r.Prof, out d, out L)) return outp;
            var positions = r.Poly != null && r.Poly.Count > 0 ? r.Poly : new List<double[]> { new double[] { 0, 0, 0 } };

            double headH = 0.65 * d, nutH = 0.80 * d;
            double af = 1.6 * d, R = af / Math.Sqrt(3.0);
            var hex = new List<double[]>();
            for (int i = 0; i < 6; i++)
            {
                double ang = Math.PI / 6 + i * Math.PI / 3;
                hex.Add(new[] { R * Math.Cos(ang), R * Math.Sin(ang) });
            }
            var shaft = Profiles.Circle(d, 0, 0, true, 12);

            foreach (var pos in positions)
            {
                V3 c = r.O + r.Ex * pos[0] + r.Ey * pos[1] + r.Ez * (pos.Length > 2 ? pos[2] : 0);
                outp.Add(Geom.Extrude(shaft, null, c, r.Ez, r.Ex, r.Ey, -L / 2, L / 2));
                outp.Add(Geom.Extrude(hex, null, c, r.Ez, r.Ex, r.Ey, -L / 2 - headH, -L / 2));
                outp.Add(Geom.Extrude(hex, null, c, r.Ez, r.Ex, r.Ey, L / 2, L / 2 + nutH));
                count++;
            }
            return outp;
        }
    }
}
