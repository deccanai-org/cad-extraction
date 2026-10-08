#!/bin/bash
# stop every process of this agent's work dir (pipelines of the old kits); other agents' processes are untouched
pkill -TERM -f "/work/agentwork/cut-not-applied/(kit|kitp)/" ; sleep 4
pkill -KILL -f "/work/agentwork/cut-not-applied/(kit|kitp)/" ; sleep 1
ps -eo pid,etime,cmd | grep "[a]gentwork/cut-not-applied" | cut -c1-160 | head
echo remaining $(ps aux | grep -c "[a]gentwork/cut-not-applied")
