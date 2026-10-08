import pymupdf
doc=pymupdf.open(); pg=doc.new_page(width=200,height=100)
xref=doc.get_new_xref()
cs=b"q 1 0 0 1 0 0 cm 2 w 0 0 m 10 0 l 10 10 l h 20 20 m 30 20 l 30 30 l h S 40 40 m 50 40 l 50 50 l S 60 10 m 70 10 l 70 20 l 60 20 l h S 80 10 m 90 12 l 88 20 l 81 19 l h S Q"
pg.set_contents(pg.get_contents()[0]) if pg.get_contents() else None
c=doc.get_new_xref(); doc.update_object(c,"<<>>"); doc.update_stream(c,cs); doc.xref_set_key(pg.xref,"Contents",f"{c} 0 R")
for d in pg.get_drawings(extended=True):
    print(d.get('type'), d.get('closePath'), d.get('level'), [ (it[0],)+tuple(tuple(round(v,1) for v in (x if not hasattr(x,'x') else (x.x,x.y))) if not isinstance(x,(int,float)) else x for x in it[1:]) for it in d.get('items',[])])
