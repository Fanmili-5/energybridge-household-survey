"""Bounded, session/request-bound local raster challenge for ordinary scripts.

This is not identity verification or resistance to modern OCR. Quotas and
admission limits remain the cost boundary. No answers are sent to the browser.
"""
import base64
from collections import OrderedDict
import hashlib
import hmac
import secrets
import struct
import threading
import time
import zlib

# Small original bitmap alphabet; omit easily confused 0/O, 1/I/L, 5/S, 8/B.
GLYPHS={
 '2':['01110','10001','00001','00010','00100','01000','11111'],
 '3':['11110','00001','00001','01110','00001','00001','11110'],
 '4':['00010','00110','01010','10010','11111','00010','00010'],
 '6':['00110','01000','10000','11110','10001','10001','01110'],
 '7':['11111','00001','00010','00100','01000','01000','01000'],
 '9':['01110','10001','10001','01111','00001','00010','01100'],
 'A':['01110','10001','10001','11111','10001','10001','10001'],
 'C':['01111','10000','10000','10000','10000','10000','01111'],
 'D':['11110','10001','10001','10001','10001','10001','11110'],
 'E':['11111','10000','10000','11110','10000','10000','11111'],
 'F':['11111','10000','10000','11110','10000','10000','10000'],
 'H':['10001','10001','10001','11111','10001','10001','10001'],
 'J':['00111','00010','00010','00010','10010','10010','01100'],
 'K':['10001','10010','10100','11000','10100','10010','10001'],
 'M':['10001','11011','10101','10101','10001','10001','10001'],
 'N':['10001','11001','10101','10011','10001','10001','10001'],
 'P':['11110','10001','10001','11110','10000','10000','10000'],
 'R':['11110','10001','10001','11110','10100','10010','10001'],
 'T':['11111','00100','00100','00100','00100','00100','00100'],
 'U':['10001','10001','10001','10001','10001','10001','01110'],
 'W':['10001','10001','10001','10101','10101','11011','10001'],
 'X':['10001','10001','01010','00100','01010','10001','10001'],
 'Y':['10001','10001','01010','00100','00100','00100','00100'],
}

class CaptchaError(ValueError):
    pass


def raster_png(code):
    width,height=216,64
    pixels=bytearray([247,250,247]*(width*height))
    def pixel(x,y,color):
        if 0<=x<width and 0<=y<height:
            at=(y*width+x)*3;pixels[at:at+3]=bytes(color)
    for _ in range(180):pixel(secrets.randbelow(width),secrets.randbelow(height),(175,199,187))
    for i,char in enumerate(code):
        scale=4;x0=10+i*34+secrets.randbelow(4);y0=13+secrets.randbelow(10)
        color=(25+secrets.randbelow(30),65+secrets.randbelow(35),50+secrets.randbelow(35))
        slope=secrets.choice([-1,0,1])
        for y,row in enumerate(GLYPHS[char]):
            for x,on in enumerate(row):
                if on=='1':
                    for dy in range(scale):
                        for dx in range(scale):pixel(x0+x*scale+dx+slope*(y-3)//2,y0+y*scale+dy,color)
    raw=b''.join(b'\0'+pixels[y*width*3:(y+1)*width*3] for y in range(height))
    def chunk(kind,body):return struct.pack('!I',len(body))+kind+body+struct.pack('!I',zlib.crc32(kind+body)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')


class LocalCaptcha:
    ttl=180
    max_attempts=3
    max_entries=5000
    def __init__(self):
        self.secret=secrets.token_bytes(32)
        self.entries=OrderedDict()
        self.lock=threading.Lock()
        self._new_code=lambda:''.join(secrets.choice(tuple(GLYPHS)) for _ in range(6))

    def _digest(self,cid,code):return hmac.new(self.secret,(cid+':'+code).encode(),hashlib.sha256).digest()

    def issue(self,owner,request_id):
        import re
        if not isinstance(request_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',request_id):raise CaptchaError('提交标识无效，请重试生成')
        now=time.monotonic()
        with self.lock:
            stale=[k for k,v in self.entries.items() if v['expires']<=now]
            for k in stale:del self.entries[k]
            previous=[k for k,v in self.entries.items() if v['owner']==owner]
            if any(now-self.entries[k]['issued']<2 for k in previous):raise OverflowError('验证码刷新过快，请稍等两秒')
            for k in previous:del self.entries[k]
            if len(self.entries)>=self.max_entries:raise OverflowError('验证请求较多，请稍后再试')
            cid=secrets.token_hex(24);code=self._new_code()
            self.entries[cid]={'owner':owner,'request_id':request_id,'digest':self._digest(cid,code),
                               'expires':now+self.ttl,'issued':now,'attempts':0}
        return {'id':cid,'image':'data:image/png;base64,'+base64.b64encode(raster_png(code)).decode(),
                'expires_in':self.ttl,'length':6}

    def consume(self,owner,request_id,proof):
        if not isinstance(proof,dict):raise CaptchaError('请完成图片验证码后再生成')
        cid=proof.get('id');answer=proof.get('answer')
        if not isinstance(cid,str) or not isinstance(answer,str) or len(answer)>32:raise CaptchaError('验证码格式无效，请换一张重试')
        with self.lock:
            row=self.entries.get(cid)
            if not row or row['expires']<=time.monotonic():
                self.entries.pop(cid,None);raise CaptchaError('验证码已过期或已使用，请换一张')
            if row['owner']!=owner or row['request_id']!=request_id:raise CaptchaError('验证码与本次提交不匹配，请换一张')
            row['attempts']+=1
            valid=hmac.compare_digest(row['digest'],self._digest(cid,answer.strip().upper()))
            if valid or row['attempts']>=self.max_attempts:self.entries.pop(cid,None)
            if not valid:raise CaptchaError('验证码不正确，请重试；连续错误三次后需换一张')
