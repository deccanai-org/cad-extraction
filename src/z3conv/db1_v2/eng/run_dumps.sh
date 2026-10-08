P=/Users/dhiren/Downloads/Deccan/z3conv/db1_v2/_env/env/bin/python
for x in "8.85_no_member_layout_d69ba800a9 8.85" "7.98_no_member_layout_15f863101f 7.98" "8.85_no_member_layout_645f62bc74 8.85" "9.21_unapproved_engine_254a5fdd9e 9.21" "9.21_unapproved_engine_c4bf00c134 9.21" "8.07_no_member_layout_3ef2ec016b 8.07"; do
  set -- $x
  [ -f dumps/$1.pkl ] || $P dump_members.py src data/$1.db1 $2 dumps/$1.pkl
done
