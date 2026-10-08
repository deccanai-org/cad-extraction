while read R I N; do ( out=$(bash /tmp/z3c/ssmcli.sh $R $I /tmp/z3c/scipy.sh 300 2>&1 | tail -n +2); echo "== $N $I"; echo "$out" ) & done <<LIST
ap-south-1 i-0497fc266f3f8748a db1
ap-south-1 i-014c130c5144c5196 grade1
ap-south-1 i-03c579253a2b0d70e grade2
ap-south-1 i-0dae3109c7dae1984 grade3
ap-south-1 i-05a00abaa37960b4d ifc1
ap-south-1 i-0c76bf8926e9669f9 ifc2
ap-south-1 i-0e91c1594449c1cfc ifc3
ap-south-1 i-01f60497cfa23aae4 sds2a
ap-south-1 i-08338c4bb48a3ed18 sds2b
ap-south-1 i-0fdbf9d9420c1732c sds2c
ap-south-2 i-033bef6cead23f06a hyd1
ap-south-2 i-04b259159b528ee39 hyd2
ap-south-2 i-06d3d9457c3bc9bb3 hyd3
ap-south-2 i-0742c5de9def38bd4 hyd4
ap-south-2 i-09c07bdcf943028f9 hyd5
ap-south-1 i-016705f3ab15144d3 x1
ap-south-1 i-039ae7eee6a44023e x2
ap-south-1 i-06c7bcef59d4745dd x3
ap-south-1 i-07e410405fab606b4 x4
ap-south-1 i-09922887389799094 x5
ap-south-1 i-0d7e4bfce5b6be6f1 x6
ap-south-1 i-0dd317aa86cd2b485 x7
ap-south-1 i-0e1d51ab6ed3d4b2f x8
LIST
wait
