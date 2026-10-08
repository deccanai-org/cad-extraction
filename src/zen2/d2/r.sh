#!/bin/bash
# r.sh SCRIPT.sh [timeout]  -> run on cad-zen2-files via SSM
AWS_PROFILE=annotationprod-publish /Users/dhiren/Downloads/Deccan/cad-db1-convert/venv/bin/python /Users/dhiren/Downloads/Deccan/cad-db1-convert/src/ssm.py ap-south-1 i-0afb7c16dab7a238d "$1" "${2:-300}"
