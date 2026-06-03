#!/usr/bin/env python3
"""Ecran LED plein cadre facon 'DAMIEN RK' : texte blanc brush 'MONTE LE SON'
sur fond noir, glitch chromatique (copies decalees vert/rouge) + eclats +
decoupes. Sortie : mp4 a jouer sur l'ecran LED."""

import os, math, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1280, 720
FPS = 30
DUR = 10
NF = FPS * DUR
OUT_DIR = "/tmp/booth_render"
OUT = "/home/user/lucie/mls-mapping/monte-le-son-led.mp4"
os.makedirs(OUT_DIR, exist_ok=True)

F_SCRIPT = os.path.join(os.path.dirname(__file__), "fonts/Damion-Regular.ttf")
NAME = "Monte Le Son"

def font(s):
    try: return ImageFont.truetype(F_SCRIPT, s)
    except Exception: return ImageFont.load_default()

# ---- texte blanc brush 'Monte Le Son' (alpha plein cadre, une ligne) ----
def make_text():
    # taille de police pour remplir ~82% de la largeur
    fs = 40
    while True:
        f = font(fs)
        bb = f.getbbox(NAME)
        if bb[2]-bb[0] > W*0.82 or fs > 400: break
        fs += 4
    f = font(fs - 4)
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    bb = d.textbbox((0, 0), NAME, font=f)
    x = (W-(bb[2]-bb[0]))//2 - bb[0]
    y = (H-(bb[3]-bb[1]))//2 - bb[1]
    rng = np.random.default_rng(3)
    # longs traits qui filent (speed lines facon ref), dans le blanc
    for _ in range(8):
        yy_ = int(rng.integers(int(H*0.35), int(H*0.68)))
        d.line([(int(W*0.04), yy_+int(rng.integers(-6,6))),
                (int(W*0.96), yy_+int(rng.integers(-26,26)))],
               fill=(255,255,255,int(rng.integers(120,220))), width=int(rng.integers(2,5)))
    d.text((x, y), NAME, font=f, fill=(255,255,255,255),
           stroke_width=max(2, fs//30), stroke_fill=(255,255,255,255))
    return (np.asarray(im, np.float32)[..., 3]/255.0)        # alpha (H,W)

ALPHA = make_text()
rng = np.random.default_rng(11)

def shards(t, f):
    """Eclats angulaires vert/rouge facon glitch-art autour du texte."""
    im = Image.new("RGB", (W, H), (0, 0, 0)); d = ImageDraw.Draw(im)
    for _ in range(rng.integers(3, 8)):
        cx = int(rng.integers(int(W*0.15), int(W*0.85)))
        cy = int(rng.integers(int(H*0.3), int(H*0.7)))
        s = int(rng.integers(20, 90))
        col = (0, 230, 80) if rng.random() < 0.5 else (235, 30, 50)
        a = rng.uniform(0, math.pi)
        pts = [(cx, cy),
               (cx+int(math.cos(a)*s), cy+int(math.sin(a)*s)),
               (cx+int(math.cos(a+0.5)*s*0.5), cy+int(math.sin(a+0.5)*s*0.5))]
        d.polygon(pts, fill=col)
    return np.asarray(im, np.float32)

print(f"Rendu {NF} frames...")
for old in os.listdir(OUT_DIR):
    if old.endswith(".png"): os.remove(os.path.join(OUT_DIR, old))

for f in range(NF):
    t = f/FPS
    canvas = np.zeros((H, W, 3), np.float32)

    # eclats glitch derriere
    canvas += shards(t, f) * 0.7

    A = ALPHA.copy()
    # decoupes horizontales (glitch) sur le masque
    if rng.random() < 0.6:
        for _ in range(int(rng.integers(2, 7))):
            y0 = int(rng.integers(0, H-12)); hh = int(rng.integers(4, 16)); off = int(rng.integers(-50, 50))
            A[y0:y0+hh] = np.roll(A[y0:y0+hh], off, 1)

    # aberration chromatique : copie verte + copie rouge decalees
    burst = 1.0 if (f % 14) < 3 else 0.0
    sx = int(6 + 16*burst + rng.integers(0, 6))
    sy = int(2 + 6*burst)
    red = np.roll(np.roll(A, -sx, 1), -sy, 0)
    grn = np.roll(np.roll(A,  sx, 1),  sy, 0)
    core = A

    canvas[..., 0] += red * 235          # frange rouge
    canvas[..., 1] += grn * 235          # frange verte
    canvas += core[..., None] * 255      # coeur blanc

    # flash blanc occasionnel
    if (f % 40) in (0, 1):
        canvas += core[..., None] * 120

    # scanlines + leger glitch global
    canvas[::2] *= 0.85
    if rng.random() < 0.15:
        s = int(rng.integers(4, 14))
        canvas[..., 0] = np.roll(canvas[..., 0], s, 1)
        canvas[..., 2] = np.roll(canvas[..., 2], -s, 1)

    Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8)).save(f"{OUT_DIR}/f_{f:04d}.png")
    if f % 30 == 0: print(f"  {f}/{NF}")

print("Encodage...")
subprocess.run(["ffmpeg", "-y", "-framerate", str(FPS), "-i", f"{OUT_DIR}/f_%04d.png",
    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-movflags", "+faststart", OUT],
    check=True)
print("OK ->", OUT)
