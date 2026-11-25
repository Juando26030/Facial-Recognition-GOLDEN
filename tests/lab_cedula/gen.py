# ruff: noqa
"""Fotos SINTÉTICAS del reverso de una cédula nueva (datos inventados) para probar el recorte automático. Ver LEEME.md."""
import os
import sys, random, numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont
random.seed(7); np.random.seed(7)
MONO=os.environ.get('LAB_FONT','/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf')   # cualquier monoespaciada con el cero SIN punto
import subprocess, json, os
from pathlib import Path
HERE=Path(__file__).resolve().parent; OUT=Path(os.environ.get('LAB_OUT','/tmp/lab_cedula')); (OUT/'img').mkdir(parents=True,exist_ok=True); (OUT/'rnd').mkdir(exist_ok=True)
L=json.loads(subprocess.check_output(['node',str(HERE/'mk.js')]))
def card(W=1712):
    H=int(W*54/85.6); im=Image.new('L',(W,H),228); d=ImageDraw.Draw(im)
    f=ImageFont.truetype(MONO,int(W*0.022)); fs=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',int(W*0.02))
    for i,t in enumerate(['FECHA Y LUGAR DE NACIMIENTO','15 MAY 1990 BOGOTA D.C.','ESTATURA 1.65   G.S. O+   SEXO F','FECHA Y LUGAR DE EXPEDICION','01 ENE 2022 BOGOTA D.C.','REGISTRADOR NACIONAL']):
        d.text((int(W*0.05),int(H*(0.07+i*0.075))),t,font=fs,fill=60)
    # bloque tipo código 2D a la derecha
    bx,by,bs=int(W*0.68),int(H*0.08),int(W*0.26); a=(np.random.rand(40,40)>0.5).astype(np.uint8)*255
    im.paste(Image.fromarray(a).resize((bs,int(bs*0.8)),Image.NEAREST),(bx,by))
    # huella
    d.ellipse((int(W*0.45),int(H*0.1),int(W*0.62),int(H*0.5)),outline=90,width=3)
    fm=ImageFont.truetype(MONO,int(W*(76.2/85.6)/30/0.600))
    for i,t in enumerate(L): d.text((int(W*0.055),int(H*(0.72+i*0.0783))),t,font=fm,fill=25)
    return np.array(im)
def card_old(W=1712):
    """Reverso de una cédula VIEJA de mentira: un «código» de módulos al azar (no es un PDF417 real) con un bloque negro macizo a la IZQUIERDA y franjas a la derecha,
    para que el decodificador de reemplazo de srv.py sepa si le llegó derecho o al revés."""
    H=int(W*54/85.6); im=np.full((H,W),225,np.uint8)
    x0,x1,y0,y1=int(W*.08),int(W*.92),int(H*.10),int(H*.36); cols,rows=300,26
    a=(np.random.rand(rows,cols)>0.5).astype(np.uint8)*255
    im[y0:y1,x0:x1]=cv2.resize(a,(x1-x0,y1-y0),interpolation=cv2.INTER_NEAREST)
    im[y0:y1,x0-int(W*.035):x0-int(W*.008)]=15                                   # bloque de inicio (macizo)
    for k in range(4): im[y0:y1,x1+int(W*.008)+k*int(W*.008):x1+int(W*.008)+k*int(W*.008)+int(W*.003)]=15   # fin: rayas finas
    pil=Image.fromarray(im); d=ImageDraw.Draw(pil); fs=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',int(W*0.022))
    for i,t in enumerate(['FECHA Y LUGAR DE EXPEDICION','30-JUN-2015 CIUDAD','ESTATURA 1.65   G.S. RH O+   SEXO M','LUGAR DE NACIMIENTO']): d.text((int(W*0.12),int(H*(0.46+i*0.1))),t,font=fs,fill=60)
    d.ellipse((int(W*0.72),int(H*0.5),int(W*0.9),int(H*0.92)),outline=90,width=3)
    return np.array(pil)
def scene(pw,ph,frac,dx,dy,ang,blur=0,glare=False,persp=0,old=False,glare_at=0.45,glare_r=.12):
    c=card_old() if old else card(); ch,cw=c.shape
    bg=np.clip(np.random.normal(120,18,(ph,pw)),0,255).astype(np.uint8); bg=cv2.GaussianBlur(bg,(0,0),6)
    # mesa con vetas
    for k in range(0,ph,37): bg[k:k+2,:]=np.clip(bg[k:k+2,:].astype(int)-25,0,255)
    s=frac*pw/cw; M=cv2.getRotationMatrix2D((cw/2,ch/2),ang,s); M[0,2]+=pw/2-cw/2+dx*pw; M[1,2]+=ph/2-ch/2+dy*ph
    src=np.float32([[0,0],[cw,0],[cw,ch],[0,ch]]); dst=cv2.transform(src[None],M)[0]
    if persp: dst[0]+= [persp*pw*0.02, persp*ph*0.02]; dst[1]+=[-persp*pw*0.02, persp*ph*0.02]
    P=cv2.getPerspectiveTransform(src,np.float32(dst))
    w=cv2.warpPerspective(c,P,(pw,ph),flags=cv2.INTER_AREA if s<1 else cv2.INTER_CUBIC,borderValue=0)
    m=cv2.warpPerspective(np.full_like(c,255),P,(pw,ph))
    out=np.where(m>127,w,bg)
    if glare:
        g=np.zeros((ph,pw),np.float32); gy=(glare_at-.5)*frac*pw*54/85.6; cv2.circle(g,(int(pw*0.5+dx*pw),int(ph*0.5+dy*ph+gy)),int(pw*frac*glare_r),1,-1); g=cv2.GaussianBlur(g,(0,0),pw*frac*0.05)
        out=np.clip(out+g*200,0,255).astype(np.uint8)
    if blur: out=cv2.GaussianBlur(out,(0,0),blur)
    out=np.clip(out+np.random.normal(0,3,out.shape),0,255).astype(np.uint8)
    return out
cases={
 'full_1080':(1920,1080,.92,0,0.0,0), 'small65':(1920,1080,.65,0,0.05,0), 'small45':(1920,1080,.45,.1,-.1,0),'small30_4k':(3840,2160,.30,-.2,.15,0),
 'small30_1080':(1920,1080,.30,-.2,.15,0),'rot4':(1920,1080,.7,0,0,4),'rot10':(1920,1080,.7,0.05,0,10),'rot20':(1920,1080,.6,0,0,20),'rot90':(1920,1080,.5,0,0,90),'rot180':(1920,1080,.7,0,0,180),
 'cutbottom':(1920,1080,.8,0,.22,0),'persp':(1920,1080,.7,0,0,3),'blur':(1920,1080,.6,0,0,2),'vert_1080x1920':(1080,1920,.9,0,0,0),'vert_small':(1080,1920,.6,0,.2,5),'glare':(1920,1080,.7,0,0,0),
}
for n,(pw,ph,fr,dx,dy,an) in cases.items():
    cv2.imwrite(str(OUT/'img'/f'{n}.png'),scene(pw,ph,fr,dx,dy,an,blur=1.6 if n=='blur' else 0,glare=n=='glare',persp=1 if n=='persp' else 0))
(OUT/'img2').mkdir(exist_ok=True); (OUT/'old').mkdir(exist_ok=True)
# 24-nov (tarde): torcida de verdad (se lee girando la búsqueda 45°), brillo SOBRE las letras (debe avisar de una vez) y cédula vieja derecho / al revés / torcida / con brillo
for n,(pw,ph,fr,dx,dy,an,kw) in {'rot45':(1920,1080,.5,0,0,45,{}),'rot60':(1920,1080,.5,0,0,60,{}),'rotm40':(1080,1920,.75,0,0,-40,{}),'rot135':(1920,1080,.5,0,0,135,{}),
        'glare_mrz':(1920,1080,.7,0,0,0,dict(glare=True,glare_at=.82)),'glare_mrz_vert':(1080,1920,.9,0,.1,3,dict(glare=True,glare_at=.8)),'sin_cedula':(1920,1080,.01,0,0,0,{})}.items():
    cv2.imwrite(str(OUT/'img2'/f'{n}.png'),scene(pw,ph,fr,dx,dy,an,**kw))
for n,(pw,ph,fr,dx,dy,an,kw) in {'derecho':(1080,1920,.92,0,0,0,{}),'al_reves':(1080,1920,.92,0,0,180,{}),'pequena_al_reves':(1920,1080,.5,.1,-.1,180,{}),'torcida30':(1920,1080,.6,0,0,30,{}),
        'torcida_reves':(1080,1920,.8,0,.1,205,{}),'de_lado':(1080,1920,.55,0,0,90,{}),'brillo':(1080,1920,.92,0,0,0,dict(glare=True,glare_at=.23)),'brillo_fuerte':(1080,1920,.92,0,0,0,dict(glare=True,glare_at=.23,glare_r=.2)),'sin_cedula':(1920,1080,.01,0,0,0,{})}.items():
    cv2.imwrite(str(OUT/'old'/f'{n}.png'),scene(pw,ph,fr,dx,dy,an,old=True,**kw))
random.seed(11); np.random.seed(3)
for i in range(60):                                   # 60 fotos al azar: tamaño, posición, giro, desenfoque, brillo, perspectiva e iluminación desigual
    port=random.random()<.3; pw,ph=(1080,1920) if port else random.choice([(1920,1080),(1920,1080),(3840,2160),(1280,720)])
    frac=random.uniform(.3,.95) if not port else random.uniform(.55,.98); cw=frac*pw; chh=cw*54/85.6
    dx=random.uniform(-1,1)*max(0,(pw-cw)/2/pw)*.9; dy=random.uniform(-1,1)*max(0,(ph-chh)/2/ph)*.9
    ang=random.choice([0,0,random.uniform(-6,6),random.uniform(-18,18)])
    if abs(ang)>8: dx*=.5; dy*=.5
    o=scene(pw,ph,frac,dx,dy,ang,blur=random.choice([0,0,.8,1.3]),glare=random.random()<.25,persp=random.choice([0,0,1,-1]))
    gx=np.linspace(random.uniform(.6,1),random.uniform(.6,1.1),pw)[None,:]; cv2.imwrite(str(OUT/'rnd'/f'r{i:02d}.png'),np.clip(o*gx,0,255).astype(np.uint8))
print('fotos en',OUT)
