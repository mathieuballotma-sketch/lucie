#!/usr/bin/env python3
"""Mapping PSYCHOACTIF plein cadre : mandala/kaleidoscope plasma qui ondule,
tunnel, trainees, couleurs qui pulsent + logo MLS qui bat au centre.
Rendu plasma en basse def puis upscale (fluide). Sortie : mp4 a projeter."""

import os, math, subprocess
import numpy as np
from PIL import Image, ImageFilter

W, H = 1280, 720
LW, LH = 640, 360                 # resolution du plasma (upscale ensuite)
FPS = 30
DUR = 14
NF = FPS * DUR
OUT_DIR = "/tmp/psy_render"
OUT = "/home/user/lucie/mls-mapping/mls-psychoactif.mp4"
os.makedirs(OUT_DIR, exist_ok=True)
LOGO = "/home/user/lucie/mls-mapping/mls-logo.png"

# coords polaires (low res)
yy, xx = np.mgrid[0:LH, 0:LW].astype(np.float32)
cx, cy = LW/2, LH/2
dx, dy = (xx-cx)/LW, (yy-cy)/LW
R = np.sqrt(dx*dx + dy*dy) + 1e-4
TH = np.arctan2(dy, dx)

def hsv2rgb(h, s, v):
    h = (h % 1.0)*6.0
    i = np.floor(h).astype(np.int32); f = h - i
    p = v*(1-s); q = v*(1-f*s); t = v*(1-(1-f)*s)
    i = i % 6
    r = np.choose(i, [v, q, p, p, t, v])
    g = np.choose(i, [t, v, v, q, p, p])
    b = np.choose(i, [p, p, t, v, v, q])
    return np.stack([r, g, b], -1)

# logo MLS
logo_im = Image.open(LOGO).convert("RGBA") if os.path.exists(LOGO) else None

print(f"Rendu {NF} frames...")
for old in os.listdir(OUT_DIR):
    if old.endswith(".png"): os.remove(os.path.join(OUT_DIR, old))

prev = None
NSEG = 6                            # symetrie du mandala
for f in range(NF):
    t = f/FPS
    # tunnel : on fait "avancer" dans le rayon
    rr = np.log(R) * 2.0 - t*0.9
    # kaleidoscope : repli de l'angle en NSEG segments mirroir
    fold = np.arccos(np.cos(TH*NSEG + math.sin(t*0.5)*2))

    # plasma psychoactif (somme de sinus)
    v = (np.sin(rr*3.0 + t*2.0)
         + np.sin(fold*4.0 - t*1.7)
         + np.sin((rr*2.0 + fold*3.0) + t*1.3)
         + np.sin(1.0/R*0.6 - t*2.5)
         + np.sin((dx*10)*np.cos(t*0.7) + (dy*10)*np.sin(t*0.7) + t))
    v = v/5.0

    hue = (v*0.5 + t*0.06 + R*0.3) % 1.0
    sat = np.clip(0.7 + 0.3*np.sin(v*3.14 + t), 0, 1)
    val = np.clip(0.45 + 0.55*np.sin(v*3.14159*1.5 - t*1.5)**2, 0, 1)
    rgb = hsv2rgb(hue, sat, val) * 255.0

    # trainees (feedback)
    if prev is not None:
        rgb = rgb*0.62 + prev*0.45
    prev = rgb.copy()

    # upscale + glow
    img = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8)).resize((W, H), Image.BILINEAR)
    glow = img.filter(ImageFilter.GaussianBlur(8))
    canvas = np.clip(np.asarray(img, np.float32) + np.asarray(glow, np.float32)*0.35, 0, 255)

    # logo MLS qui bat au centre
    if logo_im is not None:
        beat = 0.5 + 0.5*math.sin(t*2*math.pi*2.0)
        ls = int(H*(0.34 + 0.05*beat))
        spin = t*25
        lg = logo_im.resize((ls, ls)).rotate(spin, resample=Image.BICUBIC)
        la = np.asarray(lg, np.float32); lrgb, lal = la[..., :3], (la[..., 3:4]/255.0)*(0.7+0.3*beat)
        x0 = (W-ls)//2; y0 = (H-ls)//2
        X1, Y1 = x0+ls, y0+ls
        canvas[y0:Y1, x0:X1] = canvas[y0:Y1, x0:X1]*(1-lal) + lrgb*lal
        canvas[y0:Y1, x0:X1] += lrgb*lal*0.3

    Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8)).save(f"{OUT_DIR}/f_{f:04d}.png")
    if f % 30 == 0: print(f"  {f}/{NF}")

print("Encodage...")
subprocess.run(["ffmpeg", "-y", "-framerate", str(FPS), "-i", f"{OUT_DIR}/f_%04d.png",
    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-movflags", "+faststart", OUT],
    check=True)
print("OK ->", OUT)
