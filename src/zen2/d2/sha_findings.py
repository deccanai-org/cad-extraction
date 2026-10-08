#!/usr/bin/env python3
"""record the .sha structure findings in the status file (part sha_json)."""
import json, sys
sys.path.insert(0, '/work/2d')
import status

F = {
    'container': 'OLE2 compound file (root CLSID F66621A2-5ED9-11D2-AB1F-080036AA2104 = SmartSketch/Smart 3D sheet '
                 'document; DocVersion3 names "shape2dserver.a"). Every file: TaggedTxtData/* (12 XML streams: '
                 'TitleArea, Revision, Custom, Configuration, Notes, SignatureArea, Structure, Style, General, '
                 'ProfileSketch, MHEPDRCustom, TitleBlockInfo), OLE SummaryInformation (661/669), PSM object store '
                 '(PSMcluster0, PSMclustertable, PSMroots, PSMsegmenttable, PSMspacemap/*), StyleCluster, '
                 'Dynamic Attributes, Sheet<N> streams and nested JSite<N> storages (embedded sub-documents).',
    'record_stream': 'Sheet<N> / PSMcluster0 / StyleCluster / Unclustered Dynamic Attributes = magic 44 f5 90 6c, '
                     'u32 record count, records [u16 type][u32 length][payload] that parse every stream exactly to its '
                     'end (verified on all 669 distinct files); type bit 0x8000 is a flag with an identical layout. '
                     'Payload header: u32 object id, u32 owner id, u32 layer id, u16 flags, u32 style index. '
                     'No compression: coordinates are plain little-endian float64 in metres.',
    'sub_documents': 'type 61 = placed sub-document: JSite id (u32 @156) + transform a b c d tx ty s (7 doubles @164). '
                     'Root sheet places the drawing view (e.g. s = 0.004 for 1:250; view geometry is stored in plant/model '
                     'metres) and the border sheet (identity), which in turn places key plan, north arrow and logos '
                     '(static DIB pictures, CLSID 00000316-...). Composing these transforms puts decoded lines within '
                     '0.05 mm of the PDF plot for 95% of endpoints (all within 0.2 mm) on the test sheet.',
    'decoded_types': {'24 (50 B)': 'line x1 y1 x2 y2', '89': 'circle cx cy r', '97/99': 'circular arc cx cy r a0 a1',
                      '126': 'elliptical arc p0 p1 cx cy major-axis(x,y) ratio', '61': 'placed view/sub-document',
                      '77': 'text box: UTF-16 runs, anchor x y + cos/sin rotation + justification byte (high nibble '
                            'left/centre/right, low nibble 1 top / 5 middle / 0 baseline); XML runs '
                            '<intstgxml stream= select=/> are title-block fields resolved from TaggedTxtData',
                      '129 (PSMcluster0)': 'layer: id -> name (STRUCT, LIGHT, piping layers, ...)',
                      '46/48 (StyleCluster)': 'line style: width in metres', '44 (StyleCluster)': 'font record: face + height',
                      '45 (StyleCluster)': 'text style -> font record index'},
    'not_decoded': {'text size/font': 'run/style indirection gives RomanS 2.5 mm where the plot shows Arial 3.1-12.6 mm, '
                                      'so heights are not reliable -> texts exported as JSON (string, anchor, rotation, '
                                      'justification) and NOT as DXF TEXT',
                    '132 / 19': '132 polygon outlines decoded (u32 n, 2 flag bytes, n points @24) but fill style not; 19 paths not decoded', '93': 'rational B-splines (count, points, weights, knots)',
                    '123': 'graphic groups / symbol containers (u16 bbox index)', '24 (66 B)': 'symbol-local lines',
                    '206 / 250 / 277 / 280 / 32 / 33 / 6 / 94': 'dimensions, labels, frames, points (layouts unknown)',
                    'colours / linetypes': 'style records 42/47/50/52/72/90/278 not mapped',
                    'pictures': 'JSite CONTENTS = BMP (static DIB); placement extents in the type-61 record not mapped'},
    'what_a_full_decoder_needs': 'about 2-4 more days of reverse engineering against the PDF plots: the text style / '
                                 'run model (font, height, width factor, multi-line layout), fill and hatch records, '
                                 'B-spline records, symbol instancing (123 groups + 66-byte lines), dimension and label '
                                 'objects, colour and linetype tables, picture placement. The alternative is a Smart 3D '
                                 '/ SmartSketch installation (Hexagon licence) to export DWG/DXF directly.',
}

s = json.load(open('/work/2d/state/status_sha_json.json'))
s['graphics_findings'] = F
status.put_part('sha_json', s)
print('ok')
