#!/bin/bash
# Relaunch the DB1->STEP fleet (new code is picked up from S3 by the user-data loop).
# Mumbai: N_MUM x r7i.16xlarge (+ the running 96-vCPU cad-db1-re box) must stay <= 700 vCPU (team cap).
# Hyderabad: N_HYD x r7i.16xlarge within the 320 vCPU quota (lead's hyd-medium/hyd-status use 18).
set -e
cd /Users/dhiren/Downloads/Deccan/cad-db1-convert
export AWS_PROFILE=${AWS_PROFILE:-annotationprod-publish}
N_MUM=${N_MUM:-9}; N_HYD=${N_HYD:-4}
# vCPU guard for Mumbai: count our running cad instances first
USED=$(aws ec2 describe-instances --region ap-south-1 --filters "Name=instance-state-name,Values=running,pending" "Name=tag:Project,Values=cad,cad-disk-extract" \
  --query 'Reservations[].Instances[].CpuOptions.[CoreCount,ThreadsPerCore]' --output text | awk '{s+=$1*$2} END {print s+0}')
NEED=$((N_MUM*64))
echo "mumbai cad vCPU in use: $USED, adding $NEED -> $((USED+NEED)) (cap 700)"
if [ $((USED+NEED)) -gt 700 ]; then echo "would exceed the 700 vCPU Mumbai cap - aborting"; exit 1; fi
aws ec2 run-instances --region ap-south-1 --image-id ami-0ee11497c4eac651d --instance-type r7i.16xlarge --count $N_MUM \
  --subnet-id subnet-0eeba63763d7eb0da --security-group-ids sg-088de8e930b87b429 --iam-instance-profile Name=cad-disk-extract-ec2 \
  --instance-initiated-shutdown-behavior terminate --user-data file://ud_db1_mumbai.sh \
  --block-device-mappings '[{"DeviceName":"/dev/xvda","Ebs":{"VolumeSize":500,"VolumeType":"gp3","Iops":6000,"Throughput":500,"DeleteOnTermination":true}}]' \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=cad-db1-step-mum},{Key=Project,Value=cad}]' \
  --query 'Instances[].InstanceId' --output text
if [ "$N_HYD" -gt 0 ]; then
  SUB=$(aws ec2 describe-subnets --region ap-south-2 --filters Name=default-for-az,Values=true Name=availability-zone,Values=ap-south-2b --query 'Subnets[0].SubnetId' --output text)
  SG=$(aws ec2 describe-security-groups --region ap-south-2 --filters Name=group-name,Values=default --query 'SecurityGroups[0].GroupId' --output text)
  echo "hyderabad subnet $SUB sg $SG"
  aws ec2 run-instances --region ap-south-2 --image-id ami-0d810b4169227c0ca --instance-type r7i.16xlarge --count $N_HYD \
    --subnet-id $SUB --security-group-ids $SG --iam-instance-profile Name=cad-disk-extract-ec2 \
    --instance-initiated-shutdown-behavior terminate --user-data file://ud_db1.sh \
    --block-device-mappings '[{"DeviceName":"/dev/xvda","Ebs":{"VolumeSize":500,"VolumeType":"gp3","Iops":6000,"Throughput":500,"DeleteOnTermination":true}}]' \
    --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=cad-db1-step},{Key=Project,Value=cad}]' \
    --query 'Instances[].InstanceId' --output text
fi
# the 96-vCPU box has no restart loop: restart its worker on the new code
venv/bin/python src/ssm.py ap-south-1 i-0d44873a4951075f7 src/restart_db1_re.sh 200 2>&1 | tail -3
