using System;
using System.IO;
using System.Threading;

namespace Tek
{
    /// .db1 -> .step, with no Tekla installed and no licence.
    ///   db1tostep.exe <model.db1> <out.step> <report.txt> <schedule.csv> [nobolts]
    public static class Db1ToStep
    {
        public static int Main(string[] args)
        {
            if (args.Length < 4)
            {
                Console.WriteLine("db1tostep.exe <model.db1> <out.step> <report.txt> <schedule.csv> [nobolts]");
                return 2;
            }
            int rc = 1;
            var t = new Thread(() => rc = Run(args), 512 * 1024 * 1024);   // CSG recursion
            t.Start(); t.Join();
            return rc;
        }

        static int Run(string[] args)
        {
            string db1 = args[0];
            bool withBolts = args.Length < 5 || args[4] != "nobolts";
            string name = Path.GetFileNameWithoutExtension(db1);

            var clock = System.Diagnostics.Stopwatch.StartNew();
            Console.WriteLine("reading " + db1);
            var model = Db1Reader.Read(db1);
            Console.WriteLine("engine: " + Db1Reader.Version);
            if (Db1Reader.Unsupported)
            {
                Console.WriteLine("UNSUPPORTED ENGINE - no record layout has been derived for this version.");
                Console.WriteLine("Supported: Xsteel 6.87, 7.01, 7.24. See README for how to extend.");
                return 3;
            }
            foreach (var t in new[] { "part", "part_attr", "point", "coordsys_attr", "partpolygon", "relation", "object", "assembly" })
                Console.WriteLine("   " + t.PadRight(16) + model.T(t).Count);

            var res = Converter.Convert(model, db1, args[1], args[2], args[3], name, withBolts);
            clock.Stop();

            Console.WriteLine();
            Console.WriteLine("ok            : " + res.Ok + (res.Error.Length > 0 ? "  (" + res.Error + ")" : ""));
            Console.WriteLine("parts         : " + res.Parts);
            Console.WriteLine("solids written: " + res.SolidsWritten);
            Console.WriteLine("steel kg      : " + res.SteelKg.ToString("F1"));
            Console.WriteLine("bolts kg      : " + res.BoltKg.ToString("F1"));
            Console.WriteLine("bbox mm       : " +
                (res.BBoxMax[0] - res.BBoxMin[0]).ToString("F0") + " x " +
                (res.BBoxMax[1] - res.BBoxMin[1]).ToString("F0") + " x " +
                (res.BBoxMax[2] - res.BBoxMin[2]).ToString("F0"));
            Console.WriteLine("step          : " + (res.StepBytes / 1048576.0).ToString("F1") + " MB");
            Console.WriteLine("elapsed       : " + clock.Elapsed.TotalSeconds.ToString("F1") + " s");
            return res.Ok ? 0 : 1;
        }
    }
}

