#!/usr/bin/env python3
"""Video facon stand DJ / scene LED (style de la video de reference) avec le
nom 'MONTE LE SON' en glitch graffiti : ecran de fond + facade de booth,
spots/strobes, silhouettes de DJ, haze. Sortie : un mp4."""

import os, math, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1280, 720
FPS = 30
DUR = 12
NF = FPS * DUR
OUT_DIR = "/tmp/booth_render"
OUT = "/home/user/lucie/mls-mapping/monte-le-son-stage.mp4"
os.makedirs(OUT_DIR, exist_ok=True)

F_ITAL = "/usr/share/fonts/truetype/freefont/FreeSansBoldOblique.ttf"
F_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
NAME = "MONTE LE SON"

def font(p, s):
    try: return ImageFont.truetype(p, s)
    except Exception: return ImageFont.load_default()

# ---------------------------------------------------------------- texte glitch
def text_panel(text, pw, ph, fs, rng, stacked=False):
    """Texte blanc style graffiti (slashes) sur fond transparent -> RGBA."""
    im = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    # coups de pinceau / slashes derriere
    for _ in range(rng.integers(6, 12)):
        x0 = rng.integers(0, pw); y0 = rng.integers(int(ph*0.2), int(ph*0.9))
        L = rng.integers(pw//6, pw//2); a = math.radians(rng.uniform(-25, -8))
        x1 = x0 + L*math.cos(a); y1 = y0 + L*math.sin(a)
        w = int(rng.integers(2, 7))
        d.line([(x0, y0), (x1, y1)], fill=(255, 255, 255, rng.integers(60, 160)), width=w)
    # le texte
    if stacked:
        lines = ["MONTE LE", "SON"]
    else:
        lines = [text]
    fnt = font(F_ITAL, fs)
    total_h = sum(font(F_ITAL, fs).getbbox(l)[3] for l in lines) + (len(lines)-1)*int(fs*0.1)
    y = (ph - total_h)//2
    for li, line in enumerate(lines):
        f2 = font(F_ITAL, fs if li == 0 or not stacked else int(fs*1.25))
        bb = d.textbbox((0, 0), line, font=f2)
        x = (pw - (bb[2]-bb[0]))//2 - bb[0]
        # ombre/contour
        d.text((x, y), line, font=f2, fill=(0, 0, 0, 255), stroke_width=max(2, fs//22),
               stroke_fill=(0, 0, 0, 255))
        d.text((x, y), line, font=f2, fill=(255, 255, 255, 255))
        y += (bb[3]-bb[1]) + int(fs*0.12)
    return im

def glitch_np(rgba, t, f, rng, tint_cycle):
    """Applique RGB-split, decoupes, tint colore, scanlines."""
    arr = np.asarray(rgba, np.float32)
    rgb, a = arr[..., :3].copy(), arr[..., 3:4]/255.0
    h_ = rgb.shape[0]
    # tint colore periodique (vert / rouge / cyan facon LED)
    if (f % 20) < 4:
        col = [(40, 255, 90), (255, 40, 60), (40, 200, 255)][int(t*3) % 3]
        rgb = rgb*0.25 + np.array(col, np.float32)[None, None, :]*0.9
    # RGB split
    if rng.random() < 0.5:
        s = int(rng.integers(3, 12))
        rgb[..., 0] = np.roll(rgb[..., 0], s, 1)
        rgb[..., 2] = np.roll(rgb[..., 2], -s, 1)
    # decoupes horizontales
    if rng.random() < 0.55:
        for _ in range(int(rng.integers(2, 7))):
            y0 = int(rng.integers(0, max(1, h_-10))); hh = int(rng.integers(3, 12))
            off = int(rng.integers(-30, 30))
            rgb[y0:y0+hh] = np.roll(rgb[y0:y0+hh], off, 1)
            a[y0:y0+hh] = np.roll(a[y0:y0+hh], off, 1)
    rgb[::2] *= 0.85  # scanlines
    return rgb, a

def paste_glow(canvas, rgb, a, x0, y0):
    h_, w_ = rgb.shape[:2]
    X0, Y0 = max(0, x0), max(0, y0)
    X1, Y1 = min(W, x0+w_), min(H, y0+h_)
    if X0 >= X1 or Y0 >= Y1: return
    sx, sy = X0-x0, Y0-y0
    sub_rgb = rgb[sy:sy+(Y1-Y0), sx:sx+(X1-X0)]
    sub_a = a[sy:sy+(Y1-Y0), sx:sx+(X1-X0)]
    canvas[Y0:Y1, X0:X1] = canvas[Y0:Y1, X0:X1]*(1-sub_a) + sub_rgb*sub_a
    # leger halo additif
    canvas[Y0:Y1, X0:X1] += sub_rgb*sub_a*0.25

# ---------------------------------------------------------------- decors fixes
yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
# fond : sombre, un peu plus clair en haut (lumieres + haze)
BG = np.zeros((H, W, 3), np.float32)
grad = np.clip(1 - yy/H, 0, 1)
BG[..., 0] = 14 + 26*grad
BG[..., 1] = 16 + 28*grad
BG[..., 2] = 24 + 40*grad

def silhouette(draw, cx, base_y, scale, col=(6, 6, 10)):
    hw = int(40*scale)
    draw.ellipse([cx-int(18*scale), base_y-int(150*scale),
                  cx+int(18*scale), base_y-int(110*scale)], fill=col)      # tete
    draw.polygon([(cx-hw, base_y), (cx+hw, base_y),
                  (cx+int(26*scale), base_y-int(110*scale)),
                  (cx-int(26*scale), base_y-int(110*scale))], fill=col)    # buste

# pre-rendu silhouettes (statique)
SIL = Image.new("RGBA", (W, H), (0, 0, 0, 0))
sd = ImageDraw.Draw(SIL)
silhouette(sd, int(W*0.42), int(H*0.66), 1.0)
silhouette(sd, int(W*0.62), int(H*0.64), 0.95)
SIL_np = np.asarray(SIL, np.float32)

rng = np.random.default_rng(11)

print(f"Rendu {NF} frames...")
for old in os.listdir(OUT_DIR):
    if old.endswith(".png"): os.remove(os.path.join(OUT_DIR, old))

for f in range(NF):
    t = f/FPS
    canvas = BG.copy()

    # ---- spots / lampes en haut + faisceaux
    beams = Image.new("RGB", (W, H), (0, 0, 0))
    bd = ImageDraw.Draw(beams)
    for i in range(6):
        bx = W*(i+0.5)/6
        sway = math.sin(t*1.4+i)*70
        bd.polygon([(bx, -10), (bx+sway-55, H*0.8), (bx+sway+55, H*0.8)],
                   fill=(120, 120, 140))
        bd.ellipse([bx-16, 4, bx+16, 34], fill=(230, 230, 255))  # lampe
    beams = beams.filter(ImageFilter.GaussianBlur(22))
    strobe = 1.0 if (f % 24) < 2 else 0.0
    canvas += np.asarray(beams, np.float32)*(0.5 + 0.7*strobe)

    # ---- silhouettes DJ
    a = SIL_np[..., 3:4]/255.0
    canvas = canvas*(1-a) + SIL_np[..., :3]*a

    # ---- ECRAN DE FOND (LED wall) : grand texte glitch
    bw, bh = int(W*0.62), int(H*0.34)
    panel = text_panel(NAME, bw, bh, int(bh*0.42), rng, stacked=True)
    rgb, pa = glitch_np(panel, t, f, rng, True)
    paste_glow(canvas, rgb, pa, (W-bw)//2, int(H*0.06))

    # ---- FACADE DE BOOTH (bas) : bandeau + grand texte glitch
    fw, fh = int(W*0.96), int(H*0.26)
    fx, fy = (W-fw)//2, int(H*0.66)
    # caisson du booth
    cv = canvas[fy:fy+fh, fx:fx+fw]
    cv[:] = cv*0.2 + np.array([18, 18, 26], np.float32)
    canvas[fy:fy+fh, fx:fx+fw] = cv
    canvas[fy:fy+3, fx:fx+fw] += 60   # arete lumineuse haute
    panel2 = text_panel(NAME, fw, fh, int(fh*0.5), rng, stacked=False)
    rgb2, pa2 = glitch_np(panel2, t, f, rng, True)
    paste_glow(canvas, rgb2, pa2, fx, fy)

    # ---- flash blanc occasionnel (club)
    if (f % 48) in (0, 1):
        canvas += 80

    # ---- grain / glitch global
    if rng.random() < 0.12:
        s = int(rng.integers(3, 9))
        canvas[..., 0] = np.roll(canvas[..., 0], s, 1)
        canvas[..., 2] = np.roll(canvas[..., 2], -s, 1)

    Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8)).save(f"{OUT_DIR}/f_{f:04d}.png")
    if f % 30 == 0: print(f"  {f}/{NF}")

print("Encodage...")
subprocess.run(["ffmpeg", "-y", "-framerate", str(FPS), "-i", f"{OUT_DIR}/f_%04d.png",
    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "19", "-movflags", "+faststart", OUT],
    check=True)
print("OK ->", OUT)
