#!/bin/bash
cd /work/agentwork/cut-not-applied/reports
for i in 6a44b409f977d7c2 6304887153755ea3 0762effe61de88c0 df81723c53d23ef7 e151a8faacbce446; do echo "$i $(grep -a -h -o 'Date: *[0-9.]*' $i/KSS_part_list.xsr $i/Hot_Rolled_list-KSS.xsr 2>/dev/null | sort -u | tr '\n' ' ')"; done
