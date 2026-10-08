#!/bin/bash
# ssmcli.sh REGION INSTANCE_ID SCRIPT_FILE [TIMEOUT_S]: run a local bash script on an EC2 instance through SSM (AWS-RunShellScript),
# wait for it, print "[Status]" then its stdout (stderr to stderr). SCRIPT_FILE may be /dev/stdin.
R=$1; I=$2; F=$3; T=${4:-120}
export AWS_PROFILE=${AWS_PROFILE:-annotationprod-publish}
B64=$(base64 < "$F" | tr -d '\n')
CMD="echo $B64 | base64 -d > /tmp/ssmcli_\$\$.sh && bash /tmp/ssmcli_\$\$.sh; rc=\$?; rm -f /tmp/ssmcli_\$\$.sh; exit \$rc"
P=$(python3 -c 'import json,sys; print(json.dumps({"commands": [sys.argv[1]], "executionTimeout": [sys.argv[2]]}))' "$CMD" "$T")
ID=$(aws ssm send-command --region "$R" --instance-ids "$I" --document-name AWS-RunShellScript --parameters "$P" \
     --timeout-seconds 60 --query Command.CommandId --output text) || { echo "[SendFailed]"; exit 1; }
end=$((SECONDS + T + 45)); st=Pending
while :; do
  sleep 2
  st=$(aws ssm get-command-invocation --region "$R" --command-id "$ID" --instance-id "$I" --query Status --output text 2>/dev/null)
  case "$st" in Success|Failed|Cancelled|TimedOut|Undeliverable|Terminated) break;; esac
  [ $SECONDS -gt $end ] && break
done
echo "[$st]"
aws ssm get-command-invocation --region "$R" --command-id "$ID" --instance-id "$I" --query StandardOutputContent --output text 2>/dev/null
e=$(aws ssm get-command-invocation --region "$R" --command-id "$ID" --instance-id "$I" --query StandardErrorContent --output text 2>/dev/null)
[ -n "$e" ] && [ "$e" != "None" ] && echo "$e" >&2
[ "$st" = Success ]
