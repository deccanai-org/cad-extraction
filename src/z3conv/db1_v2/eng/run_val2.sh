P=/Users/dhiren/Downloads/Deccan/z3conv/db1_v2/_env/env/bin/python
while pgrep -f run_dumps.sh > /dev/null; do sleep 20; done
$P validate.py data/8.07_no_member_layout_7059354edd.db1 data/8.07_no_member_layout_7059354edd.ifc 8.07 > val_7059.log 2>&1
$P validate.py data/9.08_ok_f34e32d507.db1 data/9.08_ok_f34e32d507.ifc 9.08 > val_f34e.log 2>&1
