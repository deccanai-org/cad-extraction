# Hyderabad hosts run the worker under a restart loop: killing it restarts it with fresh code
pkill -f "[p]ython3 /opt/db1v2/db1_worker.py"; pkill -f "[c]onvert_one.py"; pkill -f "[i]fc2step5.py"; sleep 3
rm -rf /opt/db1v2/jobs /opt/db1v2/src; echo restarted-by-loop
