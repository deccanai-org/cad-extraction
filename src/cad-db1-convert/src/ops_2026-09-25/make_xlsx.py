"""Minimal .xlsx writer (no dependencies): one sheet per table, bold frozen header, column widths, wrapped text."""
import csv, os, zipfile
from xml.sax.saxutils import escape
S = "/Users/dhiren/Downloads/Deccan/cad-db1-convert/report_final/out/simple"
OUT = "/Users/dhiren/Downloads/Deccan/cad-db1-convert/report_final/out/simple/Locked_and_Damaged_Files.xlsx"
rd = lambda f: list(csv.reader(open(os.path.join(S, f), newline="")))
t1, t2, t3 = rd("1_Password_locked_by_archive.csv"), rd("3_Could_not_open_damaged.csv"), rd("2_Password_locked_zip_files.csv")
z = sum(int(r[1]) for r in t1[1:]); f = sum(int(r[2]) for r in t1[1:])
sheets = [
 ("Summary", [["What", "Count"], ["Archives received", "3,620"], ["Archives opened and processed", "3,620 (all)"],
              ["Archives with password-locked files inside", str(len(t1) - 1)], ["Password-locked zip files", f"{z:,} ({f:,} files inside)"],
              ["Damaged files we could not open", f"{len(t2) - 1} (in {len({r[0] for r in t2[1:]})} archives)"]], [46, 30]),
 ("Password-locked by archive", [["#"] + t1[0]] + [[i] + [r[0], int(r[1]), int(r[2])] for i, r in enumerate(t1[1:], 1)]
                                 + [["", f"Total: {len(t1) - 1} archives", z, f]], [6, 100, 18, 20]),
 ("Damaged files", [["#"] + t2[0]] + [[i] + r for i, r in enumerate(t2[1:], 1)], [6, 70, 70, 45, 30]),
 ("All locked zip files", [["#"] + t3[0][:4]] + [[i, r[0], r[1], r[2], int(r[3])] for i, r in enumerate(t3[1:], 1)], [7, 70, 80, 50, 18]),
]
def col(n):
    s = ""
    while n: n, r = divmod(n - 1, 26); s = chr(65 + r) + s
    return s
def sheet_xml(rows, widths):
    cols = "".join(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths, 1))
    out = []
    for ri, row in enumerate(rows, 1):
        cells = []
        for ci, v in enumerate(row, 1):
            ref = f"{col(ci)}{ri}"; st = 1 if ri == 1 else 2
            if isinstance(v, int): cells.append(f'<c r="{ref}" s="{st}"><v>{v}</v></c>')
            else: cells.append(f'<c r="{ref}" s="{st}" t="inlineStr"><is><t xml:space="preserve">{escape(str(v))}</t></is></c>')
        out.append(f'<row r="{ri}">{"".join(cells)}</row>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
            f'<cols>{cols}</cols><sheetData>{"".join(out)}</sheetData></worksheet>')
styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
          '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
          '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
          '<fill><patternFill patternType="solid"><fgColor rgb="FFE8EEED"/><bgColor indexed="64"/></patternFill></fill></fills>'
          '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
          '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
          '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
          '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
          '<xf numFmtId="3" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf></cellXfs>'
          '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zf:
    zf.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, len(sheets) + 1))
        + '</Types>')
    zf.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    zf.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
        + "".join(f'<sheet name="{escape(n)}" sheetId="{i}" r:id="rId{i}"/>' for i, (n, _, _) in enumerate(sheets, 1)) + '</sheets></workbook>')
    zf.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets) + 1))
        + f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
    zf.writestr("xl/styles.xml", styles)
    for i, (_, rows, widths) in enumerate(sheets, 1): zf.writestr(f"xl/worksheets/sheet{i}.xml", sheet_xml(rows, widths))
print("written", OUT, os.path.getsize(OUT), "bytes;", [(n, len(r) - 1) for n, r, _ in sheets])
