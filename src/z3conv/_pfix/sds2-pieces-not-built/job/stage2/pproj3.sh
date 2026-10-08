W=/work/agentwork/sds2-pieces-not-built
grep -v " ok\| cached" $W/out/proj.log | head; ls $W/out/PROJ_DONE 2>/dev/null; pgrep -f project_all.py
