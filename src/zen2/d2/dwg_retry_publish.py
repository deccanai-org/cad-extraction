#!/usr/bin/env python3
"""publish the retried DWG->DXF (ODA File Converter 27.9, headless via xvfb) to dxf/<relpath>.dxf + status part"""
import json, os, subprocess, sys
sys.path.insert(0, '/work/2d'); import status
rel = 'Re-Submission/04-05-2026/SECTION-F/P16093-16-01-21-1604/Related File/P16093-16-01-21-1604.dwg'
src = '/work/2d/dwg_retry/oda_out/P16093-16-01-21-1604.dxf'
key = 's3://annotationprod/cad-disk-extract/zenitude-data-2/dxf/' + rel + '.dxf'
rc = subprocess.call(['aws', 's3', 'cp', '--only-show-errors', src, key])
v = json.load(open('/work/2d/state/dwg_retry_validate.json'))
va = v['dwg_retry/oda_out/P16093-16-01-21-1604.dxf']
vb = v['dwg_retry/ldwg14/P16093-16-01-21-1604.dxf']
info = {rel: {'s3': key, 'converter': 'ODA File Converter 27.9.0 (ACAD2018 DXF, audit on, xvfb-run)', 'upload_rc': rc,
              'bytes': os.path.getsize(src),
              'note': 'LibreDWG 0.13.3 failed: AcDs data section "Invalid num_segidx" (READ ERROR 0xd40); '
                      'LibreDWG 0.14 (2026-06) wrote a DXF but logged 3,336 decode errors and ezdxf cannot read it '
                      '(%s)' % vb.get('error'),
              'validation': va}}
json.dump(info, open('/work/2d/state/dwg_retry.json', 'w'), indent=1)
status.put_part('dwg_retry', {'stage': 'done', 'failed_before': 1, 'recovered': 1 if rc == 0 else 0,
                              'file': rel, 'output': key, 'converter': info[rel]['converter'],
                              'validation': {k: va.get(k) for k in ('dxfversion', 'recover_errors', 'recover_fixes',
                                                                    'audit_errors', 'status')},
                              'modelspace_entities': va['layouts']['Model']['entities'],
                              'libredwg_0_13_3': 'failed: AcDs Invalid num_segidx',
                              'libredwg_0_14': '3,336 decode errors; output unreadable by ezdxf (%s)' % vb.get('error')})
print('rc', rc)
