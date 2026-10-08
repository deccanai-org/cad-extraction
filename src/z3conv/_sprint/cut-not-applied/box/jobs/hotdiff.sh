#!/bin/bash
W=/work/agentwork/cut-not-applied; cd $W
for id in e151a8faacbce446 6304887153755ea3 6a44b409f977d7c2 df81723c53d23ef7 0762effe61de88c0; do /opt/conv/env/bin/python tools/hot_diff.py $id | head -12; done
grep -a -i "75X10\|F.B" reports/e151a8faacbce446/Hot_*xsr | head -10
