#!/bin/bash
# kill my own runaway converter (Seaport, 158 GB RSS) and its verifier children
P=332846
ps -o pid,rss,args -p $P | cut -c1-150
pkill -9 -P $P 2>/dev/null; kill -9 $P 2>/dev/null
sleep 3
ps -o pid,rss,args -p $P | cut -c1-150 || true
free -g | head -2
