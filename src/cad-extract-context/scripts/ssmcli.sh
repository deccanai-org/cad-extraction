#!/bin/bash
# ssmcli.sh REGION INSTANCE_ID SCRIPT_FILE [TIMEOUT]  (AWS CLI; boto3 here cannot refresh the SSO token)
R=$1; I=$2; F=$3; T=${4:-120}
P=$(python3 -c "import json,sys; print(json.dumps({'commands':[open(sys.argv[1]).read()],'executionTimeout':[sys.argv[2]]}))" "$F" "$T")
C=$(AWS_PROFILE=annotationprod-publish aws ssm send-command --region $R --instance-ids $I --document-name AWS-RunShellScript --parameters "$P" --query Command.CommandId --output text) || exit 1
for i in $(seq 1 $((T/4+15))); do
  sleep 4
  S=$(AWS_PROFILE=annotationprod-publish aws ssm get-command-invocation --region $R --command-id $C --instance-id $I --query Status --output text 2>/dev/null)
  case "$S" in Pending|InProgress|Delayed|"") continue;; esac
  echo "[$S]"; AWS_PROFILE=annotationprod-publish aws ssm get-command-invocation --region $R --command-id $C --instance-id $I --query StandardOutputContent --output text; break
done
