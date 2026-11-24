# ruff: noqa
"""Corre el escáner REAL (cedula-foto.js + cedula-readers.js) en Chrome sin pantalla, con cada foto como cámara simulada. Ver LEEME.md."""
import sys, os, json, time, numpy as np, cv2, urllib.request
from playwright.sync_api import sync_playwright
CAM=os.path.join(os.environ.get('LAB_OUT','/tmp/lab_cedula'),'cam.y4m'); CHROME=os.environ.get('CHROME','/usr/bin/google-chrome')
def y4m(png, out):
    im=cv2.imread(png); h,w=im.shape[:2]; yuv=cv2.cvtColor(im,cv2.COLOR_BGR2YUV_I420)
    with open(out,'wb') as f:
        f.write(f'YUV4MPEG2 W{w} H{h} F30:1 Ip A1:1 C420jpeg\n'.encode())
        for _ in range(3): f.write(b'FRAME\n'); f.write(yuv.tobytes())
    return w,h
def one(png, kind='new', ev='', view=(400,700), wait=40):
    w,h=y4m(png,CAM)
    with sync_playwright() as p:
        b=p.chromium.launch(executable_path=CHROME,args=['--no-sandbox','--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream','--use-file-for-fake-video-capture='+CAM+''])
        pg=b.new_page(viewport={'width':view[0]+40,'height':view[1]+120}); pg.goto(f'http://127.0.0.1:8765/page?kind={kind}&ev={ev}&w={view[0]}&h={view[1]}')
        pg.wait_for_function('document.getElementById("v").videoWidth>0 && !document.getElementById("b").disabled',timeout=20000)
        vw=pg.evaluate('[v.videoWidth,v.videoHeight]'); time.sleep(.6)
        t0=time.time(); pg.click('#b')
        try: pg.wait_for_function('window.RESULT!==undefined || (LOG.length && LOG[LOG.length-1][1]==="err") ',timeout=wait*1000)
        except Exception: pass
        dt=time.time()-t0; res=pg.evaluate('window.RESULT'); log=pg.evaluate('window.LOG'); ocrn=pg.evaluate('window.OCRN||0'); b.close()
    return dict(video=vw,res=res,sec=round(dt,1),last=log[-1] if log else None,ocr=ocrn,errs=[l for l in log if l[1] in('JSERR','REJ')])
if __name__=='__main__':
    d=sys.argv[1]; names=sys.argv[2:] or sorted(f[:-4] for f in os.listdir(d) if f.endswith('.png'))
    ev=os.environ.get('EV',''); ok=0
    for n in names:
        r=one(f'{d}/{n}.png',ev=ev,kind=os.environ.get('KIND','new')); good=bool(r['res'] and r['res'].get('cedula')=='1013259208'); ok+=good
        print(n.ljust(16),'OK ' if good else 'FALLA', r['sec'],'s','ocr',r['ocr'],'video',r['video'], (r['res'] or {}).get('nombre1',''), (r['res'] or {}).get('origen',''),'' if good else r['last'], r['errs'] or '')
    print(f'{ok}/{len(names)}')
