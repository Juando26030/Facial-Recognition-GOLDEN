# ruff: noqa
"""Servidor del banco de pruebas: sirve static/, una página mínima con CedulaFoto y un OCR de reemplazo (tesseract del sistema en vez de tesseract.js). Ver LEEME.md."""
import sys, os, json, subprocess, tempfile, io, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ROOT=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); REPO=os.environ.get('REPO',ROOT); sys.path.insert(0, ROOT)   # REPO: otra copia de static/ para comparar versiones
MODE={'server':'off'}
PAGE='''<!doctype html><meta charset=utf8><body>
<div class="stage" style="position:relative;width:WWpx;height:HHpx"><video id=v style="width:100%;height:100%;object-fit:cover"></video><canvas id=o style="position:absolute;inset:0;width:100%;height:100%"></canvas></div>
<button id=b>Tomar foto</button><p id=s></p>
<script>
window.LOG=[]; window.RESULT=undefined; window.ZXN=0; window.ZXingWASM={prepareZXingModule(){}, readBarcodes: async()=>{window.ZXN++; return [];}};
window.Tesseract={createWorker: async()=>{ let wl=''; return { setParameters: async(p)=>{ wl=p.tessedit_char_whitelist||''; }, recognize: async(cv)=>{
  const blob=await new Promise(r=>cv.toBlob(r,'image/png')); const res=await fetch('/ocr?wl='+encodeURIComponent(wl),{method:'POST',body:blob}); window.OCRN=(window.OCRN||0)+1; return {data: await res.json()}; } }; }};
</script>
<script src="/static/js/cedula-readers.js"></script><script src="/static/js/cedula-foto.js"></script>
<script>
const q=new URLSearchParams(location.search);
window.H=CedulaFoto.attach({kind:q.get('kind')||'new',video:v,overlay:o,button:b,status:s,eventId:q.get('ev')||'',readers:async()=>window.CedulaReaders,
  onStatus:(m,k)=>{s.textContent=m;LOG.push([Math.round(performance.now()),k,m]);}, onResult:(d)=>{window.RESULT=d;LOG.push([Math.round(performance.now()),'RESULT',JSON.stringify(d)]);}});
window.onerror=(m)=>LOG.push([0,'JSERR',String(m)]); window.onunhandledrejection=(e)=>LOG.push([0,'REJ',String(e.reason)]);
</script>'''
class Hd(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def _send(self,code,body,ct='application/json'):
        if isinstance(body,(dict,list)): body=json.dumps(body).encode()
        self.send_response(code); self.send_header('Content-Type',ct); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        u=urllib.parse.urlparse(self.path)
        if u.path=='/page':
            q=urllib.parse.parse_qs(u.query); return self._send(200,PAGE.replace('WW',q.get('w',['400'])[0]).replace('HH',q.get('h',['700'])[0]).encode(),'text/html; charset=utf-8')
        if u.path.startswith('/static/'):
            f=os.path.join(REPO,u.path.lstrip('/'))
            if os.path.isfile(f): return self._send(200,open(f,'rb').read(),'application/javascript; charset=utf-8')
        if u.path=='/info': return self._send(200,MODE)
        if u.path=='/mode': MODE['server']=u.query; return self._send(200,{})
        self._send(404,{})
    def do_POST(self):
        u=urllib.parse.urlparse(self.path); body=self.rfile.read(int(self.headers.get('Content-Length','0')))
        if u.path=='/ocr':
            wl=urllib.parse.parse_qs(u.query).get('wl',[''])[0]
            if 'badocr' in MODE['server']: return self._send(200,{'text':'XXXX','confidence':10,'symbols':[]})
            with tempfile.TemporaryDirectory() as d:
                open(d+'/i.png','wb').write(body)
                subprocess.run(['tesseract',d+'/i.png',d+'/o','--psm','7','--dpi','300','-c','tessedit_char_whitelist='+wl,'makebox'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                syms=[]; 
                try:
                    import struct; hgt=struct.unpack('>I',body[20:24])[0]
                    for ln in open(d+'/o.box',encoding='utf8'):
                        p=ln.rstrip('\n').split(' ')
                        if len(p)>=5: syms.append({'text':p[0],'confidence':int(os.environ.get('CONF','88')),'bbox':{'x0':int(p[1]),'x1':int(p[3]),'y0':hgt-int(p[4]),'y1':hgt-int(p[2])}})
                except Exception: pass
            return self._send(200,{'text':''.join(x['text'] for x in syms),'confidence':int(os.environ.get('CONF','88')),'symbols':syms})
        if u.path.endswith('/cedula-mrz-scan'):
            MODE['calls']=MODE.get('calls',0)+1
            if 'real' not in MODE['server']: return self._send(422,{'detail':'apagado'})
            import numpy as np, cv2
            from app.mrz_ocr import VARIANTS, extract_mrz_lines
            i=body.find(b'\r\n\r\n'); j=body.rfind(b'\r\n--'); img=cv2.imdecode(np.frombuffer(body[i+4:j],np.uint8),cv2.IMREAD_COLOR); MODE['last_shape']=list(img.shape); arr=cv2.cvtColor(img,cv2.COLOR_BGR2RGB)
            for k in range(4):
                rot=np.rot90(arr,k) if k else arr
                for var in range(len(VARIANTS)):
                    lines=extract_mrz_lines(rot,var)
                    if len(lines)<3:
                        if var==0: break
                        continue
                    r=json.loads(subprocess.check_output(['node',os.path.join(os.path.dirname(os.path.abspath(__file__)),'parse.js'),json.dumps(lines[-3:])])); MODE['lines']=lines[-3:]
                    if r['valid']: return self._send(200,{'id':r['id'],'first_name':r['first_name'],'last_name':r['last_name']})
            return self._send(422,{'detail':'no'})
        if u.path.endswith('/cedula-near'): return self._send(200,{'by_number':[],'by_name':[]})
        self._send(404,{})
ThreadingHTTPServer(('127.0.0.1',8765),Hd).serve_forever()
