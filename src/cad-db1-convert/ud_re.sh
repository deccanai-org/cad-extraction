#!/bin/bash
exec > /var/log/db1v2-boot.log 2>&1
dnf install -y python3.11 python3.11-pip >/dev/null 2>&1
python3.11 -m pip install -q boto3 numpy ifcopenshell
mkdir -p /opt/db1v2/src && echo READY > /opt/db1v2/ready
