#!/bin/bash
# READ-ONLY: render page 1 of each picked shop/erection drawing (range_pick.json) to JPEG: 1800 px (page view) and 2800 px (full size).
# Output /opt/report/assets/prange/. Synchronous (a few minutes).
export AWS_DEFAULT_REGION=ap-south-1
mkdir -p /opt/report/assets/prange /opt/report/work
cat > /opt/report/work/prange_pick.json <<'JSON'
[["data-3", 0, "Zenitude-data-3__Completed_Projects_Data_0102_Lundahl LIC_MT19_033 (Data Bank SLC 5).7z", "drawings/pdf/S1.00E_Overlay.pdf", 42.0, 30.0], ["data-3", 8, "Zenitude-data-3__Completed_Projects_Data_034_SOUTH CENTRAL STEEL_MT13_049 ( New Western Health Center JCDH).7z", "drawings/pdf/252-d061af.pdf", 36.0, 24.0], ["data-3", 24, "Zenitude-data-3__Completed_Projects_Data_065_The Tarrier Steel Co Inc_MT15_014(Columbus Tanger Outlets).7z", "drawings/pdf/Irrigation-Plans-2015-06-19.pdf", 34.0, 22.0], ["data-3", 40, "Zenitude-data-3__Completed_Projects_Data_065_The Tarrier Steel Co Inc_MT18_038 (Art Van Furniture).7z", "drawings/pdf/S500.pdf", 42.0, 30.0], ["data-3", 88, "Zenitude-data-3__Completed_Projects_Data_033_CIVES NEWENGLAND_MT10_037(Boston College - Stokes Hall).7z", "drawings/pdf/a414_rev_2.pdf", 42.0, 30.0], ["data-3", 126, "Zenitude-data-3__Completed_Projects_Data_038_FabArc Steel_MT13_026 (Melbourn Building).7z", "drawings/pdf/02A109-937d30.pdf", 36.0, 24.0], ["data-3", 201, "Zenitude-data-3__Completed_Projects_Data_0001Server13_Projects_05-11-2017_024_Tri State Ironworks.7z", "drawings/pdf/89-eed4e3.pdf", 36.0, 24.0], ["data-3", 213, "Zenitude-data-3__Completed_Projects_Data_039_Ben Hur Steel WorX-Hammert's Iron_MT11_012_(Continental Tire).7z", "drawings/pdf/S-101 - R3- OVERALL FOUNDATION PLAN.pdf", 48.0, 36.0], ["data-4", 349, "Zentitude-data-4__TEKLA-HYD_Backup 2026_M Drive Backup_Steel Fab_33. 32353 Burlington Classroom.7z", "drawings/pdf/Drawings\\1012C1.pdf", 67.99, 43.97], ["data-4", 586, "Zentitude-data-4__CES_PEMB_PEMB Detailing_Backup_BINCX_Standards_Standards.7z", "drawings/pdf/1809912-011-1TF.pdf", 55.08, 33.11], ["data-4", 337, "Zentitude-data-4__TEKLA-HYD_JOBS-2015-2016_10.10.40.51_Server_Backup_SDS2-TEAM_SDS-PROJECTS_0103_OzarK Steel.7z", "drawings/pdf/S110B_Overlay.pdf", 48.0, 36.0], ["data-4", 380, "Zentitude-data-4__TEKLA-HYD_PROJECT_DATA-2019-2020_HERIC_HERRICK Steel.7z", "drawings/pdf/S-0501-TYPICAL-STEEL-COLUMN-DETAILS-AND-SCHEDULES-Rev.0.pdf", 42.0, 30.0], ["data-4", 424, "Zentitude-data-4__TEKLA-HYD_JOBS-2015-2016_10.10.40.51_Server_Backup_SDS2-TEAM_SDS-PROJECTS_098_Reedbird Steel, LLC.7z", "drawings/pdf/A002_TYPICAL DETAILS.pdf", 42.0, 30.0], ["data-4", 568, "Zentitude-data-4__TEKLA-HYD_PROJECT_DATA-2021-2022_CIVES_2.Sojo South Station.7z", "drawings/pdf/cp-s203b_rev_0.pdf", 42.0, 30.0], ["data-4", 369, "Zentitude-data-4__TEKLA-HYD_JOBS-2015-2016_10.10.40.51_Server_Backup_TEKLA-TEAM_10.10.40.59-DATA_USA_PROJECTS_CMC-SC_48.AMAZON CVG HUB_02262018_Part 2_48.AMAZON CVG HUB_02262018.7z", "drawings/pdf/B13672.pdf", 36.0, 24.0], ["data-4", 386, "Zentitude-data-4__TEKLA-HYD_JOBS-2018-2019_EXCELSIORBIM.7z", "drawings/pdf/52C24 - COLUMN - Rev A_36x24-283ba0.pdf", 36.0, 24.0], ["data-4", 358, "Zentitude-data-4__TEKLA-HYD_PROJECT_DATA-2019-2020_CMC SC_12.Yokohama Tire.7z", "drawings/pdf/F2345.PDF", 36.0, 24.0], ["data-4", 492, "Zentitude-data-4__TEKLA-HYD_PROJECT_DATA-2019-2020_ESP(Engineered Steel products)_2. 20-107 Jacob Cornsilk Community Complex.7z", "drawings/pdf/JCCC lot-3 shop drwgs.pdf", 36.0, 24.0]]
JSON
/opt/report/venv/bin/python - <<'PY'
import json, boto3, fitz
s3 = boto3.client('s3'); B = 'bim-proprietary-data'; PK = 'cad-disk-extract/dataset/packages/3d_partial/'
pick = json.load(open('/opt/report/work/prange_pick.json')); meta = []
for n, (disk, i, pid, rp, w, h) in enumerate(pick, 1):
    b = s3.get_object(Bucket=B, Key=f'{PK}{pid}/{rp}')['Body'].read()
    d = fitz.open(stream=b, filetype='pdf'); p = d[0]; r = p.rect
    for width, tag in ((1800, ''), (2800, '_full')):
        z = width / max(r.width, r.height); pix = p.get_pixmap(matrix=fitz.Matrix(z, z), alpha=False)
        pix.save(f'/opt/report/assets/prange/r{n:02d}{tag}.jpg', jpg_quality=88)
    meta.append({'n': n, 'disk': disk, 'sample_i': i, 'project_id': pid, 'relpath': rp, 'w_in': w, 'h_in': h, 'pages': d.page_count, 'bytes': len(b)})
    print('RESULT', n, disk, pid[18:70], rp[:50], flush=True)
json.dump(meta, open('/opt/report/assets/prange/range.json', 'w'), indent=1)
# three-ways drawing-detail crops, rendered from the PDF at 220 dpi (fractions of the page)
pid3 = 'Zenitude-data-3__Completed_Projects_Data_000_Technical Library7_Zip Jobs_MT21_027 (2123-Moreno ES replacement).7z'
b = s3.get_object(Bucket=B, Key=f'{PK}{pid3}/drawings/pdf/3059.pdf')['Body'].read(); p = fitz.open(stream=b, filetype='pdf')[0]; r = p.rect
CROPS = {'detail_bom': (0.775, 0.015, 0.99, 0.17), 'detail_top': (0.40, 0.05, 0.575, 0.205), 'detail_base': (0.415, 0.75, 0.56, 0.925), 'detail_title': (0.69, 0.70, 0.99, 0.965)}
for name, (x0, y0, x1, y1) in CROPS.items():
    clip = fitz.Rect(r.x0 + x0 * r.width, r.y0 + y0 * r.height, r.x0 + x1 * r.width, r.y0 + y1 * r.height)
    p.get_pixmap(matrix=fitz.Matrix(220 / 72, 220 / 72), clip=clip, alpha=False).save(f'/opt/report/assets/pthree/{name}.jpg', jpg_quality=90)
    print('RESULT crop', name, flush=True)
PY
