#!/usr/bin/env python3
"""status_composer.py - runs on cad-zen2-files: every 3 s harvest parts of hosts running older code (which overwrite
the main status file with only their own parts) into _state/d2_2d_status_parts/, then compose the full status file."""
import json, os, sys, time
sys.path.insert(0, '/work/2d')
import status
KEY = status.P + '/_state/d2_2d_status.json'
stop = time.time() + 6 * 3600
while time.time() < stop:
    try:
        d = json.loads(status.s3().get_object(Bucket=status.B, Key=KEY)['Body'].read())
        if d.get('composer') != 'cad-zen2-files':
            for k, v in (d.get('parts') or {}).items():
                if k.startswith('model_drawings_') and not os.path.exists('%s/status_%s.json' % (status.S, k)):
                    status.s3().put_object(Bucket=status.B, Key=status.P + '/_state/d2_2d_status_parts/%s.json' % k,
                                           Body=json.dumps(v, default=str).encode(), ContentType='application/json')
        status.push()
    except Exception as e:
        print(time.strftime('%T'), 'composer error', e, flush=True)
    if os.path.exists('/work/2d/state/COMPOSER_STOP'):
        break
    time.sleep(3)
