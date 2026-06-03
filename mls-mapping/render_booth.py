#!/usr/bin/env python3
"""Contenu d'ECRAN LED plein cadre (style de la reference) : fond noir,
'MONTE LE SON' en gros, graffiti glitch qui change de couleur. Sortie : mp4.
A jouer directement sur l'ecran LED / a projeter."""

import os, math, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1280, 720
FPS = 30
DUR = 12
NF = FPS * DUR
OUT_DIR = "/tmp/booth_render"
OUT = "/home/user/lucie/mls-mapping/monte-le-son-led.mp4"
os.makedirs(OUT_DIR, exist_ok=True)

F_ITAL = "/usr/share/fonts/truetype/freefont/FreeSansBoldOblique.ttf"

def font(s):
    try: return ImageFont.truetype(F_ITAL, s)
    except Exception: return ImageFont.load_default()

def hsl_rgb(h, s=1.0, l=0.6):
    h = h % 360/60.0; cc=(1-abs(2*l-1))*s; x=cc*(1-abs(h%2-1)); m=l-cc/2
    r,g,b=[(cc,x,0),(x,cc,0),(0,cc,x),(0,x,cc),(x,0,cc),(cc,0,x)][int(h)%6]
    return np.array([r+m,g+m,b+m], np.float32)*255

# ---- texte 'MONTE LE SON' (blanc, graffiti, fond transparent) -> reutilise
def make_text():
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    rng = np.random.default_rng(3)
    # coups de pinceau / slashes graffiti derriere
    for _ in range(22):
        x0 = int(rng.integers(0, W)); y0 = int(rng.integers(int(H*0.2), int(H*0.85)))
        L = int(rng.integers(W//8, W//3)); a = math.radians(rng.uniform(-22, -6))
        d.line([(x0, y0), (x0+L*math.cos(a), y0+L*math.sin(a))],
               fill=(255, 255, 255, int(rng.integers(40, 120))), width=int(rng.integers(2, 8)))
    # MONTE LE  /  SON  (empile, style nom d'artiste)
    f1 = font(int(H*0.26)); f2 = font(int(H*0.40))
    l1, l2 = "MONTE LE", "SON"
    b1 = d.textbbox((0,0), l1, font=f1); b2 = d.textbbox((0,0), l2, font=f2)
    y1 = int(H*0.13)
    x1 = (W-(b1[2]-b1[0]))//2 - b1[0]
    d.text((x1, y1), l1, font=f1, fill=(255,255,255,255),
           stroke_width=6, stroke_fill=(0,0,0,255))
    y2 = y1 + (b1[3]-b1[1]) - int(H*0.04)
    x2 = (W-(b2[2]-b2[0]))//2 - b2[0]
    d.text((x2, y2), l2, font=f2, fill=(255,255,255,255),
           stroke_width=8, stroke_fill=(0,0,0,255))
    return im

BASE_TXT = make_text()
TXT = np.asarray(BASE_TXT, np.float32)

# fond : quelques trainees colorees (visuel LED) precalculees en gabarit blanc
def make_streaks():
    im = Image.new("L", (W, H), 0); d = ImageDraw.Draw(im)
    rng = np.random.default_rng(8)
    for _ in range(16):
        x0 = int(rng.integers(-100, W)); y0 = int(rng.integers(0, H))
        L = int(rng.integers(W//3, W)); a = math.radians(rng.uniform(-18, -4))
        d.line([(x0, y0), (x0+L*math.cos(a), y0+L*math.sin(a))],
               fill=int(rng.integers(60, 160)), width=int(rng.integers(3, 10)))
    return np.asarray(im.filter(ImageFilter.GaussianBlur(2)), np.float32)/255.0
STREAKS = make_streaks()

rng = np.random.default_rng(11)
print(f"Rendu {NF} frames...")
for old in os.listdir(OUT_DIR):
    if old.endswith(".png"): os.remove(os.path.join(OUT_DIR, old))

for f in range(NF):
    t = f/FPS
    canvas = np.zeros((H, W, 3), np.float32)            # fond NOIR

    # ---- trainees colorees de fond (le visuel de l'ecran LED)
    bgcol = hsl_rgb((t*120 + 40) % 360, 1, 0.5)
    canvas += STREAKS[..., None] * bgcol[None, None, :] * 0.5

    # ---- texte qui change de couleur
    rgb = TXT[..., :3].copy(); a = TXT[..., 3:4]/255.0
    col = hsl_rgb((t*150) % 360, 1.0, 0.62)
    rgb = rgb * (col[None, None, :]/255.0)
    # flashs durs (vert / rouge / cyan / blanc) facon LED
    if (f % 16) < 3:
        hard = [(60,255,110),(255,50,70),(60,210,255),(255,255,255)][int(t*4) % 4]
        rgb = rgb*0.2 + (a > 0.05)*np.array(hard, np.float32)[None, None, :]*0.95
    rgb = np.clip(rgb*1.15, 0, 255)
    # RGB split
    if rng.random() < 0.5:
        s = int(rng.integers(4, 16))
        rgb[..., 0] = np.roll(rgb[..., 0], s, 1); rgb[..., 2] = np.roll(rgb[..., 2], -s, 1)
    # decoupes horizontales (glitch)
    if rng.random() < 0.55:
        for _ in range(int(rng.integers(3, 8))):
            y0 = int(rng.integers(0, H-12)); hh = int(rng.integers(4, 16)); off = int(rng.integers(-40, 40))
            rgb[y0:y0+hh] = np.roll(rgb[y0:y0+hh], off, 1); a[y0:y0+hh] = np.roll(a[y0:y0+hh], off, 1)
    rgb[::2] *= 0.82                                    # scanlines

    # composite + halo
    canvas = canvas*(1-a) + rgb*a
    canvas += rgb*a*0.3

    # ---- glitch global occasionnel
    if rng.random() < 0.12:
        s = int(rng.integers(4, 12))
        canvas[..., 0] = np.roll(canvas[..., 0], s, 1); canvas[..., 2] = np.roll(canvas[..., 2], -s, 1)

    Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8)).save(f"{OUT_DIR}/f_{f:04d}.png")
    if f % 30 == 0: print(f"  {f}/{NF}")

print("Encodage...")
subprocess.run(["ffmpeg", "-y", "-framerate", str(FPS), "-i", f"{OUT_DIR}/f_%04d.png",
    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-movflags", "+faststart", OUT],
    check=True)
print("OK ->", OUT)
