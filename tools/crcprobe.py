import sys
d=open(sys.argv[1],'rb').read()
def crc16(data,poly,init,refin):
    # bitwise, LSB-first if refin
    c=init
    for b in data:
        for i in range(8):
            bit=(b>>i)&1 if refin else (b>>(7-i))&1
            if refin:
                fb=(c^bit)&1; c>>=1
                if fb: c^=poly
            else:
                fb=((c>>15)^bit)&1; c=(c<<1)&0xffff
                if fb: c^=poly
    return c
# frame ending with CRC at 220550 (2 bytes) ; try lengths ending there
end=220550
for L in (296,294,298,300,292):
    blk=d[end-L:end]; st=d[end:end+2]
    for poly,refin in ((0xA001,1),(0x8005,0),(0x8408,1),(0x1021,0)):
        for init in (0,0xffff):
            c=crc16(blk,poly,init,refin)
            for v in (c, c^0xffff):
                for bo in ('little','big'):
                    if v.to_bytes(2,bo)==st: print('MATCH L',L,hex(poly),refin,hex(init),'xor' if v!=c else '',bo)
print('stored',st.hex())
