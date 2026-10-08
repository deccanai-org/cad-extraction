import sys, struct, olefile
SRC='/work/in/src/'
o=olefile.OleFileIO(SRC+sys.argv[1]); b=o.openstream(sys.argv[2]).read(); target=int(sys.argv[3])
k=8
while k+6<=len(b):
    t,ln=struct.unpack_from('<HI',b,k)
    if k<=target<k+6+ln:
        p=b[k+6:k+6+ln]; print('record type',t,'len',ln,'at',k,'target rel',target-k-6)
        print('u32:', [struct.unpack_from('<I',p,i)[0] for i in range(0,min(len(p),40),4)])
        print('hex:', p.hex())
        break
    k+=6+ln
# list all records of that type in the stream
k=8; n=0
while k+6<=len(b):
    t2,ln2=struct.unpack_from('<HI',b,k)
    if t2==t: n+=1
    k+=6+ln2
print('records of type',t,':',n)
