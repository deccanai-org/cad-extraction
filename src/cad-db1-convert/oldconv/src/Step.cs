using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;

namespace Tek
{
    public class StepWriter
    {
        readonly StreamWriter w;
        int next = 1;

        int ctx, prodCtx, defCtx, appCtx;
        int rootAxisId;
        int rootDefId, rootShapeId;
        readonly List<int> styledItems = new List<int>();
        readonly Dictionary<string, int> styleCache = new Dictionary<string, int>();

        // Per-solid caches, reset for each solid so ids stay local and small.
        Dictionary<string, int> vmap;
        Dictionary<long, int[]> emap;   // key -> {edgeCurveId, vertexAId}

        static string F(double d)
        {
            if (Math.Abs(d) < 1e-11) d = 0;
            string s = d.ToString("0.###########", CultureInfo.InvariantCulture);
            return s.Contains(".") || s.Contains("E") ? s : s + ".";
        }
        static string Q(string s)
        {
            if (s == null) return "";
            var sb = new StringBuilder();
            foreach (char c in s)
            {
                if (c == '\'') sb.Append("''");
                else if (c >= 32 && c < 127) sb.Append(c);
                else sb.Append('_');
            }
            return sb.ToString();
        }

        int E(string body) { int id = next++; w.WriteLine("#" + id + "=" + body + ";"); return id; }

        public StepWriter(string path, string modelName, string author)
        {
            w = new StreamWriter(path, false, new UTF8Encoding(false));
            string ts = DateTime.Now.ToString("yyyy-MM-ddTHH:mm:ss");
            w.WriteLine("ISO-10303-21;");
            w.WriteLine("HEADER;");
            w.WriteLine("FILE_DESCRIPTION(('" + Q(modelName) + "'),'2;1');");
            w.WriteLine("FILE_NAME('" + Q(Path.GetFileName(path)) + "','" + ts + "',('" + Q(author) +
                        "'),(''),'Tekla model.dmp to STEP converter','',''); ");
            w.WriteLine("FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 3 1 1 }'));");
            w.WriteLine("ENDSEC;");
            w.WriteLine("DATA;");

            appCtx = E("APPLICATION_CONTEXT('automotive design')");
            E("APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2000,#" + appCtx + ")");
            prodCtx = E("PRODUCT_CONTEXT('',#" + appCtx + ",'mechanical')");
            defCtx = E("PRODUCT_DEFINITION_CONTEXT('part definition',#" + appCtx + ",'design')");

            int lu = E("(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.))");
            int au = E("(NAMED_UNIT(*)PLANE_ANGLE_UNIT()SI_UNIT($,.RADIAN.))");
            int su = E("(NAMED_UNIT(*)SI_UNIT($,.STERADIAN.)SOLID_ANGLE_UNIT())");
            int un = E("UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-05),#" + lu + ",'distance_accuracy_value','confusion accuracy')");
            ctx = E("(GEOMETRIC_REPRESENTATION_CONTEXT(3)GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#" + un +
                    "))GLOBAL_UNIT_ASSIGNED_CONTEXT((#" + lu + ",#" + au + ",#" + su + "))REPRESENTATION_CONTEXT('Context','3D'))");

            rootAxisId = Axis(new V3(0, 0, 0));

            int p = E("PRODUCT('" + Q(modelName) + "','" + Q(modelName) + "','',(#" + prodCtx + "))");
            E("PRODUCT_RELATED_PRODUCT_CATEGORY('part','',(#" + p + "))");
            int pdf = E("PRODUCT_DEFINITION_FORMATION('','',#" + p + ")");
            rootDefId = E("PRODUCT_DEFINITION('design','',#" + pdf + ",#" + defCtx + ")");
            int pds = E("PRODUCT_DEFINITION_SHAPE('','',#" + rootDefId + ")");
            rootShapeId = E("SHAPE_REPRESENTATION('" + Q(modelName) + "',(#" + rootAxisId + "),#" + ctx + ")");
            E("SHAPE_DEFINITION_REPRESENTATION(#" + pds + ",#" + rootShapeId + ")");
        }

        int Pt(V3 v) { return E("CARTESIAN_POINT('',(" + F(v.X) + "," + F(v.Y) + "," + F(v.Z) + "))"); }
        int Dir(V3 v) { return E("DIRECTION('',(" + F(v.X) + "," + F(v.Y) + "," + F(v.Z) + "))"); }

        int Axis(V3 o)
        {
            int p = Pt(o);
            int z = Dir(new V3(0, 0, 1));
            int x = Dir(new V3(1, 0, 0));
            return E("AXIS2_PLACEMENT_3D('',#" + p + ",#" + z + ",#" + x + ")");
        }

        int Axis(V3 o, V3 zd, V3 xd)
        {
            int p = Pt(o);
            int z = Dir(zd);
            int x = Dir(xd);
            return E("AXIS2_PLACEMENT_3D('',#" + p + ",#" + z + ",#" + x + ")");
        }

        int Vertex(V3 v)
        {
            string k = Math.Round(v.X, 5).ToString("F5", CultureInfo.InvariantCulture) + "|" +
                       Math.Round(v.Y, 5).ToString("F5", CultureInfo.InvariantCulture) + "|" +
                       Math.Round(v.Z, 5).ToString("F5", CultureInfo.InvariantCulture);
            int id;
            if (vmap.TryGetValue(k, out id)) return id;
            id = E("VERTEX_POINT('',#" + Pt(v) + ")");
            vmap[k] = id;
            return id;
        }

        // Returns the oriented edge for a -> b, sharing the underlying edge_curve.
        int OrientedEdge(V3 a, V3 b)
        {
            int va = Vertex(a), vb = Vertex(b);
            bool fwd = va <= vb;
            long key = fwd ? ((long)va << 32) | (uint)vb : ((long)vb << 32) | (uint)va;
            int[] e;
            if (!emap.TryGetValue(key, out e))
            {
                V3 p0 = fwd ? a : b, p1 = fwd ? b : a;
                V3 d = (p1 - p0).Unit;
                int dirId = Dir(d);
                int vec = E("VECTOR('',#" + dirId + "," + F(1) + ")");
                int line = E("LINE('',#" + Pt(p0) + ",#" + vec + ")");
                int ec = E("EDGE_CURVE('',#" + (fwd ? va : vb) + ",#" + (fwd ? vb : va) + ",#" + line + ",.T.)");
                e = new[] { ec };
                emap[key] = e;
            }
            return E("ORIENTED_EDGE('',*,*,#" + e[0] + "," + (fwd ? ".T." : ".F.") + ")");
        }

        int Loop(List<V3> pts)
        {
            var oe = new List<int>();
            for (int i = 0; i < pts.Count; i++)
            {
                V3 a = pts[i], b = pts[(i + 1) % pts.Count];
                if ((b - a).Len < 1e-7) continue;
                oe.Add(OrientedEdge(a, b));
            }
            if (oe.Count < 3) return 0;
            var sb = new StringBuilder("EDGE_LOOP('',(");
            for (int i = 0; i < oe.Count; i++) { if (i > 0) sb.Append(','); sb.Append('#').Append(oe[i]); }
            sb.Append("))");
            return E(sb.ToString());
        }

        int FaceOf(Face f)
        {
            V3 n = f.Normal();
            if (n.Len < 0.5) return 0;
            int outer = Loop(f.Outer);
            if (outer == 0) return 0;

            var bounds = new List<int> { E("FACE_OUTER_BOUND('',#" + outer + ",.T.)") };
            foreach (var inn in f.Inner)
            {
                int l = Loop(inn);
                if (l != 0) bounds.Add(E("FACE_BOUND('',#" + l + ",.T.)"));
            }

            V3 refDir = Math.Abs(n.X) < 0.9 ? new V3(1, 0, 0) : new V3(0, 1, 0);
            refDir = (refDir - n * n.Dot(refDir)).Unit;
            int pl = E("PLANE('',#" + Axis(f.Outer[0], n, refDir) + ")");

            var sb = new StringBuilder("ADVANCED_FACE('',(");
            for (int i = 0; i < bounds.Count; i++) { if (i > 0) sb.Append(','); sb.Append('#').Append(bounds[i]); }
            sb.Append("),#").Append(pl).Append(",.T.)");
            return E(sb.ToString());
        }

        int StyleFor(double r, double g, double b)
        {
            string k = r + "/" + g + "/" + b;
            int id;
            if (styleCache.TryGetValue(k, out id)) return id;
            int col = E("COLOUR_RGB('',", r, g, b);
            int fac = E("FILL_AREA_STYLE_COLOUR('',#" + col + ")");
            int fas = E("FILL_AREA_STYLE('',(#" + fac + "))");
            int ssf = E("SURFACE_STYLE_FILL_AREA(#" + fas + ")");
            int sss = E("SURFACE_SIDE_STYLE('',(#" + ssf + "))");
            int ssu = E("SURFACE_STYLE_USAGE(.BOTH.,#" + sss + ")");
            id = E("PRESENTATION_STYLE_ASSIGNMENT((#" + ssu + "))");
            styleCache[k] = id;
            return id;
        }
        int E(string prefix, double r, double g, double b)
        {
            return E(prefix + F(r) + "," + F(g) + "," + F(b) + ")");
        }

        /// Adds one part as a child product of the root, with its own solid.
        public void AddPart(string name, List<Solid> solids, double[] rgb)
        {
            vmap = new Dictionary<string, int>();
            emap = new Dictionary<long, int[]>();

            var breps = new List<int>();
            foreach (var s in solids)
            {
                var faces = new List<int>();
                foreach (var f in s.Faces)
                {
                    int fid = FaceOf(f);
                    if (fid != 0) faces.Add(fid);
                }
                if (faces.Count < 4) continue;
                var sb = new StringBuilder("CLOSED_SHELL('',(");
                for (int i = 0; i < faces.Count; i++) { if (i > 0) sb.Append(','); sb.Append('#').Append(faces[i]); }
                sb.Append("))");
                int shell = E(sb.ToString());
                breps.Add(E("MANIFOLD_SOLID_BREP('" + Q(name) + "',#" + shell + ")"));
            }
            if (breps.Count == 0) return;

            int axis = Axis(new V3(0, 0, 0));
            int prod = E("PRODUCT('" + Q(name) + "','" + Q(name) + "','',(#" + prodCtx + "))");
            E("PRODUCT_RELATED_PRODUCT_CATEGORY('part','',(#" + prod + "))");
            int pdf = E("PRODUCT_DEFINITION_FORMATION('','',#" + prod + ")");
            int pd = E("PRODUCT_DEFINITION('design','',#" + pdf + ",#" + defCtx + ")");
            int pds = E("PRODUCT_DEFINITION_SHAPE('','',#" + pd + ")");

            var items = new StringBuilder("#" + axis);
            foreach (var b in breps) items.Append(",#").Append(b);
            int shape = E("ADVANCED_BREP_SHAPE_REPRESENTATION('" + Q(name) + "',(" + items + "),#" + ctx + ")");
            E("SHAPE_DEFINITION_REPRESENTATION(#" + pds + ",#" + shape + ")");

            // Hang the part off the root assembly with an identity transform.
            int nauo = E("NEXT_ASSEMBLY_USAGE_OCCURRENCE('" + Q(name) + "','" + Q(name) + "','',#" +
                         rootDefId + ",#" + pd + ",$)");
            int npds = E("PRODUCT_DEFINITION_SHAPE('','',#" + nauo + ")");
            int idt = E("ITEM_DEFINED_TRANSFORMATION('','',#" + rootAxisId + ",#" + axis + ")");
            int rr = E("(REPRESENTATION_RELATIONSHIP('','',#" + shape + ",#" + rootShapeId +
                       ")REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION(#" + idt +
                       ")SHAPE_REPRESENTATION_RELATIONSHIP())");
            E("CONTEXT_DEPENDENT_SHAPE_REPRESENTATION(#" + rr + ",#" + npds + ")");

            if (rgb != null)
            {
                int psa = StyleFor(rgb[0], rgb[1], rgb[2]);
                foreach (var b in breps)
                    styledItems.Add(E("STYLED_ITEM('color',(#" + psa + "),#" + b + ")"));
            }
        }

        public void Close()
        {
            if (styledItems.Count > 0)
            {
                // Emit in chunks; a single list of 100k+ refs upsets some readers.
                const int chunk = 2000;
                for (int i = 0; i < styledItems.Count; i += chunk)
                {
                    var sb = new StringBuilder("MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION('',(");
                    int n = 0;
                    for (int j = i; j < Math.Min(i + chunk, styledItems.Count); j++)
                    {
                        if (n++ > 0) sb.Append(',');
                        sb.Append('#').Append(styledItems[j]);
                    }
                    sb.Append("),#").Append(ctx).Append(")");
                    E(sb.ToString());
                }
            }
            w.WriteLine("ENDSEC;");
            w.WriteLine("END-ISO-10303-21;");
            w.Flush();
            w.Close();
        }
    }
}
