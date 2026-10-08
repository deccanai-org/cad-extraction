#!/usr/bin/env python3
"""add exact-vs-approximate notes + clip/annotation stats to the pdf status part."""
import json, sys, collections
sys.path.insert(0, '/work/2d')
import status
recs = {}
for l in open('/work/2d/state/pdf_results.jsonl'):
    r = json.loads(l)
    recs[r['sha256']] = r
pages = [p for r in recs.values() for p in r.get('pages', [])]
agg = collections.Counter()
for p in pages:
    st = p.get('stats', {})
    for k in ('clip_nonrect', 'clipped_paths', 'flattened_beziers_in_clip', 'dashes', 'transparent', 'annotations_baked',
              'annot_paths', 'image', 'text', 'spline', 'hatch', 'lwpolyline', 'line'):
        agg[k] += st.get(k, 0) if isinstance(st.get(k, 0), int) else 0
    agg['pages_with_nonrect_clip'] += 1 if st.get('clip_nonrect') else 0
    agg['pages_with_annotations'] += 1 if st.get('annotations_baked') else 0
s = json.load(open('/work/2d/state/status_pdf.json'))
s['entity_totals_distinct_pages'] = dict(agg)
s['fidelity'] = {
    'exact': ['page size and coordinates (1 pt = 25.4/72 mm, origin lower-left, float64)',
              'straight segments, rectangles, quads (LWPOLYLINE/LINE)',
              'cubic Beziers -> degree-3 SPLINE with the PDF control points (identical curve)',
              'fill boundaries not crossing a clip (HATCH polyline / line+spline edge paths)',
              'stroke/fill/text RGB colours (true colour on layers), content-stream draw order',
              'text string, baseline origin and rotation; image placement matrix (IMAGE u/v vectors)'],
    'approximate': ['lineweight snapped to the nearest DXF standard weight (exact width kept in the layer name S_<rgb>_W<mm>)',
                    'geometry crossing a clip rectangle is clipped (Beziers there flattened to ~0.01 mm); '
                    'non-rectangular clips use their bounding box',
                    'non-zero-winding fills written as odd-parity HATCH; blend modes ignored; opacity -> DXF transparency',
                    'dash patterns (97 dashed strokes in the set) written as DXF linetypes with lengths converted from pt (CTM scaling ignored)',
                    'fonts: DXF styles reference arial*.ttf / arialn*.ttf / romans|romant.shx; TEXT height = font size x '
                    'cap-height of the embedded font, width factor calibrated so the advance matches the PDF',
                    'line caps/joins not represented; images are PNG side files next to the DXF (page-<n>_img<k>.png)',
                    '384 distinct PDFs carry review annotations (Square/FreeText/Line/Ink/Circle/Highlight/Stamp): they were '
                    're-run with the annotations flattened (MuPDF bake). Raster stamps are recovered as IMAGE entities '
                    '(this fixed the 4 TEC "_commented" sheets: 0.60 -> 0.97); vector/FreeText annotation appearances are '
                    'not recovered by PyMuPDF from the baked forms, so they are listed per page (type, text, rect mm) in '
                    'json/drawings/<relpath>.json -> pages[].annotations instead of being drawn in the DXF'],
    'validation_render': 'ezdxf drawing add-on (PyMuPDF backend, lineweight ABSOLUTE, min 1 px) rasterised on the pdftoppm '
                         '150-dpi grid; substitute fonts Liberation Sans/Serif/Narrow for rendering only',
}
status.put_part('pdf', s)
print(dict(agg))
