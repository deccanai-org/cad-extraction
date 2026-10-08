#!/bin/bash
ps -eo pid,etime,rss,args --sort=-rss | head -12 | cut -c1-170
