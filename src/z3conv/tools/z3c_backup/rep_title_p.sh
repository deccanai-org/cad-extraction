#!/bin/bash
# READ-ONLY: re-render the three-ways title-block crop (taller) from the PDF at 220 dpi
export AWS_DEFAULT_REGION=ap-south-1
/opt/report/venv/bin/python - <<'PY'
import boto3, fitz
s3 = boto3.client('s3'); B = 'bim-proprietary-data'; PK = 'cad-disk-extract/dataset/packages/3d_partial/'
pid3 = 'Zenitude-data-3__Completed_Projects_Data_000_Technical Library7_Zip Jobs_MT21_027 (2123-Moreno ES replacement).7z'
b = s3.get_object(Bucket=B, Key=f'{PK}{pid3}/drawings/pdf/3059.pdf')['Body'].read(); p = fitz.open(stream=b, filetype='pdf')[0]; r = p.rect
x0, y0, x1, y1 = 0.775, 0.70, 0.99, 0.985
clip = fitz.Rect(r.x0 + x0 * r.width, r.y0 + y0 * r.height, r.x0 + x1 * r.width, r.y0 + y1 * r.height)
p.get_pixmap(matrix=fitz.Matrix(220 / 72, 220 / 72), clip=clip, alpha=False).save('/opt/report/assets/pthree/detail_title.jpg', jpg_quality=90)
print('RESULT ok')
PY
aws s3 cp --only-show-errors /opt/report/assets/pthree/detail_title.jpg s3://bim-proprietary-data/cad-disk-extract/_state/report/assets/pthree/detail_title.jpg
