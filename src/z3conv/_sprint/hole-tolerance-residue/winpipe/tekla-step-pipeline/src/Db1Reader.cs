using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Text;

namespace Tek
{
    /// Reads a Tekla/Xsteel .db1 directly, with no Tekla installed.
    ///
    /// The file is the Xsteel engine's record store: an optional gzip wrapper, an
    /// "Xsteel  N.NN" header, then fixed-size records grouped by table. Each record
    /// carries a 1-byte prefix, so the stride is one more than the record body.
    ///
    /// Layouts below were derived mechanically against the ASCII dump of the same model
    /// (see Db1Layout) rather than guessed, and every field is re-checked by Db1Verify.
    ///
    /// Output is the same shape Dump.Parse produces, so the existing STEP converter
    /// consumes it unchanged.
    public static class Db1Reader
    {
        class Fld
        {
            public string Name; public int Off; public char Kind; public int Len;
            public Fld(string n, int o, char k, int l = 0) { Name = n; Off = o; Kind = k; Len = l; }
        }

        class TableSpec
        {
            public string Name;
            public int Stride;
            public List<Fld> Fields = new List<Fld>();
            public Func<byte[], int, bool> Valid;
        }

        // Per-thread: the batch pipeline converts models in parallel, and shared statics
        // here leaked one model's engine version into another's read.
        [ThreadStatic] public static string Version;
        /// True when the engine version has no derived layout; tables come back empty.
        [ThreadStatic] public static bool Unsupported;

        static List<Fld> Arr(string prefix, int start, int count, char kind, int step)
        {
            var l = new List<Fld>();
            for (int i = 1; i <= count; i++) l.Add(new Fld(prefix + i, start + (i - 1) * step, kind));
            return l;
        }

        /// The `part` record changed shape between engine versions: 6.87/7.01 carry
        /// partstartno and fpos before the point refs, later engines drop them and widen
        /// the record. Offsets here were discovered by Db1Discover against referential
        /// integrity, not guessed. Anything unrecognised falls back to the 6.87 layout,
        /// which simply yields no parts rather than wrong ones.
        class PartLayout
        {
            public int Stride, OAttr, OP1, OP2, OPoly, OCsysAttr, OCsys;
            public bool HasStartNo;
            // other tables, which also shift between engines
            public int PointStride = 33, CsysStride = 53, CsysIdOff = 48;
            public int PartAttrStride = 373, PolyStride = 333;
            public int PaProf = 124, PaMat = 270, PaBen = 102, PaNpoints = 72, PaYlage = 44, PaZlage = 60;
        }

        /// The banner is "Xsteel" followed by a byte that is not always printable, then the
        /// version, so pull the first number out of the string rather than trusting its shape.
        static string Sanitize(string s)
        {
            var sb = new StringBuilder();
            foreach (var c in s) sb.Append(c >= 32 && c <= 126 ? c : ' ');
            return sb.ToString().Trim();
        }
        
        public static double EngineNumber(string version)
        {
            string v = version ?? "";
            int i = 0;
            while (i < v.Length && !char.IsDigit(v[i])) i++;
            int j = i;
            while (j < v.Length && (char.IsDigit(v[j]) || v[j] == '.')) j++;
            double n;
            double.TryParse(v.Substring(i, j - i), NumberStyles.Float, CultureInfo.InvariantCulture, out n);
            return n;
        }

        static PartLayout LayoutFor(string version)
        {
            double n = EngineNumber(version);

            // 7.5+ is NOT supported. Partial findings for 7.64 are recorded here because
            // they are real and were expensive to get, but `part_attr` - which carries the
            // profile and material strings, and without which there is no geometry at all -
            // has not been located, and no coordinate source for the part record has been
            // identified. Engaging this layout would emit plausible-looking wrong geometry,
            // which across thousands of models is worse than emitting none, so it stays off.
            //
            //   point         stride 41
            //   coordsys_attr stride 61, id @ +56
            //   part          stride ~164, id@0 part_attr_id@4 p1@16 p2@20
            //   coordsys      stride 65, csys_attr_id@+4, x1/y1/z1/length@+8
            //   part_attr     stride ~324 (from profile-string spacing), offsets unknown
            if (n >= 7.5) return null;

            if (n >= 7.1)
                return new PartLayout { Stride = 228, OAttr = 4, OP1 = 8, OP2 = 12, OPoly = 16, OCsysAttr = 20, OCsys = 24, HasStartNo = false };

            return new PartLayout { Stride = 121, OAttr = 4, OP1 = 12, OP2 = 16, OPoly = 28, OCsysAttr = 32, OCsys = 40, HasStartNo = true };
        }

        static List<TableSpec> Specs(string version)
        {
            var L = LayoutFor(version);
            if (L == null) return null;
            var specs = new List<TableSpec>();

            var part = new TableSpec { Name = "part", Stride = L.Stride };
            part.Fields.AddRange(new[]{
                new Fld("id",0,'i'), new Fld("part_attr_id",L.OAttr,'i'),
                new Fld("p1",L.OP1,'i'), new Fld("p2",L.OP2,'i'),
                new Fld("polygon_id",L.OPoly,'i'), new Fld("csys_attr_id",L.OCsysAttr,'i'),
                new Fld("csys_x",L.OCsys,'d'), new Fld("csys_y",L.OCsys+8,'d'),
                new Fld("csys_z",L.OCsys+16,'d'), new Fld("csys_length",L.OCsys+24,'d')});
            if (L.HasStartNo)
                part.Fields.AddRange(new[]{ new Fld("partstartno",8,'i'), new Fld("fpos",20,'i'),
                                            new Fld("pos",72,'s',16), new Fld("analysis_attr_id",116,'i')});
            part.Valid = (b, o) =>
            {
                int id = I(b, o), pa = I(b, o + L.OAttr);
                if (id <= 0 || id > 20000000 || pa <= 0 || pa > 20000000) return false;
                double len = D(b, o + L.OCsys + 24);
                if (double.IsNaN(len) || len < 0 || len > 1e6) return false;
                for (int k = 0; k <= 16; k += 8)
                {
                    double v = D(b, o + L.OCsys + k);
                    if (double.IsNaN(v) || Math.Abs(v) > 1e8) return false;
                }
                return true;
            };
            specs.Add(part);

            var pa2 = new TableSpec { Name = "part_attr", Stride = L.PartAttrStride };
            pa2.Fields.AddRange(new[]{
                new Fld("id",0,'i'), new Fld("obj_type",4,'i'), new Fld("form_type",8,'i'),
                new Fld("obj_class",12,'i'), new Fld("assstartno",16,'i'),
                new Fld("ylage",44,'i'), new Fld("zlage",60,'i'), new Fld("npoints",72,'i'),
                new Fld("ryhma",80,'s',22), new Fld("ben",102,'s',22), new Fld("prof",124,'s',62),
                new Fld("asspos",186,'s',22), new Fld("mat",270,'s',22)});
            pa2.Valid = (b, o) =>
            {
                int id = I(b, o), ot = I(b, o + 4);
                if (id <= 0 || id > 20000000 || ot < 0 || ot > 100) return false;
                int np = I(b, o + 72); if (np < 0 || np > 64) return false;
                return Printable(b, o + 124, 4) || Printable(b, o + 270, 3);
            };
            specs.Add(pa2);

            var pt = new TableSpec { Name = "point", Stride = L.PointStride };
            pt.Fields.AddRange(new[]{
                new Fld("id",0,'i'), new Fld("vis",4,'i'),
                new Fld("x",8,'d'), new Fld("y",16,'d'), new Fld("z",24,'d')});
            pt.Valid = (b, o) =>
            {
                int id = I(b, o), vis = I(b, o + 4);
                if (id <= 0 || id > 20000000 || vis < 0 || vis > 64) return false;
                for (int k = 8; k <= 24; k += 8) { double v = D(b, o + k); if (double.IsNaN(v) || Math.Abs(v) > 1e8) return false; }
                return true;
            };
            specs.Add(pt);

            var ca = new TableSpec { Name = "coordsys_attr", Stride = L.CsysStride };
            ca.Fields.AddRange(new[]{
                new Fld("xdir_x",0,'d'), new Fld("xdir_y",8,'d'), new Fld("xdir_z",16,'d'),
                new Fld("ydir_x",24,'d'), new Fld("ydir_y",32,'d'), new Fld("ydir_z",40,'d'),
                new Fld("id",L.CsysIdOff,'i')});
            ca.Valid = (b, o) =>
            {
                int id = I(b, o + L.CsysIdOff);
                if (id <= 0 || id > 20000000) return false;
                double sx = 0, sy = 0;
                for (int k = 0; k < 3; k++)
                {
                    double v = D(b, o + k * 8); if (double.IsNaN(v) || Math.Abs(v) > 1.0001) return false; sx += v * v;
                    double w = D(b, o + 24 + k * 8); if (double.IsNaN(w) || Math.Abs(w) > 1.0001) return false; sy += w * w;
                }
                return Math.Abs(sx - 1) < 0.02 && Math.Abs(sy - 1) < 0.02;
            };
            specs.Add(ca);

            var pp = new TableSpec { Name = "partpolygon", Stride = L.PolyStride };
            pp.Fields.AddRange(new[] { new Fld("id", 0, 'i'), new Fld("no", 4, 'i'), new Fld("hash_id", 8, 'i') });
            pp.Fields.AddRange(Arr("x", 12, 10, 'f', 4));
            pp.Fields.AddRange(Arr("y", 52, 10, 'f', 4));
            pp.Fields.AddRange(Arr("z", 92, 10, 'f', 4));
            pp.Fields.AddRange(Arr("dx", 132, 10, 'f', 4));
            pp.Fields.AddRange(Arr("dy", 172, 10, 'f', 4));
            pp.Fields.AddRange(Arr("types", 212, 10, 'i', 4));
            pp.Fields.AddRange(Arr("dz1_", 252, 10, 'f', 4));
            pp.Fields.AddRange(Arr("dz2_", 292, 10, 'f', 4));
            pp.Valid = (b, o) =>
            {
                int id = I(b, o), no = I(b, o + 4);
                if (id <= 0 || id > 20000000 || no < 0 || no > 64) return false;
                for (int k = 12; k < 132; k += 4)
                {
                    float v = F(b, o + k);
                    if (float.IsNaN(v) || float.IsInfinity(v) || Math.Abs(v) > 1e7) return false;
                }
                return true;
            };
            specs.Add(pp);

            var rel = new TableSpec { Name = "relation", Stride = 17 };
            rel.Fields.AddRange(new[]{ new Fld("id",0,'i'), new Fld("type",4,'i'),
                                       new Fld("id1",8,'i'), new Fld("id2",12,'i')});
            rel.Valid = (b, o) =>
            {
                int id = I(b, o), t = I(b, o + 4), a = I(b, o + 8), c = I(b, o + 12);
                return id > 0 && id <= 20000000 && t >= 0 && t <= 2000 &&
                       a > 0 && a <= 20000000 && c > 0 && c <= 20000000;
            };
            specs.Add(rel);

            var obj = new TableSpec { Name = "object", Stride = 68 };
            obj.Fields.AddRange(new[]{
                new Fld("id",0,'i'), new Fld("object_attr_id",4,'i'), new Fld("mod",8,'i'),
                new Fld("num_id",12,'i'), new Fld("save_id",16,'i'), new Fld("kuuluu",20,'i'),
                new Fld("assembly",24,'i'), new Fld("guid",28,'s',40)});
            obj.Valid = (b, o) =>
            {
                int id = I(b, o);
                if (id <= 0 || id > 20000000) return false;
                return b[o + 28] == (byte)'I' && b[o + 29] == (byte)'D';
            };
            specs.Add(obj);

            var asm = new TableSpec { Name = "assembly", Stride = 153 };
            asm.Fields.AddRange(new[]{
                new Fld("id",0,'i'), new Fld("obj_type",4,'i'), new Fld("start_no",8,'i'),
                new Fld("fpos",12,'i'), new Fld("dum",28,'i'),
                new Fld("pos",40,'s',22), new Fld("name",84,'s',62)});
            asm.Valid = (b, o) =>
            {
                int id = I(b, o), ot = I(b, o + 4);
                return id > 0 && id <= 20000000 && ot >= 0 && ot <= 100 && Printable(b, o + 84, 2);
            };
            specs.Add(asm);

            return specs;
        }

        public static Dump Read(string path)
        {
            byte[] bin = Load(path);
            Version = bin.Length > 16 ? Sanitize(Encoding.ASCII.GetString(bin, 0, 12)) : "";

            var d = new Dump();
            var specs = Specs(Version);

            if (specs == null)

            {

                Unsupported = true;

                return d;          // engine version whose layout has not been derived

            }

            foreach (var spec in specs)

                d.Tables[spec.Name] = ScanTable(bin, spec);

            Salvage(bin, d, specs.First(x => x.Name == "part"));
            return d;
        }

        /// Records edited late in a model's life land in free slots rather than the main
        /// contiguous run, so a run-length filter misses them - in the reference model
        /// that cost a whole bracket assembly. Recover isolated records by requiring that
        /// every id they reference resolves against the tables already read, which no
        /// chance byte alignment survives.
        static void Salvage(byte[] b, Dump d, TableSpec part)
        {
            var have = new HashSet<int>(d.T("part").Select(r => r.I("id")));
            var attrs = new HashSet<int>(d.T("part_attr").Select(r => r.I("id")));
            var pts = new HashSet<int>(d.T("point").Select(r => r.I("id")));
            var csys = new HashSet<int>(d.T("coordsys_attr").Select(r => r.I("id")));
            if (attrs.Count == 0 || pts.Count == 0) return;

            int last = b.Length - part.Stride;
            var added = new Dictionary<int, Row>();
            for (int i = 0; i <= last; i++)
            {
                if (!part.Valid(b, i)) continue;
                int id = I(b, i);
                if (have.Contains(id) || added.ContainsKey(id)) continue;
                if (!attrs.Contains(I(b, i + 4))) continue;          // part_attr_id
                if (!pts.Contains(I(b, i + 12))) continue;           // p1
                if (!pts.Contains(I(b, i + 16))) continue;           // p2
                if (!csys.Contains(I(b, i + 32))) continue;          // csys_attr_id
                added[id] = Decode(b, i, part);
            }
            foreach (var r in added.Values) d.Tables["part"].Add(r);
        }

        /// gunzip when wrapped; older models are stored plain.
        public static byte[] Load(string path)
        {
            var raw = File.ReadAllBytes(path);
            if (raw.Length > 2 && raw[0] == 0x1F && raw[1] == 0x8B)
            {
                using (var ms = new MemoryStream(raw))
                using (var gz = new GZipStream(ms, CompressionMode.Decompress))
                using (var outMs = new MemoryStream())
                {
                    gz.CopyTo(outMs);
                    return outMs.ToArray();
                }
            }
            return raw;
        }

        /// Records of one table sit in contiguous runs at a fixed stride. Find every run
        /// of validating records and take the union, keyed by id so overlapping scans of
        /// the same run collapse.
        static List<Row> ScanTable(byte[] b, TableSpec s)
        {
            const int MinRun = 6;
            var seen = new Dictionary<long, Row>();
            var seenRun = new Dictionary<long, int>();
            int i = 0;
            int last = b.Length - s.Stride;

            while (i <= last)
            {
                if (!s.Valid(b, i)) { i++; continue; }
                int run = 0, j = i;
                while (j <= last && s.Valid(b, j)) { run++; j += s.Stride; }
                if (run >= MinRun)
                {
                    for (int k = i; k < j; k += s.Stride)
                    {
                        var row = Decode(b, k, s);
                        long key = row.I("id");
                        if (key == 0) continue;
                        if (s.Name == "partpolygon") key = key * 100 + row.I("no");
                        // A stray offset can validate by chance. The genuine table is the
                        // long contiguous run, so when ids collide keep the record from
                        // the longer run.
                        int prev;
                        if (!seenRun.TryGetValue(key, out prev) || run > prev)
                        {
                            seen[key] = row;
                            seenRun[key] = run;
                        }
                    }
                    i = j;
                }
                else i++;
            }
            return seen.Values.ToList();
        }

        static Row Decode(byte[] b, int o, TableSpec s)
        {
            var r = new Row();
            foreach (var f in s.Fields)
            {
                int p = o + f.Off;
                switch (f.Kind)
                {
                    case 'i': r[f.Name] = I(b, p).ToString(CultureInfo.InvariantCulture); break;
                    case 'd': r[f.Name] = D(b, p).ToString("F6", CultureInfo.InvariantCulture); break;
                    case 'f': r[f.Name] = ((double)F(b, p)).ToString("F6", CultureInfo.InvariantCulture); break;
                    case 's': r[f.Name] = Str(b, p, f.Len); break;
                }
            }
            return r;
        }

        static int I(byte[] b, int o) { return o + 4 <= b.Length ? BitConverter.ToInt32(b, o) : 0; }
        static double D(byte[] b, int o) { return o + 8 <= b.Length ? BitConverter.ToDouble(b, o) : double.NaN; }
        static float F(byte[] b, int o) { return o + 4 <= b.Length ? BitConverter.ToSingle(b, o) : float.NaN; }

        static string Str(byte[] b, int o, int max)
        {
            if (o >= b.Length) return "";
            var sb = new StringBuilder();
            for (int i = 0; i < max && o + i < b.Length; i++)
            {
                byte c = b[o + i];
                if (c == 0) break;
                if (c < 32 || c > 126) return sb.ToString();
                sb.Append((char)c);
            }
            return sb.ToString();
        }

        static bool Printable(byte[] b, int o, int need)
        {
            if (o + need > b.Length) return false;
            for (int i = 0; i < need; i++)
            {
                byte c = b[o + i];
                if (c < 32 || c > 126) return false;
            }
            return true;
        }
    }
}





