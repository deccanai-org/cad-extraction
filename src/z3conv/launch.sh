#!/bin/bash
# launch.sh REGION_KEY TYPE COUNT ROOT_GB NAME PIPE [SUBNET_INDEX]
export AWS_PROFILE=${AWS_PROFILE:-annotationprod-publish}
case $1 in
  M) R=ap-south-1; AMI=ami-0ee11497c4eac651d; SG=sg-04a594766aa42b691; SUBS=(subnet-0eeba63763d7eb0da subnet-0540cf3953564acb7);;
  H) R=ap-south-2; AMI=ami-003ed75f7a31e8f3d; SG=sg-018b6284e7a0e0aee; SUBS=(subnet-0caf1128706834be5 subnet-0b39b75c41778cb27);;
  # (owner 10-03 01:15Z) Singapore: default VPC vpc-05a01123e8fba5e27 (public-IP subnets 1a/1b/1c), AL2023 x86_64; no SG given ->
  # the VPC default security group (all egress; S3 in ap-south-1 is reached cross-region over the internet)
  S) R=ap-southeast-1; AMI=ami-01a395a37625fb28c; SG=; SUBS=(subnet-0ac4084aced16aa1c subnet-05575030bee2c6a00 subnet-06cee8e57dff09788);;
  *) echo "region key M / H / S"; exit 1;;
esac
SUB=${SUBS[${7:-0}]}
UD=$6/userdata.sh; [ "$6" = coord ] && UD=ud/ud_coord.sh
aws ec2 run-instances --region $R --image-id $AMI --instance-type $2 --count $3 --subnet-id $SUB --security-group-ids $SG \
  --iam-instance-profile Name=cad-disk-extract-ec2 --instance-initiated-shutdown-behavior terminate --metadata-options HttpTokens=required \
  --block-device-mappings "[{\"DeviceName\":\"/dev/xvda\",\"Ebs\":{\"VolumeSize\":$4,\"VolumeType\":\"gp3\",\"Iops\":6000,\"Throughput\":${THRU:-500},\"DeleteOnTermination\":true}}]" \
  --user-data file://$UD --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$5},{Key=Project,Value=cad-disk-extract}]" \
  --query 'Instances[].[InstanceId,InstanceType,Placement.AvailabilityZone]' --output text
