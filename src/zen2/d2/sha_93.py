import sys, struct, olefile
sys.path.insert(0,'/work/2d'); import sha2dxf as S
dec=S.Decoder('/work/in/src/'+sys.argv[1])
n=0
for st in ['JSite4758','','JSite4756']:
  for sn in dec.sheet_streams(st):
    for t,p in S.recs(dec.o.openstream(sn).read()):
        if t&0x7fff==93 and n<3:
            n+=1; c=struct.unpack_from('<I',p,18)[0]; off=22
            pts=[struct.unpack_from('<2d',p,off+16*i) for i in range(c)]; off+=16*c
            w=struct.unpack_from('<%dd'%c,p,off); off+=8*c
            rest=p[off:]
            print(len(p),'n',c,'pts0',pts[0],'w',[round(x,3) for x in w],'rest',len(rest), rest[:8].hex(), [round(struct.unpack_from('<d',rest,k)[0],4) for k in range(4,len(rest)-7,8)][:16], rest[-12:].hex())
        if t&0x7fff==132 and n<6:
            n+=1; c=struct.unpack_from('<I',p,18)[0]; print('132',len(p),'n',c,p[22:24].hex(),[tuple(round(v,4) for v in struct.unpack_from('<2d',p,24+16*i)) for i in range(min(c,5))], p[24+16*c:].hex())
