#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W; cp stage/tools/spec2.py tools/
OUT=s3://bim-proprietary-data/cad-disk-extract/zenitude-data-3/_state/agentwork/cut-not-applied
P=/opt/conv/env/bin/python
r() { $P tools/spec2.py "$1" "$2" $3 $4 renders/$5.json "$6" "$7" "$8" && timeout 900 $P tools/render_pair.py renders/$5.json renders/$5.png && aws s3 cp --quiet renders/$5.png $OUT/renders/; }
r pipes3/nofit/truth_iron pipes3/fit/truth_iron 130663016 0 p13_iron_pipe_fitting 'without fittings (L 663.2 mm)' 'P13 fittings (Tekla Length 687.5)' 'IRON_ORE 7.24 PIPE1-1/2SCH40 130663016: Tekla NetVolume 314,777 mm3 | ours 338,685 -> 327,384'
r pipes3/nofit/truth_iron pipes3/fit/truth_iron 121775453 0 p13_iron_W10X22_fitting 'without fittings (L 1447.8)' 'P13 fittings (Tekla Length 1412.9)' 'IRON_ORE 7.24 W10X22 121775453: Tekla NetVolume 5,661,595 mm3 | ours 6,024,447 -> 5,910,693'
r pipes3/nofit/0762effe61de88c0 pipes3/fit/0762effe61de88c0 65130 0 p13_0762_L150_linecuts 'without line cuts: 17.09 kg' 'P13 line cuts: 14.56 kg' '0762effe 6.87 L150*90*10 (mark TA4100, Tekla net 14.5 kg, gross 17.0)'
r pipes3/nofit/0762effe61de88c0 pipes3/fit/0762effe61de88c0 52418 0 p13_0762_channel_fitting 'without fittings' 'P13 oblique fittings (ends extended to the planes, clipped)' '0762effe 6.87 [200*90*8*13.5 52418: two oblique fittings'
r pipes4/nofit/fit_p7.64 pipes4/fit/fit_p7.64 1365019 0 p12_p764_C6X8_fitting 'without fittings (end 6.4 mm long)' 'P12 fitting (end trimmed to the plane)' 'Duke_Boiler 7.64 C6X8.2 1365019: bbox vs Tekla IFC 6.4 mm -> 0.0 mm'
ls -la renders/p1*.png
