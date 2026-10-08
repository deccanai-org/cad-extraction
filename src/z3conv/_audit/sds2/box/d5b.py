#!/usr/bin/env python3
"""D5b: the deployed v5.4 converter on every v4 class-1 job (main-member holes: mating_holes_not_stored / derived holes)."""
import os, sys, json
sys.argv = [sys.argv[0]]
import diag
diag.D = f'{diag.W}/diag54'; diag.OUTP = diag.OUTP.replace('/diag', '/diag54'); diag.PIPE = f'{diag.W}/v54/sds2-step-pipeline'
os.makedirs(diag.D, exist_ok=True)
diag.d5()
diag.log('D5b ALL DONE')
diag.s3.put_object(Bucket=diag.B, Key=f'{diag.OUTP}/DONE', Body=b'done')
