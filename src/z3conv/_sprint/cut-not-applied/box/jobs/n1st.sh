#!/bin/bash
cd /work/agentwork/cut-not-applied; echo "kitn $(ls convall/kitn/*/conv.json 2>/dev/null | wc -l) kitnp $(ls convall/kitnp/*/conv.json 2>/dev/null | wc -l) of $(wc -l < res/convn.lst)"; cat res/patch_kitnp.txt | tail -2; uptime
tail -3 logs/n1.log
