/* GENERADO por scripts/build_cedula_readers.py desde app/pruebas/lector_cedula.html — NO editar a mano (edita la página y vuelve a generar).
   Lectores de cédula por cámara para el quiosco (Registro → Escanear), cargados bajo demanda por qr.js:
     CedulaReaders.CedulaScanner  cédula vieja: código de barras PDF417 (zxing-wasm)
     CedulaReaders.MrzScanner     cédula nueva: las 3 líneas de abajo (OCR con tesseract.js + dígitos de control)
   Librerías: copia propia en /static/vendor/cedula/ si existe (window.CEDULA_VENDOR; ver scripts/vendor_cedula_readers.sh); si no, CDN. Todo se procesa en el navegador. */
(function () {
'use strict';
/*
 * Parser del PDF417 de la cédula de ciudadanía colombiana.
 * Recibe los BYTES crudos del código (no el texto) y devuelve:
 *   { cedula, nombre1, nombre2, apellido1, apellido2, nacimiento:'YYYYMMDD', sexo, rh, linea }
 *
 * Disposición conocida (posiciones desde el inicio del payload, campos de 23 bytes rellenos con \0):
 *   48  cédula (10)     58 apellido1   81 apellido2   104 nombre1   127 nombre2
 *   151 sexo (M/F)      152 año(4) 156 mes(2) 158 día(2)           166 RH (2)
 * Para tolerar cabeceras distintas, las posiciones se calculan RELATIVAS al byte de sexo+fecha.
 */
function bytesToLatin1(b){
  let s=''; for(let i=0;i<b.length;i++) s+=String.fromCharCode(b[i]); return s;
}
function cleanField(str){
  return str.replace(/[\x00-\x1f\x7f]/g,' ').replace(/\s+/g,' ').trim();
}
const NAME_RE=/^[A-ZÑÁÉÍÓÚÜ' .-]+$/;
function validDate(y,m,d){
  const dt=new Date(Date.UTC(y,m-1,d));
  return y>=1900 && y<=new Date().getUTCFullYear() &&
         dt.getUTCFullYear()===y && dt.getUTCMonth()===m-1 && dt.getUTCDate()===d;
}
function buildResult(o){
  const ced=String(o.cedula).replace(/^0+(?=\d)/,'');
  const r={
    cedula:ced, nombre1:o.nombre1||'', nombre2:o.nombre2||'',
    apellido1:o.apellido1||'', apellido2:o.apellido2||'',
    nacimiento:o.nacimiento, sexo:o.sexo||'', rh:o.rh||'', aproximado:!!o.aproximado
  };
  r.linea=[r.cedula,r.nombre1,r.nombre2,r.apellido1,r.apellido2,r.nacimiento].join(',');
  return r;
}
function parseCedula(bytes){
  const s=bytesToLatin1(bytes);
  const re=/([MF])((?:19|20)\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])/g;
  let m;
  while((m=re.exec(s))){
    const g=m.index;
    if(!validDate(+m[2],+m[3],+m[4])) continue;
    const nacimiento=m[2]+m[3]+m[4];
    const rhM=cleanField(s.slice(g+15,g+18)).match(/^(AB|A|B|O)[+-]/);
    const rh=rhM?rhM[0]:'';

    // --- Estrategia A: posiciones fijas relativas al sexo ---
    if(g>=103){
      const ced=cleanField(s.slice(g-103,g-93));
      const f=[s.slice(g-93,g-70),s.slice(g-70,g-47),s.slice(g-47,g-24),s.slice(g-24,g-1)].map(cleanField);
      const ok=/^\d{5,10}$/.test(ced) && f[0] && f[2] && f.every(x=>x===''||NAME_RE.test(x));
      if(ok) return buildResult({cedula:ced,apellido1:f[0],apellido2:f[1],nombre1:f[2],nombre2:f[3],nacimiento,sexo:m[1],rh});
    }

    // --- Estrategia B: heurística por "bloques de letras" antes del sexo ---
    const before=s.slice(0,g);
    const runs=[]; const rr=/[A-ZÑÁÉÍÓÚÜ][A-ZÑÁÉÍÓÚÜ' .-]*/g; let x;
    while((x=rr.exec(before))){ const t=x[0].trim(); if(t.length>=2) runs.push({t,i:x.index}); }
    const names=runs.slice(-4);
    if(names.length>=2){
      const first=names[0].i;
      const nums=[...before.slice(0,first).matchAll(/\d{6,10}/g)];
      if(nums.length){
        const ced=nums[nums.length-1][0];
        const t=names.map(n=>n.t);
        let ap1=t[0],ap2='',n1='',n2='';
        if(t.length===4){ap2=t[1];n1=t[2];n2=t[3];}
        else if(t.length===3){ap2=t[1];n1=t[2];}
        else {n1=t[1];}
        return buildResult({cedula:ced,apellido1:ap1,apellido2:ap2,nombre1:n1,nombre2:n2,nacimiento,sexo:m[1],rh,aproximado:true});
      }
    }
  }
  return null;
}
function formatBirth(yyyymmdd){ return yyyymmdd.slice(6,8)+'/'+yyyymmdd.slice(4,6)+'/'+yyyymmdd.slice(0,4); }
function rawDump(bytes){
  const hex=[...bytes].map(b=>b.toString(16).padStart(2,'0')).join(' ');
  const txt=[...bytes].map(b=>(b>=32&&b<127)||b>=0xA0?String.fromCharCode(b):'·').join('');
  return 'TEXTO (· = byte no imprimible):\n'+txt+'\n\nHEX ('+bytes.length+' bytes):\n'+hex;
}


/*
 * Localizador de PDF417 por textura: el PDF417 es una malla densa con transiciones
 * claro/oscuro en AMBOS ejes (el texto y los fondos no). Se mide la densidad de bordes
 * por bloques, se agrupan bloques "calientes" y de cada grupo se calcula el rectángulo
 * orientado (PCA) -> centro, ángulo, largo y ancho.
 * gray: Uint8ClampedArray|Uint8Array (w*h). Devuelve candidatos ordenados por puntaje.
 */
function locateBarcodes(gray,w,h,o){
  o=o||{};
  const B=o.block||6, T=o.edge||22, DH=o.dh||0.28, DV=o.dv||0.28;
  const gw=Math.floor(w/B), gh=Math.floor(h/B);
  if(gw<4||gh<4) return [];
  const ch=new Uint16Array(gw*gh), cv=new Uint16Array(gw*gh);
  for(let y=1;y<h-1;y++){
    const by=Math.min(gh-1,(y/B)|0), row=y*w;
    for(let x=1;x<w-1;x++){
      const i=row+x, bx=Math.min(gw-1,(x/B)|0);
      const dx=gray[i+1]-gray[i-1], dy=gray[i+w]-gray[i-w];
      if(dx>T||dx<-T) ch[by*gw+bx]++;
      if(dy>T||dy<-T) cv[by*gw+bx]++;
    }
  }
  const area=B*B, hot=new Uint8Array(gw*gh);
  for(let i=0;i<hot.length;i++) hot[i]=(ch[i]/area>=DH && cv[i]/area>=DV)?1:0;
  // dilatación 3x3 para unir huecos pequeños
  const dil=new Uint8Array(gw*gh);
  for(let y=0;y<gh;y++)for(let x=0;x<gw;x++){
    let v=0;
    for(let j=-1;j<=1&&!v;j++)for(let i=-1;i<=1;i++){
      const X=x+i,Y=y+j; if(X>=0&&Y>=0&&X<gw&&Y<gh&&hot[Y*gw+X]){v=1;break;}
    }
    dil[y*gw+x]=v;
  }
  // componentes conexas (4-vecinos) sobre la dilatada
  const lab=new Int32Array(gw*gh).fill(-1), out=[]; let nl=0;
  const stack=[];
  for(let s0=0;s0<gw*gh;s0++){
    if(!dil[s0]||lab[s0]>=0) continue;
    const cells=[]; stack.push(s0); lab[s0]=nl;
    while(stack.length){
      const c=stack.pop(), cx=c%gw, cy=(c/gw)|0;
      if(hot[c]) cells.push(c);
      if(cx>0&&dil[c-1]&&lab[c-1]<0){lab[c-1]=nl;stack.push(c-1);}
      if(cx<gw-1&&dil[c+1]&&lab[c+1]<0){lab[c+1]=nl;stack.push(c+1);}
      if(cy>0&&dil[c-gw]&&lab[c-gw]<0){lab[c-gw]=nl;stack.push(c-gw);}
      if(cy<gh-1&&dil[c+gw]&&lab[c+gw]<0){lab[c+gw]=nl;stack.push(c+gw);}
    }
    nl++;
    const cand=analyse(cells,gw,B,o);
    if(cand) out.push(cand);
  }
  out.sort((a,b)=>b.score-a.score);
  return out;
}
function analyse(cells,gw,B,o){
  const minCells=o.minCells||30;
  if(cells.length<minCells) return null;
  let mx=0,my=0; const px=new Float32Array(cells.length), py=new Float32Array(cells.length);
  for(let i=0;i<cells.length;i++){ px[i]=cells[i]%gw+.5; py[i]=((cells[i]/gw)|0)+.5; mx+=px[i]; my+=py[i]; }
  mx/=cells.length; my/=cells.length;
  let sxx=0,syy=0,sxy=0;
  for(let i=0;i<cells.length;i++){ const dx=px[i]-mx,dy=py[i]-my; sxx+=dx*dx; syy+=dy*dy; sxy+=dx*dy; }
  const ang=0.5*Math.atan2(2*sxy,sxx-syy), ca=Math.cos(ang), sa=Math.sin(ang);
  // proyecciones u (eje largo) / v (eje corto)
  const U=new Float32Array(cells.length), V=new Float32Array(cells.length);
  let umin=1e9,umax=-1e9,vmin=1e9,vmax=-1e9;
  for(let i=0;i<cells.length;i++){
    U[i]=(px[i]-mx)*ca+(py[i]-my)*sa; V[i]=-(px[i]-mx)*sa+(py[i]-my)*ca;
  }
  // recorte por perfiles: descarta colas (texto pegado, bordes) con <40% del máximo
  const trim=(arr)=>{
    let lo=1e9,hi=-1e9; for(const a of arr){ if(a<lo)lo=a; if(a>hi)hi=a; }
    const n=Math.max(1,Math.ceil(hi-lo)+1), bins=new Int32Array(n);
    for(const a of arr) bins[Math.min(n-1,Math.floor(a-lo))]++;
    let m=0,mi=0; for(let i=0;i<n;i++) if(bins[i]>m){m=bins[i];mi=i;}
    let a=mi,b=mi; const th=m*0.4;
    while(a>0&&bins[a-1]>=th) a--; while(b<n-1&&bins[b+1]>=th) b++;
    return [lo+a,lo+b+1];
  };
  [umin,umax]=trim(U); [vmin,vmax]=trim(V);
  let n=0; for(let i=0;i<cells.length;i++) if(U[i]>=umin&&U[i]<=umax&&V[i]>=vmin&&V[i]<=vmax) n++;
  const L=umax-umin, Wd=vmax-vmin;
  if(L<=0||Wd<=0) return null;
  const fill=n/(L*Wd), elong=L/Wd;
  const minL=o.minLen||14; // celdas
  if(L<minL||fill<(o.minFill||0.45)||elong<(o.minElong||2.2)||elong>(o.maxElong||14)) return null;
  // las barras de inicio/fin (verticales) y la zona de silencio tienen poca textura 2D: se amplía el rectángulo
  const ex=o.expandU===undefined?0.14:o.expandU, ey=o.expandV===undefined?0.06:o.expandV;
  umin-=L*ex+1; umax+=L*ex+1; vmin-=Wd*ey+0.5; vmax+=Wd*ey+0.5;
  const uc=(umin+umax)/2, vc=(vmin+vmax)/2;
  return {
    cx:(mx+uc*ca-vc*sa)*B, cy:(my+uc*sa+vc*ca)*B, angle:ang,
    L:(umax-umin)*B, W:(vmax-vmin)*B, count:n, fill, elong, score:n*fill
  };
}


/*
 * CedulaScanner — lee el PDF417 de la cédula colombiana desde la cámara o desde una imagen.
 *
 *   import { CedulaScanner } from './cedula-scanner.js';
 *   const sc = new CedulaScanner({
 *     onResult:  (data, bytes) => console.log(data.linea),   // "1016100329,JHOAN,SEBASTIAN,ANGARITA,ROJAS,19980206"
 *     onUnknown: (bytes)       => {},                         // PDF417 leído pero con otro formato
 *     onStatus:  (msg, kind)   => {},                         // kind: '' | 'ok' | 'warn' | 'err'
 *   });
 *   await sc.init();
 *   await sc.startCamera(videoEl, overlayCanvasEl);           // en vivo (HTTPS + permiso de cámara)
 *   const data = await sc.scanImage(fileOrBlob);              // foto / galería -> objeto | null
 *   sc.lastDebug                                              // diagnóstico del último escaneo de imagen
 *   sc.stop();
 *
 * data = { cedula, nombre1, nombre2, apellido1, apellido2, nacimiento:'YYYYMMDD', sexo, rh, linea, aproximado }
 */

const ZX_VERSION = '3.1.3';
const ZX_URLS = [
  ...(window.CEDULA_VENDOR ? [`${window.CEDULA_VENDOR}/zxing/iife/reader/index.js`] : []),   // copia propia (scripts/vendor_cedula_readers.sh), si existe; si no, CDN
  `https://cdn.jsdelivr.net/npm/zxing-wasm@${ZX_VERSION}/dist/iife/reader/index.js`,
  `https://unpkg.com/zxing-wasm@${ZX_VERSION}/dist/iife/reader/index.js`,
];
const MAX_SIDE = 1920;
const GAP_MS = 60;
const GUIDE_AR = 4.8;                          // proporción ancho/alto del recuadro guía (el PDF417 de la cédula es ~5:1)
const SHARP_MIN = .30;                         // nitidez mínima (energía de bordes a un módulo / contraste) para gastar análisis a fondo
const MODULES_EST = 340;                       // módulos aprox. de ancho del PDF417 de la cédula (para estimar px/módulo)
const ROIS = [[0,0,1,1],[0,.3,1,.7],[0,0,1,.7],[.08,.08,.84,.84]];
const SCALES = [[1100,{}],[600,{}],[600,{minFill:.3,dh:.22,dv:.22}]];

const BASE = { formats:['PDF417'], tryHarder:true, tryRotate:true, tryInvert:true, tryDownscale:true, maxNumberOfSymbols:1 };
const OPT_SETS = {
  def: BASE,
  gh:  { ...BASE, binarizer:'GlobalHistogram' },
  dn:  { ...BASE, tryDenoise:true, minLineCount:1 },
};
const OPTS_MIN = { formats:['PDF417'], tryHarder:true };

/* ============ utilidades de imagen (gris, desenfoque, umbral, enderezado de perspectiva) ============ */
const toGray = img => { const d = img.data, g = new Uint8Array(img.width * img.height);
  for (let i = 0, j = 0; j < g.length; i += 4, j++) g[j] = (d[i]*77 + d[i+1]*150 + d[i+2]*29) >> 8; return g; };
const fromGray = (g, w, h) => { const o = new ImageData(w, h), d = o.data;
  for (let i = 0, j = 0; j < g.length; i += 4, j++) { d[i] = d[i+1] = d[i+2] = g[j]; d[i+3] = 255; } return o; };
function boxBlur(g, w, h, r) {
  const tmp = new Float32Array(w * h), out = new Uint8Array(w * h), n = 2 * r + 1, cl = (v, m) => v < 0 ? 0 : v > m ? m : v;
  for (let y = 0; y < h; y++) { const row = y * w; let acc = 0;
    for (let x = -r; x <= r; x++) acc += g[row + cl(x, w-1)];
    for (let x = 0; x < w; x++) { tmp[row + x] = acc / n; acc += g[row + cl(x + r + 1, w-1)] - g[row + cl(x - r, w-1)]; } }
  for (let x = 0; x < w; x++) { let acc = 0;
    for (let y = -r; y <= r; y++) acc += tmp[cl(y, h-1) * w + x];
    for (let y = 0; y < h; y++) { out[y*w + x] = acc / n; acc += tmp[cl(y + r + 1, h-1) * w + x] - tmp[cl(y - r, h-1) * w + x]; } }
  return out;
}
function gauss(g, w, h, sigma) {                 // gaussiana separable real (devuelve 8 bits)
  const r = Math.max(1, Math.ceil(sigma * 3)), k = new Float32Array(2 * r + 1); let tot = 0;
  for (let i = -r; i <= r; i++) { k[i + r] = Math.exp(-i * i / (2 * sigma * sigma)); tot += k[i + r]; }
  for (let i = 0; i < k.length; i++) k[i] /= tot;
  const t = new Float32Array(w * h), o = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) { const row = y * w;
    for (let x = 0; x < w; x++) { let a = 0; for (let i = -r; i <= r; i++) { const xx = x + i < 0 ? 0 : x + i >= w ? w - 1 : x + i; a += g[row + xx] * k[i + r]; } t[row + x] = a; } }
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) { let a = 0;
    for (let i = -r; i <= r; i++) { const yy = y + i < 0 ? 0 : y + i >= h ? h - 1 : y + i; a += t[yy * w + x] * k[i + r]; } o[y*w + x] = a + .5; }
  return o;
}
/* Paso-banda: suaviza levemente (mata la trama de pantalla) y luego realza el contraste local (compensa el desenfoque).
   Los radios se escalan con el tamaño del módulo del código en el recorte (~ancho/435 px). */
function bandPass(img, fp, fu, amt) {
  const w = img.width, h = img.height, mod = w / 435, g = toGray(img);
  const p = gauss(g, w, h, Math.max(.5, fp * mod)), b = gauss(p, w, h, Math.max(1.5, fu * mod)), o = new Uint8Array(g.length);
  for (let i = 0; i < o.length; i++) { const v = p[i] + amt * (p[i] - b[i]); o[i] = v < 0 ? 0 : v > 255 ? 255 : v; }
  return o;
}
function stretchGray(g) {                       // estira contraste (percentiles 1–99)
  const h = new Uint32Array(256), n = g.length; for (let i = 0; i < n; i++) h[g[i]]++;
  let lo = 0, hi = 255, acc = 0;
  for (let i = 0; i < 256; i++) { acc += h[i]; if (acc >= n * .01) { lo = i; break; } }
  acc = 0; for (let i = 255; i >= 0; i--) { acc += h[i]; if (acc >= n * .01) { hi = i; break; } }
  const sc = 255 / Math.max(1, hi - lo), o = new Uint8Array(n);
  for (let i = 0; i < n; i++) { const v = (g[i] - lo) * sc; o[i] = v < 0 ? 0 : v > 255 ? 255 : v; }
  return o;
}
function binarGray(g, w, h) {                   // umbral adaptativo por media local (imagen integral)
  const W = w + 1, I = new Float64Array(W * (h + 1));
  for (let y = 0; y < h; y++) { let r = 0; for (let x = 0; x < w; x++) { r += g[y*w + x]; I[(y+1)*W + x + 1] = I[y*W + x + 1] + r; } }
  const R = Math.max(8, Math.round(w / 70)), out = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) { const y0 = Math.max(0, y - R), y1 = Math.min(h, y + R + 1);
    for (let x = 0; x < w; x++) { const x0 = Math.max(0, x - R), x1 = Math.min(w, x + R + 1);
      const m = (I[y1*W + x1] - I[y0*W + x1] - I[y1*W + x0] + I[y0*W + x0]) / ((x1 - x0) * (y1 - y0));
      out[y*w + x] = g[y*w + x] < m * .93 ? 0 : 255; } }
  return out;
}
function fitLine(xs, ys) {                      // mínimos cuadrados con un descarte de atípicos
  const run = (X, Y) => { const n = X.length; let sx = 0, sy = 0, sxx = 0, sxy = 0;
    for (let i = 0; i < n; i++) { sx += X[i]; sy += Y[i]; sxx += X[i]*X[i]; sxy += X[i]*Y[i]; }
    const d = n*sxx - sx*sx || 1e-9, b = (n*sxy - sx*sy) / d; return [(sy - b*sx) / n, b]; };
  let [a, b] = run(xs, ys);
  const res = ys.map((y, i) => Math.abs(y - (a + b*xs[i]))), med = [...res].sort((p, q) => p - q)[res.length >> 1] || 1;
  const kx = [], ky = []; res.forEach((r, i) => { if (r <= 2.5 * med + 1) { kx.push(xs[i]); ky.push(ys[i]); } });
  return kx.length >= 4 ? run(kx, ky) : [a, b];
}
/* Corrige la perspectiva (trapecio) del recorte: ajusta el borde superior e inferior del código y los vuelve horizontales */
function dewarpGray(g, w, h) {
  const NB = 16, bw = Math.floor(w / NB), xs = [], tops = [], bots = [];
  for (let b = 1; b < NB - 1; b++) {
    const x0 = b * bw, x1 = x0 + bw, dens = new Float32Array(h);
    for (let y = 0; y < h; y++) { let c = 0; const row = y * w;
      for (let x = x0 + 1; x < x1 - 1; x++) { const d = g[row + x + 1] - g[row + x - 1]; if (d > 22 || d < -22) c++; } dens[y] = c; }
    const sm = new Float32Array(h); let m = 0, mi = 0;
    for (let y = 0; y < h; y++) { sm[y] = dens[y] + (dens[y-1] || 0) + (dens[y+1] || 0); if (sm[y] > m) { m = sm[y]; mi = y; } }
    if (m < 6) continue;
    let t = mi, bt = mi; while (t > 0 && sm[t-1] >= .4 * m) t--; while (bt < h - 1 && sm[bt+1] >= .4 * m) bt++;
    xs.push(x0 + bw / 2); tops.push(t); bots.push(bt + 1);
  }
  if (xs.length < 6) return null;
  const [at, bt_] = fitLine(xs, tops), [ab, bb] = fitLine(xs, bots), f = .07, out = new Uint8Array(w * h).fill(255);
  const hm = xs.reduce((s, _, i) => s + bots[i] - tops[i], 0) / xs.length; if (hm < .25 * h) return null;
  for (let x = 0; x < w; x++) {
    const t = at + bt_ * x, bo = ab + bb * x, ht = Math.max(4, bo - t);
    for (let y = 0; y < h; y++) {
      const sy = t - f * ht + (y / (h - 1)) * (1 + 2 * f) * ht, y0 = Math.floor(sy);
      if (y0 < 0 || y0 >= h - 1) continue; const fr = sy - y0;
      out[y*w + x] = g[y0*w + x] * (1 - fr) + g[(y0+1)*w + x] * fr;
    }
  }
  return out;
}
const VARIANTS = {
  raw:     img => img,
  stretch: img => fromGray(stretchGray(toGray(img)), img.width, img.height),
  binar:   img => fromGray(binarGray(stretchGray(toGray(img)), img.width, img.height), img.width, img.height),
  denoise: img => { const w = img.width, h = img.height, b = gauss(toGray(img), w, h, 1.3);        // quita trama de pantalla / ruido
                    return fromGray(binarGray(stretchGray(b), w, h), w, h); },
  sharp:   img => { const w = img.width, h = img.height, g = toGray(img), b = gauss(g, w, h, 2.4), o = new Uint8Array(g.length); // desenfoque
                    for (let i = 0; i < g.length; i++) { const v = g[i] + 1.7 * (g[i] - b[i]); o[i] = v < 0 ? 0 : v > 255 ? 255 : v; }
                    return fromGray(stretchGray(o), w, h); },
  bandA:   img => fromGray(stretchGray(bandPass(img, .28, .95, 1.5)), img.width, img.height),
  bandB:   img => fromGray(stretchGray(bandPass(img, .40, 1.25, 2)), img.width, img.height),
  bandC:   img => fromGray(stretchGray(bandPass(img, .40, 1.0, 2)), img.width, img.height),
  bandAb:  img => fromGray(binarGray(stretchGray(bandPass(img, .28, .95, 1.5)), img.width, img.height), img.width, img.height),
  dewarpA: img => { const d = dewarpGray(toGray(img), img.width, img.height); if (!d) return null;
                    const im = fromGray(stretchGray(d), img.width, img.height); return fromGray(stretchGray(bandPass(im, .28, .95, 1.5)), img.width, img.height); },
  dewarp:  img => { const d = dewarpGray(toGray(img), img.width, img.height); return d && fromGray(stretchGray(d), img.width, img.height); },
  dewarpB: img => { const d = dewarpGray(toGray(img), img.width, img.height); return d && fromGray(binarGray(stretchGray(d), img.width, img.height), img.width, img.height); },
};
/* Planes de intento (en orden de costo/probabilidad). mult = escala del recorte relativa a la automática */
const V3 = ['raw', 'stretch', 'binar'];
const PLANS = {
  legacy:     [{ mult: 1, flip: false, variants: V3 }],
  legacyFlip: [{ mult: 1, flip: false, variants: V3 }, { mult: 1, flip: true, variants: V3 }],
  fast:       [{ mult: 1, flip: false, variants: [...V3, 'bandA'] }],
  deep: [
    { mult: 1,   flip: false, variants: ['raw', 'stretch', 'binar', 'bandA', 'bandB', 'bandC', 'bandAb', 'denoise', 'sharp'] },
    { mult: 1,   flip: false, variants: ['dewarp', 'dewarpA', 'dewarpB'] },
    { mult: 1,   flip: false, variants: ['raw', 'stretch', 'bandA'], opts: 'gh' },
    { mult: 1,   flip: false, variants: ['stretch', 'binar', 'bandA'], opts: 'dn' },
    { mult: .65, flip: false, variants: ['raw', 'stretch', 'binar', 'bandA', 'denoise'] },
    { mult: 1.5, flip: false, variants: ['raw', 'stretch', 'binar', 'bandA', 'denoise'] },
    { mult: 1,   flip: true,  variants: [...V3, 'bandA'] },
    { mult: 1,   flip: true,  variants: ['dewarp', 'denoise'] },
    { mult: 1,   flip: false, pad: .08, variants: ['raw', 'stretch', 'bandA', 'binar'] },                // con zona de silencio blanca alrededor
    { mult: 1,   flip: false, pad: .08, variants: ['stretch', 'bandA'], rot: -4 },
    { mult: 1,   flip: false, pad: .08, variants: ['stretch', 'bandA'], rot: 4 },
    // barrido de giro: el localizador puede errar el ángulo unos grados y un código inclinado en el recorte no se lee
    ...[-5, 5, -10, 10, -16, 16].map(rot => ({ mult: 1, flip: false, rot, variants: ['stretch', 'bandA', 'binar'] })),
  ],
};

const mk = () => { const c = document.createElement('canvas'); return [c, c.getContext('2d', { willReadFrequently: true })]; };
const sleep = ms => new Promise(r => setTimeout(r, ms));
/* Cede el turno al navegador entre una decodificación y la siguiente: el análisis a fondo encadena decenas de intentos y, sin esto, el hilo de la página quedaba ocupado
   hasta 1,6 s seguidos (video congelado, botones sin responder). Lo que se analiza y el orden no cambian; solo se deja pintar entre intento e intento. */
const yieldUI = () => new Promise(r => { const ch = new MessageChannel(); ch.port1.onmessage = () => r(); ch.port2.postMessage(0); });

class CedulaScanner {
  /** opts.legacy = true -> comportamiento de la versión 2 (solo para comparar) */
  constructor({ onResult = () => {}, onUnknown = () => {}, onStatus = () => {}, legacy = false, autoStill = true, guide = true } = {}) {
    Object.assign(this, { onResult, onUnknown, onStatus, legacy, autoStill, guideMode: guide });
    [this.ana, this.actx] = mk(); [this.crop, this.cctx] = mk(); [this.work, this.wctx] = mk(); [this.shc, this.shx] = mk();
    this.useMin = false; this.scanning = false; this.stream = null; this.track = null; this.lastDebug = null;
  }

  /* ---------- decodificador ---------- */
  async init() {
    if (!window.ZXingWASM) {
      let base = '';
      for (const u of ZX_URLS) {
        try { await new Promise((res, rej) => { const s = document.createElement('script'); s.src = u; s.onload = res; s.onerror = rej; document.head.appendChild(s); });
              base = u.replace('/iife/reader/index.js', '/reader/'); break; } catch (e) { console.warn('CDN falló', u); }
      }
      if (!window.ZXingWASM) throw new Error('No se pudo cargar zxing-wasm (revisa la conexión).');
      try { ZXingWASM.prepareZXingModule({ overrides: { locateFile: (p, prefix) => p.endsWith('.wasm') ? base + p : prefix + p } }); } catch (e) {}
    }
    await this._decode(new ImageData(16, 16));
  }
  async _decode(img, key = 'def') {
    try { return await ZXingWASM.readBarcodes(img, this.useMin ? OPTS_MIN : OPT_SETS[key] || BASE); }
    catch (e) { if (this.useMin) throw e; this.useMin = true; console.warn('opciones avanzadas no soportadas', e); return await ZXingWASM.readBarcodes(img, OPTS_MIN); }
  }
  static _hit(r) { return (r || []).find(x => (x.bytes && x.bytes.length) || x.text) || null; }
  static _bytes(hit) {
    if (hit.bytes && hit.bytes.length) return Uint8Array.from(hit.bytes);
    return Uint8Array.from([...(hit.text || '')].map(c => c.charCodeAt(0) & 0xFF));
  }

  /* ---------- localizar el código en la imagen ---------- */
  findCandidates(src, sw, sh) {
    const all = [];
    for (const [side, opt] of SCALES) {
      const s = Math.min(1, side / Math.max(sw, sh)), aw = Math.max(8, Math.round(sw * s)), ah = Math.max(8, Math.round(sh * s));
      this._downscale(src, sw, sh, aw, ah);
      const g = toGray(this.actx.getImageData(0, 0, aw, ah));
      for (const c of locateBarcodes(g, aw, ah, opt))
        all.push({ cx: c.cx / s, cy: c.cy / s, angle: c.angle, L: c.L / s, W: c.W / s, score: c.score * c.fill * (6 / s) * (6 / s) });
    }
    all.sort((a, b) => b.score - a.score);
    const keep = [];
    for (const c of all) {
      if (keep.every(k => Math.hypot(k.cx - c.cx, k.cy - c.cy) > .4 * Math.min(k.L, c.L))) keep.push(c);
      if (keep.length >= 3) break;
    }
    return keep;
  }
  /* reducción por mitades sucesivas: evita el aliasing (falsa trama) de un solo drawImage muy reducido */
  _downscale(src, sw, sh, aw, ah) {
    const bufs = this._bufs || (this._bufs = [mk(), mk()]);
    let cur = src, cw = sw, ch = sh, i = 0;
    while (cw / 2 >= aw && ch / 2 >= ah) {
      const nw = Math.max(aw, Math.round(cw / 2)), nh = Math.max(ah, Math.round(ch / 2)), [c, cx] = bufs[i];
      c.width = nw; c.height = nh; cx.imageSmoothingQuality = 'high'; cx.drawImage(cur, 0, 0, cw, ch, 0, 0, nw, nh);
      cur = c; cw = nw; ch = nh; i ^= 1;
    }
    this.ana.width = aw; this.ana.height = ah; this.actx.imageSmoothingQuality = 'high'; this.actx.drawImage(cur, 0, 0, cw, ch, 0, 0, aw, ah);
  }
  _cropCandidate(src, c, flip, mult = 1, dAng = 0, pad = 0) {
    const target = Math.min(2200, Math.max(1400, c.L)) * mult, k = Math.min(4, target / c.L);
    const iw = Math.min(4200, Math.max(32, Math.round(c.L * k))), ih = Math.min(1600, Math.max(16, Math.round(c.W * k)));
    const ow = pad ? Math.round(iw * (1 + 2 * pad)) : iw, oh = pad ? Math.round(ih * (1 + 4 * pad)) : ih;      // pad = zona de silencio blanca alrededor
    const { crop, cctx } = this; crop.width = ow; crop.height = oh;
    cctx.save(); cctx.fillStyle = '#fff'; cctx.fillRect(0, 0, ow, oh);
    if (pad) { cctx.beginPath(); cctx.rect((ow - iw) / 2, (oh - ih) / 2, iw, ih); cctx.clip(); }
    cctx.translate(ow / 2, oh / 2); cctx.rotate(-c.angle - dAng + (flip ? Math.PI : 0)); cctx.scale(iw / c.L, ih / c.W); cctx.translate(-c.cx, -c.cy);
    cctx.imageSmoothingQuality = 'high'; cctx.drawImage(src, 0, 0); cctx.restore();
    return cctx.getImageData(0, 0, ow, oh);
  }
  /* aplica el plan de intentos a un candidato; devuelve {hit,cand,how} o null */
  async _tryCandidate(src, c, plan, deadline = Infinity) {
    const cache = new Map();
    for (const st of plan) {
      if (performance.now() > deadline) return null;
      const key = st.mult + '|' + st.flip + '|' + (st.rot || 0) + '|' + (st.pad || 0); let base = cache.get(key);
      if (!base) { base = this._cropCandidate(src, c, st.flip, st.mult, (st.rot || 0) * Math.PI / 180, st.pad || 0); cache.set(key, base); }
      for (const vn of st.variants) {
        if (performance.now() > deadline) return null;
        const img = VARIANTS[vn](base); if (!img) continue;
        await yieldUI();
        const hit = CedulaScanner._hit(await this._decode(img, st.opts || 'def'));
        if (hit) return { hit, cand: c, how: `${vn}@${st.mult}${st.flip ? '/180°' : ''}${st.rot ? '/rot' + st.rot : ''}${st.pad ? '/pad' : ''}${st.opts ? '/' + st.opts : ''}` };
      }
    }
    return null;
  }
  /* búsqueda por ventanas: si no se localizó el rectángulo, decodifica porciones de la imagen */
  async _tiles(bmp, deadline) {
    const W = bmp.width, H = bmp.height, pos = f => { const a = [], st = f * .5; for (let p = 0; ; p += st) { if (p + f >= 1 - 1e-6) { a.push(1 - f); break; } a.push(p); } return a; };
    for (const f of [.6, .4, .28]) for (const py of pos(f)) for (const px of pos(f)) {
      if (performance.now() > deadline) return null;
      const sx = Math.round(px * W), sy = Math.round(py * H), sw = Math.round(f * W), sh = Math.round(f * H), k = Math.min(1, MAX_SIDE / Math.max(sw, sh));
      this.work.width = Math.round(sw * k); this.work.height = Math.round(sh * k);
      this.wctx.drawImage(bmp, sx, sy, sw, sh, 0, 0, this.work.width, this.work.height);
      const hit = CedulaScanner._hit(await this._decode(this.wctx.getImageData(0, 0, this.work.width, this.work.height)));
      if (hit) return { hit, how: `ventana ${f}` };
    }
    return null;
  }

  /* ---------- resultado ---------- */
  _handle(bytes) {
    const data = parseCedula(bytes);
    if (data) { this.onStatus('Cédula leída', 'ok'); this.onResult(data, bytes); }
    else      { this.onStatus('Se leyó un PDF417 con formato desconocido', 'warn'); this.onUnknown(bytes); }
    return data;
  }

  /* ---------- foto / galería ---------- */
  async scanImage(file, { budgetMs = 15000 } = {}) {
    const t0 = performance.now(), deadline = t0 + budgetMs;
    const bmp = await createImageBitmap(file, { imageOrientation: 'from-image' });
    const dbg = this.lastDebug = { w: bmp.width, h: bmp.height, cands: [], how: '', ms: 0, ppm: null, hint: '', preview: null };
    const done = (hit, how) => { dbg.how = how; dbg.ms = Math.round(performance.now() - t0); return this._handle(CedulaScanner._bytes(hit)) || null; };

    const cands = dbg.cands = this.findCandidates(bmp, bmp.width, bmp.height);
    if (cands.length) dbg.ppm = +(cands[0].L / 1.28 / MODULES_EST).toFixed(2);
    for (const c of cands.slice(0, 3)) {
      const r = await this._tryCandidate(bmp, c, this.legacy ? PLANS.legacyFlip : PLANS.deep, this.legacy ? Infinity : deadline);
      if (r) return done(r.hit, 'recorte ' + r.how);
    }
    for (const side of [2800, 1800, 1100]) {                                    // imagen completa a varias escalas
      if (performance.now() > deadline) break;
      const k = Math.min(1, side / Math.max(bmp.width, bmp.height));
      this.work.width = Math.round(bmp.width * k); this.work.height = Math.round(bmp.height * k);
      this.wctx.drawImage(bmp, 0, 0, this.work.width, this.work.height);
      const hit = CedulaScanner._hit(await this._decode(this.wctx.getImageData(0, 0, this.work.width, this.work.height)));
      if (hit) return done(hit, 'imagen completa @' + side);
    }
    if (!this.legacy) { const r = await this._tiles(bmp, deadline); if (r) return done(r.hit, r.how); }

    // sin lectura: diagnóstico
    dbg.ms = Math.round(performance.now() - t0);
    if (!cands.length) dbg.hint = 'No se distingue ningún código PDF417. Enfoca el reverso de la cédula, con el código ocupando buena parte de la foto.';
    else if (dbg.ppm < 1.8) dbg.hint = `El código se ve muy pequeño o pixelado (≈${dbg.ppm} px por módulo; se necesitan ≥2.5). Acércate para que ocupe casi todo el ancho de la foto.`;
    else dbg.hint = 'El código se encontró pero no se pudo leer. Puede estar borroso o con reflejos, o ser una fotocopia, una impresión o una pantalla: esas copias pierden detalle del código y no se recuperan. Prueba con la cédula de plástico original, bien enfocada.';
    if (cands.length) { const im = this._cropCandidate(bmp, cands[0], false, 1), cv = document.createElement('canvas'); cv.width = im.width; cv.height = im.height; cv.getContext('2d').putImageData(im, 0, 0); dbg.preview = cv.toDataURL('image/jpeg', .85); }
    { const k = Math.min(1, 720 / Math.max(bmp.width, bmp.height)), t = document.createElement('canvas'); t.width = Math.round(bmp.width * k); t.height = Math.round(bmp.height * k); t.getContext('2d').drawImage(bmp, 0, 0, t.width, t.height); dbg.thumb = t.toDataURL('image/jpeg', .7); }
    this.onStatus(dbg.hint, 'err');
    return null;
  }

  /* ---------- cámara en vivo ---------- */
  async startCamera(video, overlay) {
    this.video = video; this.overlay = overlay; this.octx = overlay ? overlay.getContext('2d') : null;
    let last = null; this.stream = null;
    for (const size of [{ width: { ideal: 3840 }, height: { ideal: 2160 } }, { width: { ideal: 2560 }, height: { ideal: 1440 } }, {}]) {   // la mayor resolución que dé el celular
      try { this.stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: { facingMode: { ideal: 'environment' }, ...size } }); break; }
      catch (e) { last = e; if (e.name === 'NotAllowedError' || e.name === 'SecurityError' || e.name === 'NotFoundError') throw e; }
    }
    if (!this.stream) throw last || new Error('No se pudo abrir la cámara');
    this.track = this.stream.getVideoTracks()[0]; this._ic = null; this.stillError = ''; this._hintedPhoto = false; this._sh = []; this._lastDeep = 0; this._lastStill = 0;
    try { await this.track.applyConstraints({ advanced: [{ focusMode: 'continuous' }] }); } catch (e) {}
    video.srcObject = this.stream; video.setAttribute('playsinline', ''); video.muted = true; await video.play();
    this.scanning = true; this.startedAt = performance.now(); this._loop();
  }
  async setTorch(on) { try { await this.track.applyConstraints({ advanced: [{ torch: !!on }] }); return true; } catch (e) { return false; } }
  resume() { if (this.stream && !this.scanning) { this.video.play(); this.scanning = true; this.startedAt = performance.now(); this._loop(); } }
  stop() {
    this.scanning = false;
    if (this.stream) this.stream.getTracks().forEach(t => t.stop());
    this.stream = this.track = null; if (this.video) this.video.srcObject = null;
    if (this.octx) this.octx.clearRect(0, 0, this.overlay.width, this.overlay.height);
  }
  /** Foto fija de alta resolución (ImageCapture) del sensor: muchísimo más detalle que un cuadro de video. Si falla, `stillError` dice por qué. */
  async captureStill() {
    this.stillError = '';
    if (!this.track || typeof ImageCapture === 'undefined') { this.stillError = 'este navegador no ofrece ImageCapture'; return null; }
    try {
      const ic = this._ic || (this._ic = new ImageCapture(this.track)); let opts = {};
      try {                                                                // pedir la resolución máxima (hasta ~4600 px de ancho)
        const cap = await ic.getPhotoCapabilities(), W = cap.imageWidth, H = cap.imageHeight;
        if (W && H && W.max) {
          const k = Math.min(1, 4600 / W.max), fit = (r, v) => Math.min(r.max, Math.max(r.min || 1, Math.round(v / (r.step || 1)) * (r.step || 1)));
          opts = { imageWidth: fit(W, W.max * k), imageHeight: fit(H, H.max * k) };
        }
      } catch (e) {}
      try { return await ic.takePhoto(opts); }
      catch (e1) { this.stillError = (e1.name || 'Error') + ': ' + (e1.message || ''); return await ic.takePhoto(); }
    } catch (e) { this.stillError = (e.name || 'Error') + ': ' + (e.message || ''); return null; }
  }
  /** Foto fija del sensor si el navegador la da; si no, el cuadro de video actual. */
  async snapshot() {
    const still = await this.captureStill(); if (still) return { blob: still, source: 'foto fija del sensor' };
    const why = this.stillError ? ` — la foto fija no estuvo disponible (${this.stillError})` : '';
    const { video } = this, c = document.createElement('canvas'); c.width = video.videoWidth; c.height = video.videoHeight; c.getContext('2d').drawImage(video, 0, 0);
    return { blob: await new Promise(r => c.toBlob(r, 'image/jpeg', .92)), source: 'cuadro de video' + why };
  }
  _rect(c, color) {
    if (!this.octx) return; const { overlay, octx, video } = this, vw = video.videoWidth, vh = video.videoHeight;
    if (overlay.width !== vw || overlay.height !== vh) { overlay.width = vw; overlay.height = vh; }
    octx.clearRect(0, 0, vw, vh); if (!c) return;
    const ca = Math.cos(c.angle), sa = Math.sin(c.angle), L = c.L / 2, W = c.W / 2;
    octx.lineWidth = Math.max(4, vw / 220); octx.strokeStyle = color; octx.fillStyle = color + '30'; octx.beginPath();
    [[-L, -W], [L, -W], [L, W], [-L, W]].forEach(([u, v], i) => { const X = c.cx + u*ca - v*sa, Y = c.cy + u*sa + v*ca; i ? octx.lineTo(X, Y) : octx.moveTo(X, Y); });
    octx.closePath(); octx.fill(); octx.stroke();
  }
  _finish(hit, cand) {
    this.scanning = false; this.video.pause(); if (cand) this._rect(cand, '#2ee59d'); this._handle(CedulaScanner._bytes(hit));
  }
  /* ---------- modo guía: el código se encaja en un recuadro fijo y solo se analiza esa zona ---------- */
  setGuide(on) { this.guideMode = !!on; if (!on) this._rect(null); }
  /** Recuadro guía en píxeles del video, calculado sobre la parte VISIBLE (el video se muestra con object-fit: cover). */
  _guideRect(vw, vh) {
    const r = this.video.getBoundingClientRect(); let visW = vw, visH = vh;
    if (r.width && r.height) { const k = Math.max(r.width / vw, r.height / vh); visW = r.width / k; visH = r.height / k; }
    const x0 = (vw - visW) / 2, y0 = (vh - visH) / 2, w = Math.min(visW * .92, visH * .92 * GUIDE_AR), h = w / GUIDE_AR;
    return { x: x0 + (visW - w) / 2, y: y0 + (visH - h) / 2, w, h };
  }
  _drawGuide(g, color, cand, off, k) {
    if (!this.octx) return; const { overlay, octx, video } = this, vw = video.videoWidth, vh = video.videoHeight;
    if (overlay.width !== vw || overlay.height !== vh) { overlay.width = vw; overlay.height = vh; }
    octx.clearRect(0, 0, vw, vh);
    octx.fillStyle = 'rgba(0,0,0,.45)';                                   // oscurece lo que queda fuera del recuadro
    octx.beginPath(); octx.rect(0, 0, vw, vh); octx.rect(g.x, g.y, g.w, g.h); octx.fill('evenodd');
    const lw = Math.max(4, vw / 260), c = Math.min(g.h * .35, g.w * .06);
    octx.lineWidth = lw; octx.strokeStyle = color; octx.lineCap = 'round';
    octx.strokeRect(g.x, g.y, g.w, g.h);
    octx.lineWidth = lw * 1.8;                                            // esquinas marcadas
    [[g.x, g.y, 1, 1], [g.x + g.w, g.y, -1, 1], [g.x, g.y + g.h, 1, -1], [g.x + g.w, g.y + g.h, -1, -1]].forEach(([x, y, sx, sy]) => {
      octx.beginPath(); octx.moveTo(x, y + sy * c); octx.lineTo(x, y); octx.lineTo(x + sx * c, y); octx.stroke();
    });
    if (cand) {                                                           // el rectángulo que halló el localizador dentro del recuadro
      const ca = Math.cos(cand.angle), sa = Math.sin(cand.angle), L = cand.L / 2 / k, W = cand.W / 2 / k, cx = cand.cx / k + off.x, cy = cand.cy / k + off.y;
      octx.lineWidth = lw * .7; octx.strokeStyle = '#ffc857'; octx.beginPath();
      [[-L, -W], [L, -W], [L, W], [-L, W]].forEach(([u, v], i) => { const X = cx + u * ca - v * sa, Y = cy + u * sa + v * ca; i ? octx.lineTo(X, Y) : octx.moveTo(X, Y); });
      octx.closePath(); octx.stroke();
    }
  }
  /** Nitidez del recuadro guía (en el lienzo `work`): energía de bordes a ~1 módulo sobre el contraste. ~.6 = muy nítido, <.3 = borroso. */
  _sharp(gx, gy, gw, gh) {
    const W = 1000, H = Math.max(40, Math.round(W * gh / gw)), c = this.shc, x = this.shx; c.width = W; c.height = H;
    x.imageSmoothingQuality = 'high'; x.drawImage(this.work, gx, gy, gw, gh, 0, 0, W, H);
    const d = x.getImageData(0, 0, W, H).data, g = new Uint8Array(W * H); for (let i = 0; i < g.length; i++) g[i] = (d[i * 4] * 77 + d[i * 4 + 1] * 150 + d[i * 4 + 2] * 29) >> 8;
    const y0 = Math.floor(H * .25), y1 = Math.ceil(H * .75); let s1 = 0, m = 0, n = 0;
    for (let y = y0; y < y1; y += 2) { const o = y * W; for (let xx = 6; xx < W - 6; xx++) { const a = g[o + xx + 1] - g[o + xx - 1]; s1 += a * a; m += g[o + xx]; n++; } }
    m /= n; let v = 0; for (let y = y0; y < y1; y += 2) { const o = y * W; for (let xx = 6; xx < W - 6; xx++) { const q = g[o + xx] - m; v += q * q; } }
    return (s1 / n) / (v / n + 1);
  }
  /** Un intento en modo guía. Devuelve true si leyó la cédula. Lo barato (plan rápido) se hace en cada cuadro; lo caro (análisis a fondo y foto fija) solo cuando el código está ENFOCADO. */
  async _guideStep(attempts) {
    const { video, work, wctx } = this, vw = video.videoWidth, vh = video.videoHeight, g = this._guideRect(vw, vh), now = performance.now();
    const rx = Math.max(0, g.x - g.w * .04), ry = Math.max(0, g.y - g.h * .9), rw = Math.min(vw - rx, g.w * 1.08), rh = Math.min(vh - ry, g.h * 2.8);
    const k = Math.min(1, 2600 / rw), ww = Math.round(rw * k), wh = Math.round(rh * k), off = { x: rx, y: ry };
    work.width = ww; work.height = wh; wctx.drawImage(video, rx, ry, rw, rh, 0, 0, ww, wh);       // copia fija del cuadro: lo que se analiza no cambia aunque muevas el celular
    const gx = (g.x - rx) * k, gy = (g.y - ry) * k, gw = g.w * k, gh = g.h * k;
    const fallback = { cx: gx + gw / 2, cy: gy + gh / 2, angle: 0, L: gw * 1.08, W: gh * 1.22 };          // el recuadro tal cual, con un poco de margen
    const all = this.findCandidates(work, ww, wh), found = all.filter(c => c.L > gw * .75 && c.L < gw * 1.5 && Math.hypot(c.cx - fallback.cx, c.cy - fallback.cy) < gh * 1.2);
    const best = found[0] || null, ppm = +((best ? best.L / k : g.w * 1.08) / 1.28 / MODULES_EST).toFixed(1);
    const sharpNow = this._sharp(gx, gy, gw, gh), hist = this._sh = (this._sh || []).filter(h => now - h.t < 2500); hist.push({ t: now, v: sharpNow });
    const peak = Math.max(...hist.map(h => h.v)), present = !!best || all.some(c => c.L > gw * .35) || sharpNow >= .45, sharp = present && sharpNow >= SHARP_MIN && sharpNow >= .9 * peak;       // enfocado = hay código, nítido y cerca de lo mejor de los últimos 2,5 s
    this._drawGuide(g, sharp ? '#2ee59d' : present ? '#ffc857' : 'rgba(255,255,255,.9)', best, off, k);
    this.guideInfo = { ppm, found: !!best, sharp: +sharpNow.toFixed(2) };
    const tall = vh > vw;
    this.onStatus(ppm < 3.4 && tall ? 'Gira el celular a horizontal y acércate: así el código sale más nítido.' : ppm < 2.4 ? 'Acércate un poco: el código se ve pequeño.'
      : !present ? 'Encaja el código de barras dentro del recuadro.' : sharp ? 'Enfocado, analizando…' : 'Enfocando… mantén el celular firme.', present ? 'warn' : '');
    let r = null;
    if (best) r = await this._tryCandidate(work, best, PLANS.fast);
    if (!r && this.scanning) r = await this._tryCandidate(work, fallback, PLANS.fast);
    if (!r && this.scanning && !sharp && attempts % 6 === 0) r = await this._tryCandidate(work, best || fallback, PLANS.deep, performance.now() + 1200);     // respaldo periódico aunque no se mida enfoque
    if (!r && this.scanning && sharp && now - (this._lastDeep || 0) > 1500) {                 // enfocado: análisis a fondo de ESTE cuadro
      this._lastDeep = performance.now();
      if (best) r = await this._tryCandidate(work, best, PLANS.deep, this._lastDeep + 1600);                 // el rectángulo preciso del localizador primero
      if (!r && this.scanning) r = await this._tryCandidate(work, fallback, PLANS.deep, performance.now() + 1400);
    }
    if (!r && this.scanning && sharp && this.autoStill && now - (this._lastStill || 0) > 3000) {     // enfocado y sin lectura: foto fija de alta resolución, con tope de tiempo
      this._lastStill = performance.now(); const blob = await this.captureStill();
      if (blob && this.scanning) { const d = await this.scanImage(blob, { budgetMs: 2500 }); if (d) { this.scanning = false; video.pause(); return true; } }
    }
    if (!this.scanning) return false;
    if (!r) return false;
    this.scanning = false; video.pause(); this._drawGuide(g, '#2ee59d', null, off, k); this._handle(CedulaScanner._bytes(r.hit)); return true;
  }
  /** Un intento en modo libre (busca el código en todo el cuadro). Devuelve true si leyó la cédula. */
  async _freeStep(attempts) {
    const { video } = this, vw = video.videoWidth, vh = video.videoHeight;
    const cands = this.findCandidates(video, vw, vh);
    if (cands.length) {
      this._rect(cands[0], '#ffc857'); this.onStatus('Código detectado, mantén el celular firme…', 'warn');
      let r = await this._tryCandidate(video, cands[0], this.legacy ? PLANS.legacy : PLANS.fast);
      if (!r && cands[1] && !this.legacy) r = await this._tryCandidate(video, cands[1], PLANS.fast);
      if (!r && !this.legacy && attempts % 5 === 0) r = await this._tryCandidate(video, cands[0], PLANS.deep, performance.now() + 1500); // análisis a fondo periódico
      if (!this.scanning) return false;
      if (r) { this._finish(r.hit, r.cand); return true; }
    } else this._rect(null);
    if (!cands.length || attempts % 3 === 0) {
      const [rx, ry, rw, rh] = ROIS[(this._roi = (this._roi || 0) + 1) % ROIS.length];
      const sx = Math.round(rx*vw), sy = Math.round(ry*vh), sw = Math.round(rw*vw), sh = Math.round(rh*vh), k = Math.min(1, MAX_SIDE / Math.max(sw, sh));
      this.work.width = Math.round(sw*k); this.work.height = Math.round(sh*k);
      this.wctx.drawImage(video, sx, sy, sw, sh, 0, 0, this.work.width, this.work.height);
      const hit = CedulaScanner._hit(await this._decode(this.wctx.getImageData(0, 0, this.work.width, this.work.height)));
      if (!this.scanning) return false;
      if (hit) { this._finish(hit, null); return true; }
    }
    if (!cands.length && performance.now() - this.startedAt > 5000) this.onStatus('No veo el código. Acerca o aleja un poco, con buena luz y sin reflejos.', 'warn');
    return false;
  }
  /** Pide enfocar en un punto (coordenadas 0–1 del video); luego vuelve al enfoque continuo. */
  async refocus(nx, ny) {
    const t = this.track; if (!t) return false;
    try { await t.applyConstraints({ advanced: [{ focusMode: 'single-shot', pointsOfInterest: [{ x: nx, y: ny }] }] }); setTimeout(() => t && t.applyConstraints({ advanced: [{ focusMode: 'continuous' }] }).catch(() => {}), 1400); return true; }
    catch (e) { try { await t.applyConstraints({ advanced: [{ focusMode: 'continuous' }] }); } catch (_) {} return false; }
  }
  async _loop() {
    let lastStill = performance.now() - 1500, attempts = 0; const { video } = this;
    while (this.scanning) {
      try {
        if (video.readyState >= 2 && video.videoWidth) {
          attempts++;
          const finished = this.guideMode && !this.legacy ? await this._guideStep(attempts) : await this._freeStep(attempts);
          if (finished || !this.scanning) { if (finished) return; break; }
          // si pasan ~7 s sin leer, se pide una foto fija de alta resolución al sensor y se analiza a fondo
          if (this.autoStill && !this.legacy && !this.guideMode && performance.now() - lastStill > 4000) {
            lastStill = performance.now(); this.onStatus('Analizando una foto de alta resolución…', 'warn');
            const blob = await this.captureStill();
            if (blob && this.scanning) { const d = await this.scanImage(blob, { budgetMs: 6000 }); if (d) { this.scanning = false; this.video.pause(); return; } }
            if (this.scanning && performance.now() - this.startedAt > 9000 && !this._hintedPhoto) { this._hintedPhoto = true; this.onStatus('Si no lee en vivo, usa «Tomar foto»: abre la cámara del celular, que es mucho más nítida.', 'warn'); }
          }
        }
        if (this.guideMode && this.scanning && performance.now() - this.startedAt > 12000 && !this._hintedPhoto) { this._hintedPhoto = true; this.onStatus('Si no lee en vivo, usa «Tomar foto»: abre la cámara del celular, que es mucho más nítida.', 'warn'); }
      } catch (e) { console.error(e); this.onStatus('Error: ' + e.message, 'err'); }
      await sleep(GAP_MS);
    }
  }
}

/* ============ Cédula NUEVA: las 3 líneas de abajo (zona legible por máquina, «MRZ») ============
 * Cada línea tiene 30 caracteres (A–Z, 0–9 y «<» de relleno):
 *   1)  IC COL <n.º de documento(9)><dígito>…<<<<<
 *   2)  <nacimiento AAMMDD><dc><sexo><vence AAMMDD><dc> COL <cédula …><  …><dígito compuesto>
 *   3)  <APELLIDO1><APELLIDO2><<<NOMBRE1><NOMBRE2><<<<<
 * No se confía en posiciones fijas: la cédula se toma de lo que sigue a «COL» hasta el siguiente «<», y los nombres se separan por «<<» y «<».
 * Los dígitos de control (7-3-1) dicen si lo leído es correcto.
 */
const MRZ_D = { O: '0', Q: '0', D: '0', I: '1', L: '1', Z: '2', S: '5', B: '8', G: '6', T: '7' };   // letras que el OCR confunde con dígitos
const MRZ_A = { '0': 'O', '1': 'I', '2': 'Z', '5': 'S', '8': 'B', '6': 'G' };                       // y al revés (en la línea de nombres)
const mrzClean = s => String(s || '').toUpperCase().replace(/[«‹〈＜]/g, '<').replace(/[^A-Z0-9<]/g, '');
const mrzDig = s => s.replace(/[A-Z]/g, c => MRZ_D[c] || c);
const mrzAlf = s => s.replace(/[0-9]/g, c => MRZ_A[c] || c);
function mrzCheck(s) {
  let t = 0;
  for (let i = 0; i < s.length; i++) { const c = s[i], v = c === '<' ? 0 : (c >= '0' && c <= '9') ? +c : c.charCodeAt(0) - 55; t += v * [7, 3, 1][i % 3]; }
  return t % 10;
}
function mrzDate(s, birth) {                                       // 'AAMMDD' → 'AAAAMMDD' ('' si no es una fecha)
  if (!/^\d{6}$/.test(s)) return '';
  const yy = +s.slice(0, 2), m = +s.slice(2, 4), d = +s.slice(4, 6), cur = new Date().getUTCFullYear();
  let y = 2000 + yy; if (birth && y > cur) y -= 100;
  const dt = new Date(Date.UTC(y, m - 1, d));
  if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== m - 1 || dt.getUTCDate() !== d) return '';
  return String(y) + s.slice(2, 4) + s.slice(4, 6);
}
const mrzNat = (s, i) => /^C[O0Q][L1I]/.test(s.slice(i, i + 3));
/** Entiende las líneas leídas (en cualquier orden y con errores de OCR). Devuelve null si no encuentra la estructura. */
function parseMrz(raw) {
  const L = (raw || []).map(mrzClean).filter(s => s.length >= 8);
  if (L.length < 2) return null;
  let best = null;                                                  // línea 2 = la que tiene «COL» pasando el carácter ~15 y casi solo dígitos antes
  for (const s of L) for (let i = 12; i <= 18; i++) if (mrzNat(s, i)) {
    const pre = s.slice(0, i), dg = [...pre].filter(c => /[0-9OQDILZSBGT]/.test(c)).length;
    const sc = dg / pre.length - Math.abs(i - 15) * .04 + (s.length >= 26 && s.length <= 32 ? .1 : 0);
    if (!best || sc > best.sc) best = { s, i, sc };
  }
  if (!best || best.sc < .5) return null;
  const s2 = best.s, ci = best.i, pre = s2.slice(0, ci);
  let si = [7, 6, 8].find(k => /[MF]/.test(pre[k] || ''));
  if (si === undefined) { if (pre.length === 15) si = 7; else return null; }
  const sexo = /[MF]/.test(pre[si] || '') ? pre[si] : '';
  const bRaw = si >= 7 ? mrzDig(pre.slice(si - 7, si - 1)) : '', bChk = si >= 7 ? mrzDig(pre[si - 1]) : '';
  const eRaw = mrzDig(pre.slice(si + 1, si + 7)), eChk = mrzDig(pre[si + 7] || '');
  const nacimiento = mrzDate(bRaw, true), vencimiento = mrzDate(eRaw, false);
  const okB = !!nacimiento && bChk === String(mrzCheck(bRaw)), okE = !!vencimiento && eChk === String(mrzCheck(eRaw));
  // cédula: lo que sigue a «COL» hasta el siguiente «<» (si no hay «<», todo menos el último carácter, que es el dígito de control)
  const rest = s2.slice(ci + 3).replace(/^<+/, ''), k = rest.indexOf('<');
  const cedula = mrzDig(k > 0 ? rest.slice(0, k) : rest.slice(0, -1)).replace(/^0+(?=\d)/, '');
  if (!/^\d{4,11}$/.test(cedula)) return null;
  // línea 1 (n.º de documento) y línea 3 (nombres)
  const l1 = L.find(s => s !== s2 && [1, 2, 3, 4].some(i => mrzNat(s, i)) && /\d/.test(s.slice(5, 12))) || '';
  const lett = s => { const a = (s.match(/[A-Z]/g) || []).length, d = (s.match(/[0-9]/g) || []).length; return a / Math.max(1, a + d); };
  const l3 = L.filter(s => s !== s2 && s !== l1 && lett(s) >= .6).sort((a, b) => (/<</.test(b) - /<</.test(a)) || (b.length - a.length))[0] || '';
  let documento = '', okD = null;
  if (l1) { const ni = [1, 2, 3, 4].find(i => mrzNat(l1, i)); documento = l1.slice(ni + 3, ni + 12);
    if (documento.length === 9 && l1[ni + 12]) okD = [documento, mrzDig(documento)].some(d => String(mrzCheck(d)) === mrzDig(l1[ni + 12])); }
  let comp = null;                                                   // dígito compuesto: cubre el n.º de documento, las fechas y la cédula
  if (l1.length === 30 && s2.length === 30) {
    const fix = (s, from, to) => s.slice(0, from) + mrzDig(s.slice(from, to)) + s.slice(to);
    const dg = s => { const q = s.indexOf('<'); return q < 0 ? mrzDig(s) : mrzDig(s.slice(0, q)) + s.slice(q); };      // dígitos hasta el primer «<»
    const opt = dg(s2.slice(18, 29)), l1d = fix(l1, 5, 14), l1o = l1d.slice(0, 15) + dg(l1d.slice(15)), tail = mrzDig(s2.slice(0, 7)) + mrzDig(s2.slice(8, 15)) + opt;
    const v = [l1.slice(5, 30) + s2.slice(0, 7) + s2.slice(8, 15) + s2.slice(18, 29), l1d.slice(5, 30) + tail, l1o.slice(5, 30) + tail];
    comp = v.some(x => String(mrzCheck(x)) === mrzDig(s2[29]));
  }
  // nombres
  const t = mrzAlf(l3).replace(/[^A-Z<]/g, '').replace(/^<+|<+$/g, ''), j = t.indexOf('<<');
  let surnames = j > 0 ? t.slice(0, j).split('<').filter(Boolean) : [], given = j > 0 ? t.slice(j + 2).split('<').filter(Boolean) : [], guess = false;
  if (j <= 0 && t) {                                                 // sin el «<<» que separa apellidos de nombres: se adivina (2 apellidos + resto) y queda marcado como incierto
    const tk = t.split('<').filter(Boolean);
    if (tk.length >= 3) { surnames = tk.slice(0, 2); given = tk.slice(2); guess = true; } else if (tk.length === 2) { surnames = [tk[0]]; given = [tk[1]]; guess = true; }
  }
  const r = { cedula, apellido1: surnames[0] || '', apellido2: surnames.slice(1).join(' '), nombre1: given[0] || '', nombre2: given.slice(1).join(' '),
              nacimiento, sexo, vencimiento, documento, nombresIncierto: guess, checks: { birth: okB, expiry: okE, doc: okD, composite: comp }, lines: [l1, s2, l3] };
  r.linea = [r.cedula, r.nombre1, r.nombre2, r.apellido1, r.apellido2, r.nacimiento].join(',');
  return r;
}
/** «Fuerte» = los dígitos de control cuadran (incluido el compuesto, que cubre la cédula) y hay nombre y apellido. Los nombres no tienen control: por eso se confirman con otro cuadro. */
const mrzStrong = p => !!p && p.checks.birth && p.checks.expiry && p.checks.composite === true && !!p.nombre1 && !!p.apellido1 && !p.nombresIncierto;
const mrzKey = p => [p.cedula, p.nombre1, p.nombre2, p.apellido1, p.apellido2, p.nacimiento].join('|');

/* ---------- geometría pura sobre arrays de gris (también se prueba fuera del navegador) ---------- */
function mrzResize(g, w, h, nw, nh) {
  let src = g, sw = w, sh = h;
  const f = Math.min(Math.floor(w / nw), Math.floor(h / nh));
  if (f >= 2) {                                                     // al achicar mucho, primero promedio por bloques (evita aliasing)
    const rw = Math.floor(w / f), rh = Math.floor(h / f), o = new Uint8Array(rw * rh);
    for (let y = 0; y < rh; y++) for (let x = 0; x < rw; x++) { let s = 0; for (let dy = 0; dy < f; dy++) { const r = (y * f + dy) * w + x * f; for (let dx = 0; dx < f; dx++) s += g[r + dx]; } o[y * rw + x] = s / (f * f); }
    src = o; sw = rw; sh = rh;
  }
  const o = new Uint8Array(nw * nh), kx = sw / nw, ky = sh / nh;
  for (let y = 0; y < nh; y++) {
    const fy = Math.min(sh - 1, Math.max(0, (y + .5) * ky - .5)), y0 = Math.floor(fy), y1 = Math.min(sh - 1, y0 + 1), wy = fy - y0;
    for (let x = 0; x < nw; x++) {
      const fx = Math.min(sw - 1, Math.max(0, (x + .5) * kx - .5)), x0 = Math.floor(fx), x1 = Math.min(sw - 1, x0 + 1), wx = fx - x0;
      o[y * nw + x] = (src[y0 * sw + x0] * (1 - wx) + src[y0 * sw + x1] * wx) * (1 - wy) + (src[y1 * sw + x0] * (1 - wx) + src[y1 * sw + x1] * wx) * wy + .5;
    }
  }
  return o;
}
function mrzRot90(g, w, h, k) {                                     // gira k·90° en sentido horario → {g,w,h}
  k = ((k % 4) + 4) % 4; if (!k) return { g, w, h };
  const nw = k === 2 ? w : h, nh = k === 2 ? h : w, o = new Uint8Array(nw * nh);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const [X, Y] = k === 1 ? [h - 1 - y, x] : k === 2 ? [w - 1 - x, h - 1 - y] : [y, w - 1 - x]; o[Y * nw + X] = g[y * w + x];
  }
  return { g: o, w: nw, h: nh };
}
function mrzRotate(g, w, h, deg) {                                  // endereza: gira la imagen -deg (bilineal, bordes replicados)
  const a = deg * Math.PI / 180, c = Math.cos(a), s = Math.sin(a), cx = (w - 1) / 2, cy = (h - 1) / 2, o = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const dx = x - cx, dy = y - cy, sx = Math.min(w - 1, Math.max(0, cx + dx * c - dy * s)), sy = Math.min(h - 1, Math.max(0, cy + dx * s + dy * c));
    const x0 = Math.floor(sx), y0 = Math.floor(sy), x1 = Math.min(w - 1, x0 + 1), y1 = Math.min(h - 1, y0 + 1), fx = sx - x0, fy = sy - y0;
    o[y * w + x] = (g[y0 * w + x0] * (1 - fx) + g[y0 * w + x1] * fx) * (1 - fy) + (g[y1 * w + x0] * (1 - fx) + g[y1 * w + x1] * fx) * fy + .5;
  }
  return o;
}
/** Inclinación del texto en grados (positivo = las líneas bajan hacia la derecha): la que hace más «afilado» el perfil de filas. */
function mrzDeskew(g, w, h) {
  const nw = Math.min(480, w), nh = Math.max(8, Math.round(h * nw / w)), s = mrzResize(g, w, h, nw, nh), bin = binarGray(s, nw, nh), xs = [], ys = [];
  for (let y = 0; y < nh; y++) for (let x = 0; x < nw; x++) if (!bin[y * nw + x]) { xs.push(x); ys.push(y); }
  if (xs.length < 200) return 0;
  const cx = nw / 2, off = Math.ceil(nw * .2) + 2, score = a => {
    const t = Math.tan(a * Math.PI / 180), bins = new Float32Array(nh + 2 * off);
    for (let i = 0; i < xs.length; i++) bins[Math.round(ys[i] - (xs[i] - cx) * t) + off]++;
    let q = 0; for (let i = 0; i < bins.length; i++) q += bins[i] * bins[i]; return q;
  };
  let ba = 0, bs = score(0); for (let a = -7; a <= 7; a += .5) { const q = score(a); if (q > bs) { bs = q; ba = a; } }
  for (let a = ba - .5; a <= ba + .5; a += .1) { const q = score(a); if (q > bs) { bs = q; ba = a; } }
  return Math.abs(ba) < .3 ? 0 : +ba.toFixed(1);
}
/** Busca las 3 líneas de texto apiladas. bin: 0 = tinta. → {bands:[{y0,y1}], x0, x1, ok} */
function mrzBands(bin, w, h) {
  const prof = new Float32Array(h); let mx = 0;
  for (let y = 0; y < h; y++) { let n = 0; for (let x = 0; x < w; x++) if (!bin[y * w + x]) n++; prof[y] = n; }
  const p = new Float32Array(h); for (let y = 0; y < h; y++) { p[y] = ((prof[y - 1] || 0) + 2 * prof[y] + (prof[y + 1] || 0)) / 4; if (p[y] > mx) mx = p[y]; }
  if (mx < w * .03) return { ok: false, bands: [] };
  let runs = [], st = -1;
  for (let y = 0; y <= h; y++) { const on = y < h && p[y] > mx * .3; if (on && st < 0) st = y; if (!on && st >= 0) { runs.push({ y0: st, y1: y - 1 }); st = -1; } }
  for (let i = runs.length - 2; i >= 0; i--) if (runs[i + 1].y0 - runs[i].y1 <= 3) { runs[i].y1 = runs[i + 1].y1; runs.splice(i + 1, 1); }   // huecos mínimos dentro de una línea
  runs = runs.filter(r => r.y1 - r.y0 + 1 >= Math.max(5, h * .03));
  for (const r of runs) { r.m = 0; for (let y = r.y0; y <= r.y1; y++) r.m += p[y]; }
  while (runs.length > 3) { let k = 0; for (let i = 1; i < runs.length; i++) if (runs[i].m < runs[k].m) k = i; runs.splice(k, 1); }
  if (runs.length === 2) { const a = runs[0], b = runs[1], ha = a.y1 - a.y0 + 1, hb = b.y1 - b.y0 + 1;      // dos líneas pegadas contadas como una
    if (ha > hb * 1.7) { const m = Math.round((a.y0 + a.y1) / 2); runs = [{ y0: a.y0, y1: m - 1 }, { y0: m + 1, y1: a.y1 }, b]; }
    else if (hb > ha * 1.7) { const m = Math.round((b.y0 + b.y1) / 2); runs = [a, { y0: b.y0, y1: m - 1 }, { y0: m + 1, y1: b.y1 }]; } }
  if (runs.length !== 3) return { ok: false, bands: runs };
  const hs = runs.map(r => r.y1 - r.y0 + 1), ps = [runs[1].y0 - runs[0].y0, runs[2].y0 - runs[1].y0];
  const ok = Math.max(...hs) / Math.min(...hs) < 1.8 && Math.max(...ps) / Math.min(...ps) < 1.45;           // alturas y separación parecidas
  let x0 = w, x1 = -1; const colN = new Uint16Array(w);
  for (const r of runs) for (let y = r.y0; y <= r.y1; y++) for (let x = 0; x < w; x++) if (!bin[y * w + x]) colN[x]++;
  for (let x = 0; x < w; x++) if (colN[x] >= 2) { if (x < x0) x0 = x; x1 = x; }
  return { ok: ok && x1 > x0, bands: runs, x0, x1 };
}
/** Nitidez relativa: energía de bordes horizontales sobre la varianza, en las filas de texto. */
function mrzSharp(g, w, y0, y1) {
  let s = 0, m = 0, n = 0; for (let y = y0; y <= y1; y += 2) for (let x = 1; x < w - 1; x++) { const a = g[y * w + x + 1] - g[y * w + x - 1]; s += a * a; m += g[y * w + x]; n++; }
  if (!n) return 0; m /= n; let v = 0; for (let y = y0; y <= y1; y += 2) for (let x = 1; x < w - 1; x++) { const q = g[y * w + x] - m; v += q * q; }
  return (s / n) / (v / n + 1);
}
const MRZ_CAP = 36;                                                 // altura de las letras (px) con que se le entrega cada línea al OCR (se alterna 30 / 36 / 44 entre intentos)
/** Recorta cada línea, la lleva a ~44 px de alto de letra y le quita fondo/sombras. → [{g,w,h,x0,ext}] (x0 = inicio de la tinta, ext = ancho de la tinta, en px del recorte) */
function mrzCrops(g, w, h, info, cap = MRZ_CAP) {
  const out = [], PAD = 20;
  for (const b of info.bands) {
    const bh = b.y1 - b.y0 + 1, sc = Math.min(3.2, Math.max(.4, cap / bh)), pv = Math.round(bh * .55), ph = Math.round(bh * 1.0);
    const cy0 = Math.max(0, b.y0 - pv), cy1 = Math.min(h - 1, b.y1 + pv), cx0 = Math.max(0, info.x0 - ph), cx1 = Math.min(w - 1, info.x1 + ph), cw = cx1 - cx0 + 1, ch = cy1 - cy0 + 1;
    const sub = new Uint8Array(cw * ch); for (let y = 0; y < ch; y++) sub.set(g.subarray((cy0 + y) * w + cx0, (cy0 + y) * w + cx0 + cw), y * cw);
    const nw = Math.max(8, Math.round(cw * sc)), nh = Math.max(8, Math.round(ch * sc)), rs = mrzResize(sub, cw, ch, nw, nh);
    const bg = boxBlur(rs, nw, nh, Math.round(cap * 1.1)), W = nw + 2 * PAD, H = nh + 2 * PAD, o = new Uint8Array(W * H).fill(255);
    for (let y = 0; y < nh; y++) for (let x = 0; x < nw; x++) { const v = 255 - (bg[y * nw + x] - rs[y * nw + x]) * 2.8; o[(y + PAD) * W + x + PAD] = v < 0 ? 0 : v > 255 ? 255 : v; }
    out.push({ g: o, w: W, h: H, x0: (info.x0 - cx0) * (nw / cw) + PAD, ext: (info.x1 - info.x0 + 1) * (nw / cw) });
  }
  return out;
}
/** Análisis barato (imagen reducida, ~640 px de ancho): inclinación, dónde están las 3 líneas y qué tan nítidas. Aún no lee nada. */
function mrzScan(g, w, h) {
  const ang = mrzDeskew(g, w, h), r = ang ? mrzRotate(g, w, h, ang) : g, info = mrzBands(binarGray(r, w, h), w, h);
  info.angle = ang; info.w = w; info.h = h; info.sharp = info.ok ? mrzSharp(r, w, info.bands[0].y0, info.bands[2].y1) : 0;
  return info;
}
/** Recortes para el OCR a partir de la imagen COMPLETA ya enderezada (gRot, W×H); `info` viene de mrzScan sobre una versión reducida k veces. */
function mrzMakeCrops(gRot, W, H, info, k, cap) {
  const s = { bands: info.bands.map(b => ({ y0: Math.max(0, Math.round(b.y0 * k)), y1: Math.min(H - 1, Math.round(b.y1 * k)) })), x0: Math.max(0, Math.round(info.x0 * k)), x1: Math.min(W - 1, Math.round(info.x1 * k)) };
  return mrzCrops(gRot, W, H, s, cap);
}
/** Localiza las 3 líneas dentro de una foto cualquiera (otra orientación, la cédula en cualquier parte): 3 bloques de texto alargados, apilados y del mismo ancho. */
function mrzLocate(g, w, h) {
  let best = null;
  for (let rot = 0; rot < 2; rot++) {                              // 0 y 90°: las lecturas al revés (180°/270°) las prueba quien llama
    const R = mrzRot90(g, w, h, rot), nw = Math.min(720, R.w), nh = Math.round(R.h * nw / R.w), s = mrzResize(R.g, R.w, R.h, nw, nh), bin = binarGray(s, nw, nh);
    for (const gapK of [.007, .014]) {
      const G = Math.max(3, Math.round(nw * gapK)), cl = new Uint8Array(bin);                    // cierre horizontal: une las letras de cada línea en un bloque
      for (let y = 0; y < nh; y++) { let last = -1e9; for (let x = 0; x < nw; x++) if (!bin[y * nw + x]) { if (x - last <= G) for (let q = last + 1; q < x; q++) cl[y * nw + q] = 0; last = x; } }
      const lab = new Int32Array(nw * nh).fill(-1), blobs = [], st = [];
      for (let i = 0; i < nw * nh; i++) if (!cl[i] && lab[i] < 0) {
        const b = { x0: nw, y0: nh, x1: 0, y1: 0, n: 0 }; lab[i] = blobs.length; st.push(i);
        while (st.length) { const j = st.pop(), x = j % nw, y = (j / nw) | 0; b.n++; if (x < b.x0) b.x0 = x; if (x > b.x1) b.x1 = x; if (y < b.y0) b.y0 = y; if (y > b.y1) b.y1 = y;
          for (const k of [j - 1, j + 1, j - nw, j + nw]) if (k >= 0 && k < nw * nh && !cl[k] && lab[k] < 0 && Math.abs((k % nw) - x) <= 1) { lab[k] = blobs.length; st.push(k); } }
        blobs.push(b);
      }
      const L = blobs.filter(b => { const bw = b.x1 - b.x0 + 1, bh = b.y1 - b.y0 + 1; return bw >= nw * .12 && bh >= 3 && bw / bh >= 5 && bw / bh <= 60; }).sort((a, b) => a.y0 - b.y0);
      for (let i = 0; i < L.length; i++) for (let j = i + 1; j < L.length; j++) for (let k = j + 1; k < L.length; k++) {
        const A = L[i], B = L[j], C = L[k], wa = A.x1 - A.x0, ha = A.y1 - A.y0 + 1; if (B.y0 - A.y1 > ha * 2) break;
        const ok = (P, Q) => Math.abs(P.x0 - Q.x0) < wa * .1 && Math.abs((P.x1 - P.x0) - (Q.x1 - Q.x0)) < wa * .15 && Q.y0 - P.y1 > -ha * .2 && Q.y0 - P.y1 < ha * 1.2 && Math.abs((Q.y1 - Q.y0 + 1) - ha) < ha * .6;
        if (!ok(A, B) || !ok(B, C)) continue;
        const sc = wa * (1 - Math.abs((B.y0 - A.y0) - (C.y0 - B.y0)) / (ha * 3));
        if (!best || sc / nw > best.sc) best = { sc: sc / nw, rot, x0: Math.min(A.x0, B.x0, C.x0) / nw, x1: Math.max(A.x1, B.x1, C.x1) / nw, y0: A.y0 / nh, y1: C.y1 / nh, R };
      }
    }
  }
  if (!best) return null;
  const { R } = best, mx = (best.x1 - best.x0) * .06, my = (best.y1 - best.y0) * .35;
  const X0 = Math.max(0, Math.floor((best.x0 - mx) * R.w)), X1 = Math.min(R.w, Math.ceil((best.x1 + mx) * R.w)), Y0 = Math.max(0, Math.floor((best.y0 - my) * R.h)), Y1 = Math.min(R.h, Math.ceil((best.y1 + my) * R.h));
  const cw = X1 - X0, ch = Y1 - Y0, sub = new Uint8Array(cw * ch); for (let y = 0; y < ch; y++) sub.set(R.g.subarray((Y0 + y) * R.w + X0, (Y0 + y) * R.w + X0 + cw), y * cw);
  return { g: sub, w: cw, h: ch, rot: best.rot, score: best.sc, flip: () => { const f = mrzRot90(sub, cw, ch, 2); return { g: f.g, w: f.w, h: f.h, rot: best.rot + 2, score: best.sc }; } };
}

/* ---------- del resultado del OCR a una línea de 30 columnas ---------- */
/** syms: [{c, conf, cx}] en px del recorte. El paso entre celdas se mide con los propios símbolos; quita duplicados (dos símbolos en la misma celda) y rellena huecos con «<» (el OCR suele «perder» los «<»). */
function mrzGrid(syms, x0, ext, n = 30) {
  const S = syms.slice().sort((a, b) => a.cx - b.cx), p0 = ext / (n - .3), d = [];
  for (let i = 1; i < S.length; i++) { const g = S[i].cx - S[i - 1].cx; if (g > .65 * p0 && g < 1.5 * p0) d.push(g); }
  d.sort((a, b) => a - b); const p = d.length >= 5 ? d[d.length >> 1] : p0, keep = [];
  for (const s of S) { const l = keep[keep.length - 1]; if (l && s.cx - l.cx < .62 * p) { if (s.conf > l.conf) keep[keep.length - 1] = s; } else keep.push(s); }
  let txt = '', conf = [];
  keep.forEach((s, i) => {
    if (i) { const gap = Math.round((s.cx - keep[i - 1].cx) / p) - 1; for (let q = 0; q < Math.min(gap, 4); q++) { txt += '<'; conf.push(0); } }
    txt += s.c; conf.push(s.conf);
  });
  return { text: txt, conf };
}


/* ============ OCR en el navegador (Tesseract.js: se descarga la primera vez y queda en caché) ============ */
const TESS_VER = '5.1.1';
const TESS_SRC = [`https://cdn.jsdelivr.net/npm/tesseract.js@${TESS_VER}/dist/tesseract.min.js`, `https://unpkg.com/tesseract.js@${TESS_VER}/dist/tesseract.min.js`];
const TESS_LANG = ['https://cdn.jsdelivr.net/npm/@tesseract.js-data/eng/4.0.0_best_int', 'https://unpkg.com/@tesseract.js-data/eng/4.0.0_best_int'];
const MRZ_WL = ['ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<', '0123456789MFCOLX<', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ<'];   // un trabajador por línea, cada uno con SOLO los caracteres posibles en esa línea
const MRZ_GUIDE_AR = 4.6;                                           // proporción ancho/alto del recuadro (las 3 líneas miden ~5.5:1; el recuadro deja margen)
const MRZ_W = 1400;                                                 // ancho máximo del recorte que se analiza
const MRZ_CAPS = [36, 30, 44];                                      // alto de letra con que se le pasa la línea al OCR; se alterna entre intentos
const loadScript = url => new Promise((res, rej) => { const s = document.createElement('script'); s.src = url; s.onload = res; s.onerror = () => rej(new Error('no se pudo descargar ' + url)); document.head.appendChild(s); });
function symbolsOf(d) {                                             // símbolos {c, conf, cx} de la respuesta de tesseract.js (v5: data.symbols; si no, bloques → … → símbolos)
  let S = Array.isArray(d.symbols) ? d.symbols : null;
  if (!S && Array.isArray(d.blocks)) { S = []; for (const b of d.blocks) for (const p of b.paragraphs || []) for (const l of p.lines || []) for (const w of l.words || []) for (const s of w.symbols || []) S.push(s); }
  return (S || []).filter(s => s && s.bbox && typeof s.text === 'string' && /^[A-Z0-9<]$/.test(s.text)).map(s => ({ c: s.text, conf: s.confidence || 0, cx: (s.bbox.x0 + s.bbox.x1) / 2 }));
}
const grayCanvas = (g, w, h) => { const c = document.createElement('canvas'); c.width = w; c.height = h; c.getContext('2d').putImageData(fromGray(g, w, h), 0, 0); return c; };

class MrzOcr {
  constructor() { this.workers = []; this.ready = false; this._p = null; }
  load() { return this._p || (this._p = this._load().catch(e => { this._p = null; throw e; })); }
  async _load() {
    const V = window.CEDULA_VENDOR;                                   // copia propia (scripts/vendor_cedula_readers.sh) primero; si no está, CDN
    const SRC = [...(V ? [`${V}/tesseract/tesseract.min.js`] : []), ...TESS_SRC];
    if (!window.Tesseract) {
      let err; for (const u of SRC) { try { await loadScript(u); if (window.Tesseract) break; } catch (e) { err = e; } }
      if (!window.Tesseract) throw err || new Error('No se pudo cargar el lector de texto (revisa la conexión).');
    }
    const LANGS = [...(V ? [{ workerPath: `${V}/tesseract/worker.min.js`, corePath: `${V}/tesseract-core`, langPath: `${V}/tesseract-lang` }] : []), ...TESS_LANG.map(langPath => ({ langPath }))];
    let last;
    for (const lp of LANGS) {
      try {
        const mkw = async wl => { const w = await window.Tesseract.createWorker('eng', 1, { ...lp, gzip: true, logger: () => {} });
          await w.setParameters({ tessedit_char_whitelist: wl, tessedit_pageseg_mode: '7', user_defined_dpi: '300' }); return w; };
        const first = await mkw(MRZ_WL[0]);                           // el primero baja y guarda el idioma; los otros ya lo encuentran en caché
        const rest = await Promise.all(MRZ_WL.slice(1).map(mkw));
        this.workers = [first, ...rest]; this.ready = true; return;
      } catch (e) { last = e; }
    }
    throw last || new Error('No se pudieron cargar los datos del idioma.');
  }
  /** crops: [{g,w,h}] (línea 1, 2 y 3) → [{text, conf}] */
  async read(crops) {
    return Promise.all(crops.map((c, i) => this.workers[i].recognize(grayCanvas(c.g, c.w, c.h)).then(r => {
      const d = r.data || {}, raw = String(d.text || '').replace(/\s+/g, ''), syms = symbolsOf(d);
      let text = raw;
      if (syms.length >= 8) {                                        // con la posición de cada letra: se rellenan los «<» perdidos y se quitan duplicados
        text = mrzGrid(syms, c.x0, c.ext).text;
        if (i !== 1 && text.length < 30 && text.length >= 20) text += '<'.repeat(30 - text.length);      // líneas 1 y 3 terminan en relleno «<»
      }
      return { text, raw, conf: Math.round(d.confidence || 0) };
    })));
  }
}

class MrzScanner {
  /** onlyVerified: solo entrega lecturas con los dígitos de control en regla (para acreditar personas); sin eso también entrega «aproximadas». */
  constructor({ onResult = () => {}, onStatus = () => {}, onlyVerified = false } = {}) {
    this.onResult = onResult; this.onStatus = onStatus; this.onlyVerified = onlyVerified; this.ocr = new MrzOcr(); [this.work, this.wctx] = mk(); [this.rot, this.rctx] = mk();
    this.scanning = false; this.lastDebug = null; this._reset();
  }
  _reset() { this.votes = new Map(); this.fails = 0; this.flip = false; this.attempt = 0; this.sh = []; this.lastOcr = 0; }
  init() { return this.ocr.load(); }
  async startCamera(video, overlay) {
    this.video = video; this.overlay = overlay; this.octx = overlay ? overlay.getContext('2d') : null; let last = null; this.stream = null;
    for (const size of [{ width: { ideal: 3840 }, height: { ideal: 2160 } }, { width: { ideal: 2560 }, height: { ideal: 1440 } }, {}]) {
      try { this.stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: { facingMode: { ideal: 'environment' }, ...size } }); break; }
      catch (e) { last = e; if (e.name === 'NotAllowedError' || e.name === 'SecurityError' || e.name === 'NotFoundError') throw e; }
    }
    if (!this.stream) throw last || new Error('No se pudo abrir la cámara');
    this.track = this.stream.getVideoTracks()[0];
    try { await this.track.applyConstraints({ advanced: [{ focusMode: 'continuous' }] }); } catch (e) {}
    video.srcObject = this.stream; video.setAttribute('playsinline', ''); video.muted = true; await video.play();
    this._reset(); this.scanning = true; this._loop(); this.ocr.load().catch(() => {});
  }
  async setTorch(on) { try { await this.track.applyConstraints({ advanced: [{ torch: !!on }] }); return true; } catch (e) { return false; } }
  resume() { if (this.stream && !this.scanning) { this.video.play(); this._reset(); this.scanning = true; this._loop(); } }
  stop() {
    this.scanning = false; if (this.stream) this.stream.getTracks().forEach(t => t.stop());
    this.stream = this.track = null; if (this.video) this.video.srcObject = null; if (this.octx) this.octx.clearRect(0, 0, this.overlay.width, this.overlay.height);
  }
  async refocus(nx, ny) {
    const t = this.track; if (!t) return false;
    try { await t.applyConstraints({ advanced: [{ focusMode: 'single-shot', pointsOfInterest: [{ x: nx, y: ny }] }] }); setTimeout(() => t && t.applyConstraints({ advanced: [{ focusMode: 'continuous' }] }).catch(() => {}), 1400); return true; }
    catch (e) { try { await t.applyConstraints({ advanced: [{ focusMode: 'continuous' }] }); } catch (_) {} return false; }
  }
  /** Recuadro guía en píxeles del video, sobre la parte VISIBLE (el video se muestra con object-fit: cover). */
  _guideRect(vw, vh) {
    const r = this.video.getBoundingClientRect(); let visW = vw, visH = vh;
    if (r.width && r.height) { const k = Math.max(r.width / vw, r.height / vh); visW = r.width / k; visH = r.height / k; }
    const x0 = (vw - visW) / 2, y0 = (vh - visH) / 2, w = Math.min(visW * .94, visH * .94 * MRZ_GUIDE_AR), h = w / MRZ_GUIDE_AR;
    return { x: x0 + (visW - w) / 2, y: y0 + (visH - h) / 2, w, h };
  }
  _drawGuide(g, color) {
    if (!this.octx) return; const { overlay, octx, video } = this, vw = video.videoWidth, vh = video.videoHeight;
    if (overlay.width !== vw || overlay.height !== vh) { overlay.width = vw; overlay.height = vh; }
    octx.clearRect(0, 0, vw, vh); octx.fillStyle = 'rgba(0,0,0,.45)'; octx.beginPath(); octx.rect(0, 0, vw, vh); octx.rect(g.x, g.y, g.w, g.h); octx.fill('evenodd');
    const lw = Math.max(4, vw / 260), c = Math.min(g.h * .35, g.w * .06);
    octx.lineWidth = lw; octx.strokeStyle = color; octx.lineCap = 'round'; octx.strokeRect(g.x, g.y, g.w, g.h); octx.lineWidth = lw * 1.8;
    [[g.x, g.y, 1, 1], [g.x + g.w, g.y, -1, 1], [g.x, g.y + g.h, 1, -1], [g.x + g.w, g.y + g.h, -1, -1]].forEach(([x, y, sx, sy]) => { octx.beginPath(); octx.moveTo(x, y + sy * c); octx.lineTo(x, y); octx.lineTo(x + sx * c, y); octx.stroke(); });
    octx.lineWidth = lw * .5; octx.strokeStyle = color + '88'; octx.setLineDash([lw * 3, lw * 3]);                     // 3 renglones de ayuda: dónde caen las 3 líneas
    [1 / 6, .5, 5 / 6].forEach(f => { octx.beginPath(); octx.moveTo(g.x + g.w * .03, g.y + g.h * f); octx.lineTo(g.x + g.w * .97, g.y + g.h * f); octx.stroke(); }); octx.setLineDash([]);
  }
  /** Copia fija de la zona del recuadro (con un poco de margen) → gris a resolución completa de trabajo. */
  _grab(src, sx, sy, sw, sh, k) {
    const w = Math.round(sw * k), h = Math.round(sh * k); this.work.width = w; this.work.height = h; this.wctx.drawImage(src, sx, sy, sw, sh, 0, 0, w, h);
    return { gray: toGray(this.wctx.getImageData(0, 0, w, h)), w, h };
  }
  /** Imagen en gris → [textos de las 3 líneas] (o null si no se ven 3 líneas). `canvasRot`: enderezar con el lienzo (rápido) en vez de en JS. */
  async _read(gray, W, H, opts = {}) {
    const sw = Math.min(640, W), sh = Math.max(8, Math.round(H * sw / W)), info = opts.info || mrzScan(mrzResize(gray, W, H, sw, sh), sw, sh); if (!info.ok) return { info };
    let gr = gray;
    if (info.angle) {
      if (opts.fromCanvas) { const { rot, rctx } = this; rot.width = W; rot.height = H; rctx.fillStyle = '#c8c8c8'; rctx.fillRect(0, 0, W, H); rctx.save(); rctx.translate(W / 2, H / 2); rctx.rotate(-info.angle * Math.PI / 180); rctx.drawImage(this.work, -W / 2, -H / 2); rctx.restore(); gr = toGray(rctx.getImageData(0, 0, W, H)); }
      else gr = mrzRotate(gray, W, H, info.angle);
    }
    let crops = mrzMakeCrops(gr, W, H, info, W / sw, MRZ_CAPS[(opts.attempt || 0) % MRZ_CAPS.length]);
    if (opts.flip) crops = crops.reverse().map(c => { const f = mrzRot90(c.g, c.w, c.h, 2); return { g: f.g, w: f.w, h: f.h }; });   // cédula al revés: se leen las líneas giradas 180°
    const texts = await this.ocr.read(crops); return { info, texts, crops };
  }
  _consider(texts) {                                                // ¿ya hay una lectura confiable? → parsed | null
    const parsed = parseMrz(texts.map(t => t.text)), conf = texts.map(t => t.conf);
    this.lastDebug = { lines: texts.map(t => t.text), conf, parsed };
    if (!parsed) { this.fails++; if (this.fails % 3 === 0) this.flip = !this.flip; return null; }
    this.fails = 0;
    const key = mrzKey(parsed), n = (this.votes.get(key) || 0) + 1; this.votes.set(key, n);
    if (mrzStrong(parsed)) {
      if (n >= 2 || Math.min(...conf) >= 80) return { ...parsed, verificada: true };                   // controles OK + dos cuadros iguales (o letras muy seguras)
    } else if (!this.onlyVerified && parsed.checks.birth && parsed.checks.expiry && n >= 3) return { ...parsed, verificada: false, aproximado: true };
    return null;
  }
  async _step() {
    const { video } = this, vw = video.videoWidth, vh = video.videoHeight, g = this._guideRect(vw, vh), now = performance.now();
    const rx = Math.max(0, g.x - g.w * .03), ry = Math.max(0, g.y - g.h * .05), rw = Math.min(vw - rx, g.w * 1.06), rh = Math.min(vh - ry, g.h * 1.10), k = Math.min(1, MRZ_W / rw);
    const { gray, w: W, h: H } = this._grab(video, rx, ry, rw, rh, k);
    const sw = Math.min(640, W), sh = Math.max(8, Math.round(H * sw / W)), info = mrzScan(mrzResize(gray, W, H, sw, sh), sw, sh);
    const hist = this.sh = this.sh.filter(h => now - h.t < 1500); if (info.ok) hist.push({ t: now, v: info.sharp });
    const peak = Math.max(0, ...hist.map(h => h.v)), present = info.ok, sharp = present && info.sharp >= .85 * peak && info.sharp >= .12;
    this._drawGuide(g, sharp ? '#2ee59d' : present ? '#ffc857' : 'rgba(255,255,255,.9)');
    if (!this.ocr.ready) { this.onStatus('Cargando el lector de texto… (la primera vez tarda unos segundos)', 'warn'); return false; }
    if (!present) { this.onStatus('Encaja las 3 líneas de letras y números (las de abajo) dentro del recuadro.', ''); return false; }
    if (!sharp && now - this.lastOcr < 1500) { this.onStatus('Enfocando… mantén el celular firme.', 'warn'); return false; }
    this.lastOcr = now; this.onStatus('Leyendo…', 'warn'); const t0 = performance.now();
    const r = await this._read(gray, W, H, { info, fromCanvas: true, flip: this.flip, attempt: this.attempt++ }); if (!this.scanning) return false;
    if (!r.texts) return false;
    const done = this._consider(r.texts); if (this.lastDebug) this.lastDebug.ms = Math.round(performance.now() - t0);
    if (!done) { this.onStatus(this.fails >= 3 ? 'No logro leer: acércate un poco, evita reflejos y mantén las 3 líneas dentro del recuadro.' : 'Confirmando…', 'warn'); return false; }
    this.scanning = false; video.pause(); this._drawGuide(g, '#2ee59d'); this.onResult(done); return true;
  }
  async _loop() {
    const { video } = this, id = this._lid = (this._lid || 0) + 1;                // un solo bucle activo a la vez
    while (this.scanning && id === this._lid) {
      try { if (video.readyState >= 2 && video.videoWidth && await this._step()) return; }
      catch (e) { console.error(e); this.onStatus('Error: ' + e.message, 'err'); }
      await sleep(40);
    }
  }
  /** Foto de diagnóstico: lee UN cuadro sin esperar nitidez y devuelve lo que vio (recortes, texto de cada línea y qué falló). */
  async diagnose() {
    const { video } = this, vw = video.videoWidth, vh = video.videoHeight, g = this._guideRect(vw, vh);
    const rx = Math.max(0, g.x - g.w * .03), ry = Math.max(0, g.y - g.h * .05), rw = Math.min(vw - rx, g.w * 1.06), rh = Math.min(vh - ry, g.h * 1.10), k = Math.min(1, MRZ_W / rw);
    await this.ocr.load(); const { gray, w: W, h: H } = this._grab(video, rx, ry, rw, rh, k);
    return this._diagnoseGray(gray, W, H, 'cuadro de video');
  }
  async _diagnoseGray(gray, W, H, source, flips = [false, true]) {
    const out = { source, w: W, h: H, tries: [] }; let preview = null;
    for (const flip of flips) {
      const r = await this._read(gray, W, H, { flip, attempt: flip ? 1 : 0 });
      if (!r.texts) { out.tries.push({ flip, found: false, bands: r.info.bands.length }); if (!flip) out.hint = 'No se distinguen 3 líneas de texto parecidas dentro del recuadro.'; continue; }
      const p = parseMrz(r.texts.map(t => t.text)); out.tries.push({ flip, found: true, lines: r.texts.map(t => t.text), conf: r.texts.map(t => t.conf), parsed: p });
      if (!preview) { const cw = Math.max(...r.crops.map(c => c.w)), ch = r.crops.reduce((a, c) => a + c.h, 0), cv = document.createElement('canvas'); cv.width = cw; cv.height = ch;
        let y = 0; r.crops.forEach(c => { cv.getContext('2d').putImageData(fromGray(c.g, c.w, c.h), 0, y); y += c.h; }); preview = cv.toDataURL('image/jpeg', .8); }
      if (mrzStrong(p)) { out.parsed = p; break; }
      if (p && !out.parsed) out.parsed = p;
    }
    out.preview = preview; return out;
  }
  /** Foto / galería: busca las 3 líneas en cualquier parte y orientación de la imagen. */
  async scanImage(file) {
    await this.ocr.load();
    const bmp = await createImageBitmap(file), k = Math.min(1, 2400 / Math.max(bmp.width, bmp.height)), W = Math.round(bmp.width * k), H = Math.round(bmp.height * k);
    this.work.width = W; this.work.height = H; this.wctx.drawImage(bmp, 0, 0, W, H); if (bmp.close) bmp.close();
    const gray = toGray(this.wctx.getImageData(0, 0, W, H)), loc = mrzLocate(gray, W, H);
    const variants = loc ? [loc, loc.flip()] : [0, 1, 2, 3].map(r => mrzRot90(gray, W, H, r));
    let best = null, dbg = { source: 'foto', w: W, h: H, tries: [], located: !!loc };
    for (const v of variants) {
      const d = await this._diagnoseGray(v.g, v.w, v.h, 'foto', [false]); dbg.tries.push(...d.tries); if (d.preview && !dbg.preview) dbg.preview = d.preview;
      if (d.parsed && (!best || mrzStrong(d.parsed))) best = d.parsed; if (mrzStrong(best)) break;
    }
    this.lastDebug = dbg;
    if (best && best.checks.birth && best.checks.expiry) { const strong = mrzStrong(best); this.onResult({ ...best, verificada: strong, aproximado: !strong }); return best; }
    return null;
  }
}

window.CedulaReaders = { CedulaScanner, MrzScanner, parseCedula, parseMrz, mrzStrong, formatBirth };
})();
