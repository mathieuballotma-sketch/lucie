#!/usr/bin/env python3
"""Scene club complete (style video de ref IMG_7479) avec 'MONTE LE SON' :
fond noir + fumee, lumieres de couleur qui changent, lasers, mur LED avec le
texte glitch (blanc brush + aberration chromatique), booth DJ et foule.
Police la plus proche dispo (Damion). Sortie : mp4."""

import os, math, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1280, 720
FPS = 30
DUR = 12
NF = FPS * DUR
OUT_DIR = "/tmp/scene_render"
OUT = "/home/user/lucie/mls-mapping/monte-le-son-scene.mp4"
os.makedirs(OUT_DIR, exist_ok=True)

F_SCRIPT = os.path.join(os.path.dirname(__file__), "fonts/Damion-Regular.ttf")
NAME = "Monte Le Son"

def font(s):
    try: return ImageFont.truetype(F_SCRIPT, s)
    except Exception: return ImageFont.load_default()

def hsl_rgb(h, s=1.0, l=0.6):
    h = h % 360/60.0; cc=(1-abs(2*l-1))*s; x=cc*(1-abs(h%2-1)); m=l-cc/2
    r,g,b=[(cc,x,0),(x,cc,0),(0,cc,x),(0,x,cc),(x,0,cc),(cc,0,x)][int(h)%6]
    return np.array([r+m,g+m,b+m], np.float32)*255

# ---- masque texte blanc brush a une taille de panneau donnee
def text_alpha(pw, ph):
    fs = 20
    while True:
        if font(fs).getbbox(NAME)[2] > pw*0.86 or fs > 300: break
        fs += 3
    f = font(fs-3)
    im = Image.new("L", (pw, ph), 0); d = ImageDraw.Draw(im)
    bb = d.textbbox((0,0), NAME, font=f)
    x = (pw-(bb[2]-bb[0]))//2 - bb[0]; y = (ph-(bb[3]-bb[1]))//2 - bb[1]
    rng = np.random.default_rng(3)
    for _ in range(6):
        yy_ = int(rng.integers(int(ph*0.35), int(ph*0.7)))
        d.line([(int(pw*0.04), yy_), (int(pw*0.96), yy_+int(rng.integers(-14,14)))],
               fill=int(rng.integers(120,220)), width=int(rng.integers(2,4)))
    d.text((x, y), NAME, font=f, fill=255, stroke_width=max(2, fs//28), stroke_fill=255)
    return np.asarray(im, np.float32)/255.0

WALL_W, WALL_H = int(W*0.5), int(H*0.26)
WALL_A = text_alpha(WALL_W, WALL_H)
BOOTH_W, BOOTH_H = int(W*0.42), int(H*0.10)
BOOTH_A = text_alpha(BOOTH_W, BOOTH_H)

rng = np.random.default_rng(11)

def glitch_text(A, t, f):
    """Texte blanc + aberration chromatique vert/rouge + eclats colores."""
    ph, pw = A.shape
    a = A.copy()
    if rng.random() < 0.6:
        for _ in range(int(rng.integers(2, 6))):
            y0 = int(rng.integers(0, max(1, ph-8))); hh = int(rng.integers(3, 12))
            a[y0:y0+hh] = np.roll(a[y0:y0+hh], int(rng.integers(-40, 40)), 1)
    burst = 1.0 if (f % 13) < 3 else 0.0
    sx = int(4 + 14*burst + rng.integers(0, 5))
    out = np.zeros((ph, pw, 3), np.float32)
    out[..., 0] += np.roll(a, -sx, 1) * 235
    out[..., 1] += np.roll(a,  sx, 1) * 235
    out += a[..., None] * 255
    # eclats colores (fragments facon mur LED)
    if rng.random() < 0.7:
        im = Image.new("RGB", (pw, ph), (0,0,0)); d = ImageDraw.Draw(im)
        for _ in range(int(rng.integers(3, 9))):
            cx = int(rng.integers(0, pw)); cy = int(rng.integers(0, ph))
            s = int(rng.integers(10, 60)); col = (0,230,80) if rng.random()<0.5 else (235,30,50)
            ang = rng.uniform(0, math.pi)
            d.polygon([(cx,cy),(cx+int(math.cos(ang)*s),cy+int(math.sin(ang)*s)),
                       (cx+int(math.cos(ang+0.6)*s*0.5),cy+int(math.sin(ang+0.6)*s*0.5))], fill=col)
        out += np.asarray(im, np.float32)*0.6
    out[::2] *= 0.85
    return out

def paste(canvas, rgb, x0, y0, glow=0.4):
    ph, pw = rgb.shape[:2]
    X0,Y0=max(0,x0),max(0,y0); X1,Y1=min(W,x0+pw),min(H,y0+ph)
    if X0>=X1 or Y0>=Y1: return
    sub = rgb[Y0-y0:Y1-y0, X0-x0:X1-x0]
    m = (sub.sum(2, keepdims=True) > 8).astype(np.float32)
    canvas[Y0:Y1, X0:X1] = canvas[Y0:Y1, X0:X1]*(1-m) + sub*m
    canvas[Y0:Y1, X0:X1] += sub*glow

# ---- decors fixes (fond noir + fumee + foule + DJ)
BG = np.zeros((H, W, 3), np.float32)
noise = rng.random((H//12, W//12)).astype(np.float32)
FOG = np.asarray(Image.fromarray((noise*255).astype(np.uint8)).resize((W,H))
                 .filter(ImageFilter.GaussianBlur(40)), np.float32)/255.0

CROWD = Image.new("RGBA", (W,H), (0,0,0,0)); cd = ImageDraw.Draw(CROWD); xp = 0
while xp < W:
    hd = int(rng.integers(34,70)); hy = H-int(rng.integers(0,50))
    cd.ellipse([xp,hy-hd,xp+hd,hy], fill=(0,0,0,255))
    cd.rectangle([xp-8,hy-hd//2,xp+hd+8,H], fill=(0,0,0,255))
    if rng.random()<0.22:
        ax=xp+hd//2
        cd.line([(ax,hy-hd),(ax+int(rng.integers(-30,30)),hy-hd-int(rng.integers(60,120)))],fill=(0,0,0,255),width=10)
    xp += int(hd*rng.uniform(0.55,0.9))
CROWD_np = np.asarray(CROWD, np.float32)

def silh(d,cx,by,sc,col=(4,4,7,255)):
    d.ellipse([cx-int(16*sc),by-int(58*sc),cx+int(16*sc),by-int(28*sc)],fill=col)
    d.polygon([(cx-int(34*sc),by),(cx+int(34*sc),by),(cx+int(22*sc),by-int(30*sc)),(cx-int(22*sc),by-int(30*sc))],fill=col)
DJ = Image.new("RGBA",(W,H),(0,0,0,0)); dd=ImageDraw.Draw(DJ)
silh(dd,int(W*0.40),int(H*0.55),1.0); silh(dd,int(W*0.52),int(H*0.54),0.95); silh(dd,int(W*0.62),int(H*0.55),1.0)
DJ_np = np.asarray(DJ, np.float32)

def wash(t):
    sw,sh=W//4,H//4; im=Image.new("RGB",(sw,sh),(0,0,0)); d=ImageDraw.Draw(im)
    for (fx,fy,ph) in [(0.2,0.15,0),(0.8,0.12,120),(0.5,0.0,240),(0.95,0.4,60)]:
        col=tuple(int(c) for c in hsl_rgb((t*55+ph)%360,1,0.5))
        cx,cy=int(fx*sw),int(fy*sh); R=int(sw*0.5); d.ellipse([cx-R,cy-R,cx+R,cy+R],fill=col)
    return np.asarray(im.filter(ImageFilter.GaussianBlur(24)).resize((W,H)),np.float32)

print(f"Rendu {NF} frames...")
for old in os.listdir(OUT_DIR):
    if old.endswith(".png"): os.remove(os.path.join(OUT_DIR, old))

for f in range(NF):
    t = f/FPS
    canvas = BG.copy()

    # lumieres de couleur + fumee
    fog = np.roll(FOG, int(t*20), axis=1)[..., None]
    canvas += wash(t) * (0.22 + 0.78*fog) * 1.1

    # mur LED de fond (texte glitch)
    paste(canvas, glitch_text(WALL_A, t, f), (W-WALL_W)//2, int(H*0.10), glow=0.5)

    # spots + faisceaux
    beams=Image.new("RGB",(W,H),(0,0,0)); bd=ImageDraw.Draw(beams)
    for i in range(7):
        bx=W*(i+0.5)/7; sway=math.sin(t*1.6+i)*60
        col=tuple(int(c) for c in hsl_rgb((t*70+i*40)%360,1,0.5))
        bd.polygon([(bx,8),(bx+sway-30,H*0.7),(bx+sway+30,H*0.7)],fill=col)
        bd.ellipse([bx-7,6,bx+7,22],fill=(255,255,255))
    canvas += np.asarray(beams.filter(ImageFilter.GaussianBlur(10)),np.float32)*0.5

    # lasers
    las=Image.new("RGB",(W,H),(0,0,0)); ld=ImageDraw.Draw(las)
    for src in [(W*0.15,20),(W*0.85,20)]:
        lc=tuple(int(c) for c in hsl_rgb((t*90)%360,1,0.55))
        for j in range(11):
            a=math.radians(40+j*9+math.sin(t*2)*10)
            ld.line([src,(src[0]+math.cos(a)*1000*(1 if src[0]<W/2 else -1),src[1]+math.sin(a)*1000)],fill=lc,width=1)
    canvas += np.asarray(las.filter(ImageFilter.GaussianBlur(1)),np.float32)*0.6

    # booth + DJ
    by=int(H*0.50); canvas[by:by+6]+=np.array([60,60,80],np.float32)
    paste(canvas, glitch_text(BOOTH_A, t, f), (W-BOOTH_W)//2, int(H*0.41), glow=0.4)  # texte facade
    a=DJ_np[...,3:4]/255.0; canvas=canvas*(1-a*0.9)+DJ_np[...,:3]*a

    # foule
    a=CROWD_np[...,3:4]/255.0; canvas=canvas*(1-a)

    if (f % 54) in (0,1): canvas += 60

    Image.fromarray(np.clip(canvas,0,255).astype(np.uint8)).save(f"{OUT_DIR}/f_{f:04d}.png")
    if f % 30 == 0: print(f"  {f}/{NF}")

print("Encodage...")
subprocess.run(["ffmpeg","-y","-framerate",str(FPS),"-i",f"{OUT_DIR}/f_%04d.png",
    "-c:v","libx264","-pix_fmt","yuv420p","-crf","20","-movflags","+faststart",OUT],check=True)
print("OK ->", OUT)
