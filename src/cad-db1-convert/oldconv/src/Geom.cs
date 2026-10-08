using System;
using System.Collections.Generic;
using System.Linq;

namespace Tek
{
    public struct V3
    {
        public double X, Y, Z;
        public V3(double x, double y, double z) { X = x; Y = y; Z = z; }
        public static V3 operator +(V3 a, V3 b) { return new V3(a.X + b.X, a.Y + b.Y, a.Z + b.Z); }
        public static V3 operator -(V3 a, V3 b) { return new V3(a.X - b.X, a.Y - b.Y, a.Z - b.Z); }
        public static V3 operator *(V3 a, double s) { return new V3(a.X * s, a.Y * s, a.Z * s); }
        public double Dot(V3 b) { return X * b.X + Y * b.Y + Z * b.Z; }
        public V3 Cross(V3 b) { return new V3(Y * b.Z - Z * b.Y, Z * b.X - X * b.Z, X * b.Y - Y * b.X); }
        public double Len { get { return Math.Sqrt(X * X + Y * Y + Z * Z); } }
        public V3 Unit { get { double l = Len; return l < 1e-12 ? new V3(0, 0, 0) : new V3(X / l, Y / l, Z / l); } }
        public V3 Lerp(V3 b, double t) { return this + (b - this) * t; }
    }

    // A planar face: one outer loop, plus inner loops for holes.
    public class Face
    {
        public List<V3> Outer = new List<V3>();
        public List<List<V3>> Inner = new List<List<V3>>();
        public Face() { }
        public Face(IEnumerable<V3> outer) { Outer = outer.ToList(); }

        public V3 Normal()
        {
            // Newell's method - robust for non-convex and slightly non-planar loops.
            double nx = 0, ny = 0, nz = 0;
            for (int i = 0; i < Outer.Count; i++)
            {
                V3 a = Outer[i], b = Outer[(i + 1) % Outer.Count];
                nx += (a.Y - b.Y) * (a.Z + b.Z);
                ny += (a.Z - b.Z) * (a.X + b.X);
                nz += (a.X - b.X) * (a.Y + b.Y);
            }
            return new V3(nx, ny, nz).Unit;
        }
    }

    public class Solid
    {
        public List<Face> Faces = new List<Face>();
        public void Add(Face f) { if (f.Outer.Count >= 3) Faces.Add(f); }
    }

    // Convex polygon used by the BSP. Splitting a convex polygon by a plane
    // always yields convex pieces, so the invariant holds throughout CSG.
    public class CPoly
    {
        public List<V3> V;
        public V3 N;
        public double W;
        public CPoly(List<V3> v) { V = v; Recalc(); }
        public CPoly(List<V3> v, V3 n, double w) { V = v; N = n; W = w; }
        public void Recalc()
        {
            double nx = 0, ny = 0, nz = 0;
            for (int i = 0; i < V.Count; i++)
            {
                V3 a = V[i], b = V[(i + 1) % V.Count];
                nx += (a.Y - b.Y) * (a.Z + b.Z);
                ny += (a.Z - b.Z) * (a.X + b.X);
                nz += (a.X - b.X) * (a.Y + b.Y);
            }
            N = new V3(nx, ny, nz).Unit;
            W = N.Dot(V[0]);
        }
        public CPoly Flipped()
        {
            var v = new List<V3>(V); v.Reverse();
            return new CPoly(v, N * -1, -W);
        }
    }

    public static class Geom
    {
        public const double Eps = 1e-6;

        // ---- 2D ear clipping for a simple (possibly non-convex) polygon ----
        public static List<int[]> Triangulate2D(List<double[]> p)
        {
            var res = new List<int[]>();
            int n = p.Count;
            if (n < 3) return res;
            var idx = Enumerable.Range(0, n).ToList();
            if (Area2D(p) < 0) idx.Reverse();

            int guard = 0;
            while (idx.Count > 3 && guard++ < 10000)
            {
                bool clipped = false;
                for (int i = 0; i < idx.Count; i++)
                {
                    int i0 = idx[(i + idx.Count - 1) % idx.Count], i1 = idx[i], i2 = idx[(i + 1) % idx.Count];
                    double[] a = p[i0], b = p[i1], c = p[i2];
                    double cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
                    if (cross <= 1e-12) continue;                      // reflex or degenerate
                    bool contains = false;
                    foreach (int j in idx)
                    {
                        if (j == i0 || j == i1 || j == i2) continue;
                        if (PointInTri(p[j], a, b, c)) { contains = true; break; }
                    }
                    if (contains) continue;
                    res.Add(new[] { i0, i1, i2 });
                    idx.RemoveAt(i);
                    clipped = true;
                    break;
                }
                if (!clipped) break;      // degenerate input; fall back to a fan below
            }
            if (idx.Count == 3) res.Add(new[] { idx[0], idx[1], idx[2] });
            else if (idx.Count > 3) for (int i = 1; i + 1 < idx.Count; i++) res.Add(new[] { idx[0], idx[i], idx[i + 1] });
            return res;
        }

        static double Area2D(List<double[]> p)
        {
            double a = 0;
            for (int i = 0; i < p.Count; i++)
            {
                var u = p[i]; var v = p[(i + 1) % p.Count];
                a += u[0] * v[1] - v[0] * u[1];
            }
            return a / 2;
        }

        static bool PointInTri(double[] p, double[] a, double[] b, double[] c)
        {
            double d1 = Sign(p, a, b), d2 = Sign(p, b, c), d3 = Sign(p, c, a);
            bool neg = (d1 < -1e-12) || (d2 < -1e-12) || (d3 < -1e-12);
            bool pos = (d1 > 1e-12) || (d2 > 1e-12) || (d3 > 1e-12);
            return !(neg && pos);
        }
        static double Sign(double[] p1, double[] p2, double[] p3)
        {
            return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1]);
        }

        // ---- Extrusion of a 2D section along a local frame ----
        // outline/holes are (u, v) pairs in the plane spanned by eu, ev; the solid
        // runs from origin to origin + dir*length.
        public static Solid Extrude(List<double[]> outline, List<List<double[]>> holes,
                                    V3 origin, V3 dir, V3 eu, V3 ev, double t0, double t1)
        {
            var s = new Solid();
            Func<double[], double, V3> P = (uv, t) => origin + dir * t + eu * uv[0] + ev * uv[1];

            bool ccw = Area2D(outline) > 0;
            var outer = ccw ? outline : Enumerable.Reverse(outline).ToList();

            // Side walls of the outer loop.
            for (int i = 0; i < outer.Count; i++)
            {
                var a = outer[i]; var b = outer[(i + 1) % outer.Count];
                if (Math.Abs(a[0] - b[0]) < 1e-12 && Math.Abs(a[1] - b[1]) < 1e-12) continue;
                s.Add(new Face(new[] { P(a, t0), P(b, t0), P(b, t1), P(a, t1) }));
            }

            var hs = new List<List<double[]>>();
            if (holes != null)
                foreach (var h in holes)
                {
                    var hh = Area2D(h) < 0 ? h : Enumerable.Reverse(h).ToList();   // holes run opposite
                    hs.Add(hh);
                    for (int i = 0; i < hh.Count; i++)
                    {
                        var a = hh[i]; var b = hh[(i + 1) % hh.Count];
                        s.Add(new Face(new[] { P(a, t0), P(b, t0), P(b, t1), P(a, t1) }));
                    }
                }

            // Caps. The t1 cap keeps the outline order, the t0 cap is reversed so
            // both normals point out of the solid.
            var capHi = new Face(outer.Select(uv => P(uv, t1)));
            foreach (var h in hs) capHi.Inner.Add(h.Select(uv => P(uv, t1)).ToList());
            s.Add(capHi);

            var capLo = new Face(Enumerable.Reverse(outer).Select(uv => P(uv, t0)));
            foreach (var h in hs) capLo.Inner.Add(Enumerable.Reverse(h).Select(uv => P(uv, t0)).ToList());
            s.Add(capLo);

            return s;
        }

        // One station of a swept section: where the section sits and how it is turned.
        public struct Frame { public V3 O, Eu, Ev; }

        // Sweeps a 2D section through a list of stations. Side faces are emitted as
        // triangles because a quad spanning two rotated stations is not planar.
        public static Solid Sweep(List<double[]> outline, List<List<double[]>> holes, List<Frame> stations)
        {
            var s = new Solid();
            if (stations.Count < 2) return s;
            Func<Frame, double[], V3> P = (f, uv) => f.O + f.Eu * uv[0] + f.Ev * uv[1];

            bool ccw = Area2D(outline) > 0;
            var outer = ccw ? outline : Enumerable.Reverse(outline).ToList();

            var loops = new List<List<double[]>> { outer };
            var hs = new List<List<double[]>>();
            if (holes != null)
                foreach (var h in holes)
                {
                    var hh = Area2D(h) < 0 ? h : Enumerable.Reverse(h).ToList();
                    hs.Add(hh); loops.Add(hh);
                }

            for (int k = 0; k + 1 < stations.Count; k++)
            {
                Frame f0 = stations[k], f1 = stations[k + 1];
                foreach (var loop in loops)
                    for (int i = 0; i < loop.Count; i++)
                    {
                        var a = loop[i]; var b = loop[(i + 1) % loop.Count];
                        if (Math.Abs(a[0] - b[0]) < 1e-12 && Math.Abs(a[1] - b[1]) < 1e-12) continue;
                        V3 a0 = P(f0, a), b0 = P(f0, b), a1 = P(f1, a), b1 = P(f1, b);
                        s.Add(new Face(new[] { a0, b0, b1 }));
                        s.Add(new Face(new[] { a0, b1, a1 }));
                    }
            }

            Frame last = stations[stations.Count - 1], first = stations[0];
            var capHi = new Face(outer.Select(uv => P(last, uv)));
            foreach (var h in hs) capHi.Inner.Add(h.Select(uv => P(last, uv)).ToList());
            s.Add(capHi);

            var capLo = new Face(Enumerable.Reverse(outer).Select(uv => P(first, uv)));
            foreach (var h in hs) capLo.Inner.Add(Enumerable.Reverse(h).Select(uv => P(first, uv)).ToList());
            s.Add(capLo);

            return s;
        }

        // ---- Solid <-> convex polygon soup ----
        public static List<CPoly> ToPolys(Solid s)
        {
            var res = new List<CPoly>();
            foreach (var f in s.Faces)
            {
                foreach (var tri in TriangulateFace(f))
                {
                    var cp = new CPoly(tri);
                    if (cp.N.Len > 0.5) res.Add(cp);
                }
            }
            return res;
        }

        // Triangulate a planar face with holes by projecting to its best plane and
        // bridging each hole into the outer loop.
        public static List<List<V3>> TriangulateFace(Face f)
        {
            var outs = new List<List<V3>>();
            V3 n = f.Normal();
            if (n.Len < 0.5) return outs;

            V3 eu = Math.Abs(n.X) < 0.9 ? new V3(1, 0, 0) : new V3(0, 1, 0);
            eu = (eu - n * n.Dot(eu)).Unit;
            V3 ev = n.Cross(eu);

            var loop = new List<V3>(f.Outer);
            var loop2 = loop.Select(p => new double[] { p.Dot(eu), p.Dot(ev) }).ToList();

            // Annular cap (a tube wall): strip the two rings together directly.
            // Bridging a ring into another ring makes a self-touching polygon that
            // ear clipping handles badly, so this case is worth special-casing.
            if (f.Inner.Count == 1 && f.Inner[0].Count == f.Outer.Count && f.Outer.Count >= 3)
            {
                // A cap's inner bound winds opposite to its outer bound, which is
                // what STEP wants but not what a strip wants - align a local copy.
                var inner = new List<V3>(f.Inner[0]);
                var in2 = inner.Select(p => new double[] { p.Dot(eu), p.Dot(ev) }).ToList();
                if (Math.Sign(Area2D(loop2)) != Math.Sign(Area2D(in2))) inner.Reverse();
                int m = inner.Count;
                int bestK = 0; double bestD = double.MaxValue;
                for (int k = 0; k < m; k++)
                {
                    double sum = 0;
                    for (int i = 0; i < m; i++) sum += (loop[i] - inner[(i + k) % m]).Len;
                    if (sum < bestD) { bestD = sum; bestK = k; }
                }
                for (int i = 0; i < m; i++)
                {
                    V3 o0 = loop[i], o1 = loop[(i + 1) % m];
                    V3 i0 = inner[(i + bestK) % m], i1 = inner[(i + 1 + bestK) % m];
                    AddTri(outs, o0, o1, i1, n);
                    AddTri(outs, o0, i1, i0, n);
                }
                return outs;
            }

            if (f.Inner.Count > 0)
            {
                foreach (var hole in f.Inner)
                {
                    var h2 = hole.Select(p => new double[] { p.Dot(eu), p.Dot(ev) }).ToList();
                    if (Area2D(h2) > 0) { h2.Reverse(); hole.Reverse(); }
                    // Bridge: join the hole's rightmost vertex to the nearest outer vertex.
                    int hi = 0; for (int i = 1; i < h2.Count; i++) if (h2[i][0] > h2[hi][0]) hi = i;
                    int oi = 0; double best = double.MaxValue;
                    for (int i = 0; i < loop2.Count; i++)
                    {
                        double dx = loop2[i][0] - h2[hi][0], dy = loop2[i][1] - h2[hi][1];
                        double d = dx * dx + dy * dy;
                        if (d < best) { best = d; oi = i; }
                    }
                    var nl = new List<V3>(); var nl2 = new List<double[]>();
                    for (int i = 0; i <= oi; i++) { nl.Add(loop[i]); nl2.Add(loop2[i]); }
                    for (int i = 0; i <= h2.Count; i++)
                    {
                        int k = (hi + i) % h2.Count;
                        nl.Add(hole[k]); nl2.Add(h2[k]);
                    }
                    for (int i = oi; i < loop.Count; i++) { nl.Add(loop[i]); nl2.Add(loop2[i]); }
                    loop = nl; loop2 = nl2;
                }
            }

            bool flip = Area2D(loop2) < 0;
            foreach (var t in Triangulate2D(loop2))
            {
                var tri = new List<V3> { loop[t[0]], loop[t[1]], loop[t[2]] };
                if (flip) tri.Reverse();
                // Keep the winding consistent with the face normal.
                V3 tn = (tri[1] - tri[0]).Cross(tri[2] - tri[0]);
                if (tn.Dot(n) < 0) tri.Reverse();
                if (tn.Len > 1e-9) outs.Add(tri);
            }
            return outs;
        }

        // Best-fit plane normal of a 3D loop; tolerates slight warping.
        public static V3 Newell(List<V3> loop)
        {
            double nx = 0, ny = 0, nz = 0;
            for (int i = 0; i < loop.Count; i++)
            {
                V3 a = loop[i], b = loop[(i + 1) % loop.Count];
                nx += (a.Y - b.Y) * (a.Z + b.Z);
                ny += (a.Z - b.Z) * (a.X + b.X);
                nz += (a.X - b.X) * (a.Y + b.Y);
            }
            return new V3(nx, ny, nz).Unit;
        }

        static void AddTri(List<List<V3>> outs, V3 a, V3 b, V3 c, V3 n)
        {
            V3 tn = (b - a).Cross(c - a);
            if (tn.Len < 1e-9) return;
            var tri = new List<V3> { a, b, c };
            if (tn.Dot(n) < 0) tri.Reverse();
            outs.Add(tri);
        }

        public static Solid FromPolys(List<CPoly> polys)
        {
            var s = new Solid();
            foreach (var p in polys) s.Add(new Face(p.V));
            return s;
        }

        // Model coordinates here sit around z = 100 000, so summing tetrahedra from
        // the world origin loses the answer to floating-point cancellation. Shift to
        // a local reference point first.
        public static double Volume(List<CPoly> polys)
        {
            if (polys.Count == 0) return 0;
            double rx = 0, ry = 0, rz = 0;
            foreach (var p in polys) { rx += p.V[0].X; ry += p.V[0].Y; rz += p.V[0].Z; }
            var r = new V3(rx / polys.Count, ry / polys.Count, rz / polys.Count);

            double v = 0;
            foreach (var p in polys)
            {
                V3 a = p.V[0] - r;
                for (int i = 1; i + 1 < p.V.Count; i++)
                    v += a.Dot((p.V[i] - r).Cross(p.V[i + 1] - r)) / 6.0;
            }
            return v;
        }
    }

    // ---- BSP CSG (the csg.js algorithm) ----
    public class Bsp
    {
        V3 pn; double pw; bool hasPlane;
        Bsp front, back;
        List<CPoly> polys = new List<CPoly>();
        const double E = 1e-5;

        public Bsp() { }
        public Bsp(List<CPoly> p) { Build(p); }

        public void Invert()
        {
            for (int i = 0; i < polys.Count; i++) polys[i] = polys[i].Flipped();
            pn = pn * -1; pw = -pw;
            if (front != null) front.Invert();
            if (back != null) back.Invert();
            var t = front; front = back; back = t;
        }

        List<CPoly> ClipPolys(List<CPoly> list)
        {
            if (!hasPlane) return new List<CPoly>(list);
            var f = new List<CPoly>(); var b = new List<CPoly>();
            foreach (var p in list) Split(p, f, b, f, b);
            if (front != null) f = front.ClipPolys(f);
            if (back != null) b = back.ClipPolys(b); else b.Clear();
            f.AddRange(b);
            return f;
        }

        public void ClipTo(Bsp o)
        {
            polys = o.ClipPolys(polys);
            if (front != null) front.ClipTo(o);
            if (back != null) back.ClipTo(o);
        }

        public List<CPoly> All()
        {
            var r = new List<CPoly>(polys);
            if (front != null) r.AddRange(front.All());
            if (back != null) r.AddRange(back.All());
            return r;
        }

        // A fixed seed keeps runs reproducible; picking the splitting plane at
        // random avoids the degenerate linear tree that a faceted cylinder's
        // near-parallel facets would otherwise produce (and the stack overflow
        // that comes with it).
        [ThreadStatic] static Random rng;

        public void Build(List<CPoly> list)
        {
            if (list.Count == 0) return;
            if (rng == null) rng = new Random(12345);
            if (!hasPlane)
            {
                var pick = list[rng.Next(list.Count)];
                pn = pick.N; pw = pick.W; hasPlane = true;
            }
            var f = new List<CPoly>(); var b = new List<CPoly>();
            foreach (var p in list) Split(p, polys, polys, f, b);
            if (f.Count > 0) { if (front == null) front = new Bsp(); front.Build(f); }
            if (b.Count > 0) { if (back == null) back = new Bsp(); back.Build(b); }
        }

        void Split(CPoly p, List<CPoly> coFront, List<CPoly> coBack, List<CPoly> f, List<CPoly> b)
        {
            const int COPLANAR = 0, FRONT = 1, BACK = 2, SPANNING = 3;
            int type = 0;
            var types = new int[p.V.Count];
            for (int i = 0; i < p.V.Count; i++)
            {
                double t = pn.Dot(p.V[i]) - pw;
                int ty = t < -E ? BACK : (t > E ? FRONT : COPLANAR);
                type |= ty; types[i] = ty;
            }
            switch (type)
            {
                case COPLANAR:
                    (pn.Dot(p.N) > 0 ? coFront : coBack).Add(p);
                    break;
                case FRONT: f.Add(p); break;
                case BACK: b.Add(p); break;
                default:
                    var fv = new List<V3>(); var bv = new List<V3>();
                    for (int i = 0; i < p.V.Count; i++)
                    {
                        int j = (i + 1) % p.V.Count;
                        int ti = types[i], tj = types[j];
                        V3 vi = p.V[i], vj = p.V[j];
                        if (ti != BACK) fv.Add(vi);
                        if (ti != FRONT) bv.Add(vi);
                        if ((ti | tj) == SPANNING)
                        {
                            double t = (pw - pn.Dot(vi)) / pn.Dot(vj - vi);
                            V3 v = vi.Lerp(vj, t);
                            fv.Add(v); bv.Add(v);
                        }
                    }
                    if (fv.Count >= 3) f.Add(new CPoly(fv, p.N, p.W));
                    if (bv.Count >= 3) b.Add(new CPoly(bv, p.N, p.W));
                    break;
            }
        }

        // a minus b
        public static List<CPoly> Subtract(List<CPoly> a, List<CPoly> b)
        {
            var A = new Bsp(a); var B = new Bsp(b);
            A.Invert();
            A.ClipTo(B);
            B.ClipTo(A);
            B.Invert();
            B.ClipTo(A);
            B.Invert();
            A.Build(B.All());
            A.Invert();
            return A.All();
        }
    }
}
