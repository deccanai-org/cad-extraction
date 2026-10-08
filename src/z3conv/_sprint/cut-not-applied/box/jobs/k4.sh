#!/bin/bash
kill -- -3231870 2>/dev/null; sleep 1
pkill -f "cut-not-applied/kitnp6/convert_one.py.*convall" ; pkill -f "conv_only.sh /work/agentwork/cut-not-applied/kitnp6"
pkill -f "pipe.sh /work/agentwork/cut-not-applied/kitn .*pipes4/kitn"; pkill -f "pipes4/kitn/"; pkill -f "pipes4/fit/0762\|pipes4/fit/e151\|pipes4/fit/6304\|pipes4/fit/575d\|pipes4/fit/6eab\|pipes4/fit/1d89\|pipes4/fit/4518"
sleep 2; cd /work/agentwork/cut-not-applied; rm -rf convall/kitnp6 pipes4/kitn pipes4/fit/0762effe61de88c0 pipes4/fit/e151a8faacbce446 pipes4/fit/6304887153755ea3
ps -eo pid,etime,cmd | grep "[k]itnp6\|[p]ipes4" | cut -c1-160
