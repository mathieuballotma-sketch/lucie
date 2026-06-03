#!/usr/bin/env python3
"""Video 'mapping MLS' psychotrope : logo complet (cone d'enceinte + textes
courbes) qui clignote/glitch/change de couleur, kaleidoscope, trainees
(feedback), miroirs, zoom-rotation et points psychedeliques. Sortie : un mp4."""

import os, math, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1280, 720
FPS = 30
DUR = 10                      # secondes (plus rapide / plus court)
NF = FPS * DUR
OUT_DIR = "/tmp/mls_render"
os.makedirs(OUT_DIR, exist_ok=True)

LOGO_PNG = "/home/user/lucie/mls-mapping/mls-logo.png"
F_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
F_ITAL = "/usr/share/fonts/truetype/freefont/FreeSansBoldOblique.ttf"

def font(path, sz):
    try: return ImageFont.truetype(path, sz)
    except Exception: return ImageFont.load_default()

# ---------------------------------------------------------------- logo complet
def arc_text(base, text, cx, cy, radius, center_deg, arc_deg, fnt, fill, up=True):
    n = max(1, len(text))
    box = int(fnt.size * 2.4)
    for i, ch in enumerate(text):
        frac = (i + 0.5) / n - 0.5
        a_deg = center_deg + frac * arc_deg * (1 if up else -1)
        a = math.radians(a_deg)
        x = cx + radius * math.cos(a)
        y = cy + radius * math.sin(a)
        ci = Image.new("RGBA", (box, box), (0, 0, 0, 0))
        cd = ImageDraw.Draw(ci)
        bb = cd.textbbox((0, 0), ch, font=fnt)
        w_, h_ = bb[2]-bb[0], bb[3]-bb[1]
        cd.text(((box-w_)/2-bb[0], (box-h_)/2-bb[1]), ch, font=fnt, fill=fill)
        rot = -(a_deg + 90) if up else -(a_deg - 90)
        ci = ci.rotate(rot, resample=Image.BICUBIC, expand=False)
        base.alpha_composite(ci, (int(x-box/2), int(y-box/2)))

def make_logo(size=620):
    S = size
    cx = cy = S/2
    yy, xx = np.mgrid[0:S, 0:S].astype(np.float32)
    r = np.sqrt((xx-cx)**2 + (yy-cy)**2)
    ang = np.arctan2(yy-cy, xx-cx)
    R = S/2 - 2

    # rim arc-en-ciel metallique (toute la roue de teintes)
    hue = (ang + math.pi) / (2*math.pi) * 360
    def h2rgb(hh):
        hh = (hh % 360)/60.0
        c = 1.0; x = 1 - abs(hh % 2 - 1)
        z = np.zeros_like(hh)
        r_ = np.select([hh<1,hh<2,hh<3,hh<4,hh<5,hh<6],[c,x,z,z,x,c])
        g_ = np.select([hh<1,hh<2,hh<3,hh<4,hh<5,hh<6],[x,c,c,x,z,z])
        b_ = np.select([hh<1,hh<2,hh<3,hh<4,hh<5,hh<6],[z,z,x,c,c,x])
        return np.stack([r_,g_,b_], -1)
    rimcol = h2rgb(hue) * 255

    cone = np.zeros((S, S, 3), np.float32)
    rad = np.clip(r/R, 0, 1)
    cone[..., 0] = 70*(1-rad)+18
    cone[..., 1] = 25*(1-rad)+8
    cone[..., 2] = 130*(1-rad)+34
    cone += (np.sin(rad*42)*0.5+0.5)[..., None]*16   # anneaux du cone

    arr = np.zeros((S, S, 4), np.float32)
    m_disc = r <= R
    m_rim = (r <= R) & (r > R*0.86)
    m_cone = (r <= R*0.86) & (r > R*0.34)
    m_ctr = r <= R*0.34
    arr[m_rim, :3] = rimcol[m_rim]*0.9 + 30
    arr[m_cone, :3] = cone[m_cone]
    arr[m_ctr, :3] = (6, 3, 16)
    arr[m_disc, 3] = 255

    out = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGBA")
    # textes courbes
    arc_text(out, "MONTE LE SON", cx, cy, R*0.93, -90, 150,
             font(F_BOLD, int(S*0.058)), (255,255,255,255), up=True)
    arc_text(out, "SONORISATION · ÉCLAIRAGE · ÉVÈNEMENTIEL", cx, cy, R*0.93,
             90, 200, font(F_BOLD, int(S*0.036)), (240,240,240,255), up=False)
    # MLS au centre
    d = ImageDraw.Draw(out)
    fmls = font(F_ITAL, int(S*0.19))
    bb = d.textbbox((0,0), "MLS", font=fmls)
    d.text(((S-(bb[2]-bb[0]))/2, cy-(bb[3]-bb[1])/2-bb[1]), "MLS",
           font=fmls, fill=(255,255,255,255))
    return out

if os.path.exists(LOGO_PNG):
    base_logo = Image.open(LOGO_PNG).convert("RGBA"); print("Logo: vrai PNG")
else:
    base_logo = make_logo(640); print("Logo: provisoire complet genere")

# ---------------------------------------------------------------- helpers
def hue_matrix(h):
    c, s = math.cos(h), math.sin(h)
    return np.array([
        [0.213+c*0.787-s*0.213, 0.715-c*0.715-s*0.715, 0.072-c*0.072+s*0.928],
        [0.213-c*0.213+s*0.143, 0.715+c*0.285+s*0.140, 0.072-c*0.072-s*0.283],
        [0.213-c*0.213-s*0.787, 0.715-c*0.715+s*0.715, 0.072+c*0.928+s*0.072],
    ], np.float32)

def apply_hue(rgb, h):
    return (rgb.reshape(-1,3) @ hue_matrix(h).T).reshape(rgb.shape)

GS = 41
gy, gx = np.mgrid[0:GS, 0:GS].astype(np.float32)
GLOW = np.clip(1 - np.sqrt((gx-GS//2)**2+(gy-GS//2)**2)/(GS/2), 0, 1)**2

def add_sprite(canvas, spr, x, y):
    h, w = spr.shape[:2]
    x0, y0 = int(x-w//2), int(y-h//2); x1, y1 = x0+w, y0+h
    cx0, cy0 = max(0,x0), max(0,y0); cx1, cy1 = min(W,x1), min(H,y1)
    if cx0>=cx1 or cy0>=cy1: return
    canvas[cy0:cy1, cx0:cx1] += spr[cy0-y0:cy0-y0+(cy1-cy0), cx0-x0:cx0-x0+(cx1-cx0)]

def hsl_rgb(h, s=1.0, l=0.6):
    h = h % 360/60.0; cc=(1-abs(2*l-1))*s; x=cc*(1-abs(h%2-1)); m=l-cc/2
    r,g,b=[(cc,x,0),(x,cc,0),(0,cc,x),(0,x,cc),(x,0,cc),(cc,0,x)][int(h)%6]
    return np.array([r+m,g+m,b+m], np.float32)*255

yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
vig = np.clip(1-np.sqrt((xx-W/2)**2+(yy-H/2)**2)/(W*0.62), 0, 1)
BG = np.zeros((H, W, 3), np.float32); BG[...,2]=16*vig; BG[...,0]=9*vig

# ---------------------------------------------------------------- particules
rng = np.random.default_rng(7)
NP_ = 320
P = dict(
    ang=rng.uniform(0,2*math.pi,NP_), rad=rng.uniform(90,600,NP_),
    spin=rng.uniform(0.4,1.6,NP_)*np.where(rng.random(NP_)<0.5,-1,1),
    size=rng.uniform(0.5,2.6,NP_), hue=rng.uniform(0,360,NP_),
    huesp=rng.uniform(1,5,NP_), tw=rng.uniform(0,2*math.pi,NP_),
    twsp=rng.uniform(0.05,0.18,NP_))
CXP, CYP = W/2, H*0.46

# ---------------------------------------------------------------- marquee
def make_marquee():
    txt = "  MONTE LE SON   ·   SONORISATION   ·   ÉCLAIRAGE   ·   ÉVÈNEMENTIEL   ·"
    f = font(F_ITAL, 60); bb = f.getbbox(txt)
    s = Image.new("RGBA", (bb[2]-bb[0]+40, bb[3]-bb[1]+40), (0,0,0,0))
    ImageDraw.Draw(s).text((20-bb[0],20-bb[1]), txt, font=f, fill=(255,255,255,255))
    return s
MARQ = make_marquee(); MW = MARQ.width

# ---------------------------------------------------------------- feedback
def feedback(prev, t):
    img = Image.fromarray(np.clip(prev,0,255).astype(np.uint8))
    z = 1.06; nw,nh = int(W*z), int(H*z)
    img = img.resize((nw,nh), Image.BILINEAR)
    x0=(nw-W)//2; y0=(nh-H)//2
    img = img.crop((x0,y0,x0+W,y0+H)).rotate(math.sin(t*1.6)*4,
            resample=Image.BILINEAR, center=(W/2,H/2))
    return apply_hue(np.asarray(img,np.float32), 0.20) * 0.66

# ---------------------------------------------------------------- rendu
def render():
  for old in os.listdir(OUT_DIR):
    if old.endswith(".png"): os.remove(os.path.join(OUT_DIR, old))
  print(f"Rendu {NF} frames...")
  prev = None
  for f in range(NF):
    t = f/FPS
    beat = (0.5+0.5*math.sin(t*2*math.pi*3.2))**3        # tempo rapide
    canvas = BG.copy()

    # faisceaux/strobes
    flash = 1.0 if (f % 6) < 2 else 0.0
    beams = Image.new("RGB", (W,H), (0,0,0)); bd = ImageDraw.Draw(beams)
    for i in range(8):
        bx = W*(i+0.5)/8; sway = math.sin(t*2.0+i)*150
        col = tuple(int(c) for c in hsl_rgb((t*120+i*45)%360,1,0.5))
        bd.polygon([(bx,-20),(bx+sway-60,H),(bx+sway+60,H)], fill=col)
    beams = beams.filter(ImageFilter.GaussianBlur(26))
    canvas += np.asarray(beams,np.float32)*(0.10+0.55*flash+0.30*beat)

    # points psychedeliques
    P["ang"] += P["spin"]*0.05*(1+beat*1.6)
    P["hue"] += P["huesp"]; P["tw"] += P["twsp"]
    rr = P["rad"]*(1+0.14*np.sin(P["tw"]))*(1+beat*0.25)
    px = CXP+np.cos(P["ang"])*rr; py = CYP+np.sin(P["ang"])*rr*0.8
    inten = (0.4+0.6*np.sin(P["tw"]))*(0.6+beat)
    for i in range(NP_):
        col = hsl_rgb(P["hue"][i],1,0.62)*inten[i]*1.2
        spr = GLOW[...,None]*col[None,None,:]
        s = max(0.4, P["size"][i]*(0.7+0.6*math.sin(P["tw"][i])))
        if abs(s-1)>0.05:
            ns = max(8, int(GS*s))
            spr = np.asarray(Image.fromarray(np.clip(spr,0,255).astype(np.uint8))
                             .resize((ns,ns)), np.float32)
        add_sprite(canvas, spr, px[i], py[i])

    # trainees (feedback)
    if prev is not None:
        canvas += feedback(prev, t)

    # kaleidoscope : symetrie 4 axes (effet trip)
    canvas = np.maximum(canvas, canvas[:, ::-1])
    canvas = np.maximum(canvas, canvas[::-1, :])

    # ---- logo complet : glitch + couleur + clignotement + zoom/pulse
    scale = 0.78+0.10*beat
    lw = int(W*0.40*scale); logo = base_logo.resize((lw,lw))
    la = np.asarray(logo,np.float32); rgb, alpha = la[...,:3], la[...,3:4]/255.0
    rgb = apply_hue(rgb, t*2.4+0.5)
    if (f % 16) < 3:
        tint = hsl_rgb((t*260)%360,1,0.7); rgb = rgb*0.35+tint[None,None,:]*0.95
    rgb = np.clip(rgb*(1.3+0.6*beat), 0, 255)
    if rng.random() < 0.35:
        sh = rng.integers(5,18)
        rgb[...,0]=np.roll(rgb[...,0],sh,1); rgb[...,2]=np.roll(rgb[...,2],-sh,1)
    if rng.random() < 0.4:
        for _ in range(rng.integers(3,8)):
            y0=rng.integers(0,lw-12); hh=rng.integers(4,16); off=rng.integers(-26,26)
            rgb[y0:y0+hh]=np.roll(rgb[y0:y0+hh],off,1)
    blink = 0.12 if (f % 18) in (6,8) else 1.0
    add_sprite(canvas, rgb*alpha*blink*0.9, W/2, H*0.42)     # halo
    lx=int(W/2-lw/2); ly=int(H*0.42-lw/2)
    x0,y0=max(0,lx),max(0,ly); x1,y1=min(W,lx+lw),min(H,ly+lw)
    a = alpha[y0-ly:y1-ly, x0-lx:x1-lx]*blink
    canvas[y0:y1,x0:x1] = canvas[y0:y1,x0:x1]*(1-a)+rgb[y0-ly:y1-ly,x0-lx:x1-lx]*a

    # bandeau texte defilant
    bh = MARQ.height; off = int((t*320)%MW)
    strip = Image.new("RGBA",(W,bh),(0,0,0,0)); x=-off
    while x<W: strip.paste(MARQ,(x,0),MARQ); x+=MW
    sa = np.asarray(strip.convert("RGB"),np.float32)
    by=int(H*0.85); yb1=min(H,by+bh)
    canvas[by:yb1] += apply_hue(sa,t*3.0)[:yb1-by]

    # glitch global + scanlines
    if rng.random()<0.14:
        s=rng.integers(4,12)
        canvas[...,0]=np.roll(canvas[...,0],s,1); canvas[...,2]=np.roll(canvas[...,2],-s,1)
    canvas[::3]*=0.93

    prev = canvas.copy()
    Image.fromarray(np.clip(canvas,0,255).astype(np.uint8)).save(f"{OUT_DIR}/f_{f:04d}.png")
    if f % 30 == 0: print(f"  {f}/{NF}")

  print("Encodage...")
  OUT="/home/user/lucie/mls-mapping/mls-mapping.mp4"
  subprocess.run(["ffmpeg","-y","-framerate",str(FPS),"-i",f"{OUT_DIR}/f_%04d.png",
      "-c:v","libx264","-pix_fmt","yuv420p","-crf","19","-movflags","+faststart",OUT],
      check=True)
  print("OK ->", OUT)

if __name__ == "__main__":
    render()
