#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
static unsigned char d[800000];
uint16_t crc(const unsigned char*p,int n,uint16_t c){for(int i=0;i<n;i++){c^=p[i];for(int k=0;k<8;k++)c=(c&1)?(c>>1)^0xA001:c>>1;}return c;}
int main(int a,char**v){FILE*f=fopen(v[1],"rb");int n=fread(d,1,sizeof d,f);int e=atoi(v[2]);
 uint16_t st=d[e]|d[e+1]<<8;
 for(int L=290;L<=298;L++)for(uint32_t i=0;i<65536;i++){if(crc(d+e-L,L,i)==st)printf("L=%d init=%04x\n",L,i);}
 /* check across frames with found init */
}
