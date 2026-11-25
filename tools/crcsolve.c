#include <stdio.h>
#include <stdint.h>
int main(){unsigned char d[298];FILE*f=fopen("fuzz/delta.bin","rb");fread(d,1,298,f);
 int n=296; uint16_t tgt_le=d[296]|d[297]<<8, tgt_be=d[297]|d[296]<<8;
 for(int refin=0;refin<2;refin++)for(uint32_t p=1;p<65536;p++){uint16_t c=0;
  for(int i=0;i<n;i++)for(int k=0;k<8;k++){int bit=refin?(d[i]>>k)&1:(d[i]>>(7-k))&1;
   if(refin){int fb=(c^bit)&1;c>>=1;if(fb)c^=p;}else{int fb=((c>>15)^bit)&1;c<<=1;if(fb)c^=p;}}
  for(int r=0;r<2;r++){uint16_t v=r?(uint16_t)(((c&1)?0:0)):c; if(r){v=0;for(int k=0;k<16;k++)if(c>>k&1)v|=1<<(15-k);}
   if(v==tgt_le||v==tgt_be)printf("refin=%d poly=%04x rev=%d %s\n",refin,p,r,v==tgt_le?"le":"be");}}
}
