#!/usr/bin/env python3
"""Genere une video 'mapping MLS' facon ecran LED de scene/DJ booth :
logo qui clignote, change de couleur (glitch), strobes, lasers et points
psychedeliques tout autour. Sortie : un seul fichier mp4 (loopable)."""

import os, math, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1280, 720
FPS = 30
DUR = 12                      # secondes
NF = FPS * DUR
OUT_DIR = "/tmp/mls_render"
os.makedirs(OUT_DIR, exist_ok=True)

LOGO_PNG = "/home/user/lucie/mls-mapping/mls-logo.png"  # utilise le vrai logo s'il existe

F_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
F_ITAL = "/usr/share/fonts/truetype/freefont/FreeSansBoldOblique.ttf"

# ---------------------------------------------------------------- logo MLS
def make_logo(size=520):
    """Recree le logo enceinte MLS (utilise comme provisoire)."""
    S = size
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    cx = cy = S / 2
    yy, xx = np.mgrid[0:S, 0:S].astype(np.float32)
    r = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    ang = np.arctan2(yy - cy, xx - cx)
    R = S / 2 - 2

    # rim metallique multicolore (violet/bleu/magenta) selon l'angle
    t = (np.sin(ang * 1.0) * 0.5 + 0.5)
    rim = np.zeros((S, S, 3), np.float32)
    rim[..., 0] = 120 + 135 * t                 # R
    rim[..., 1] = 30 + 80 * (1 - t)             # G
    rim[..., 2] = 180 + 70 * np.sin(ang * 2)    # B
    # cone interieur degrade radial sombre
    cone = np.zeros((S, S, 3), np.float32)
    rad = np.clip(r / R, 0, 1)
    cone[..., 0] = 60 * (1 - rad) + 20
    cone[..., 1] = 20 * (1 - rad) + 8
    cone[..., 2] = 110 * (1 - rad) + 30

    arr = np.zeros((S, S, 4), np.float32)
    mask_disc = r <= R
    mask_rim = (r <= R) & (r > R * 0.84)
    mask_cone = (r <= R * 0.84) & (r > R * 0.40)
    mask_center = r <= R * 0.40

    arr[mask_rim, :3] = rim[mask_rim]
    arr[mask_cone, :3] = cone[mask_cone]
    arr[mask_center, :3] = (6, 3, 16)
    arr[mask_disc, 3] = 255
    # anneaux concentriques (texture cone)
    rings = (np.sin(rad * 38) * 0.5 + 0.5) * 18
    arr[mask_cone, :3] += rings[mask_cone, None]

    out = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGBA")
    d = ImageDraw.Draw(out)

    def font(path, sz):
        try: return ImageFont.truetype(path, sz)
        except Exception: return ImageFont.load_default()

    def ctext(y, txt, fnt, fill):
        bb = d.textbbox((0, 0), txt, font=fnt)
        d.text(((S - (bb[2]-bb[0])) / 2, y), txt, font=fnt, fill=fill)

    ctext(S*0.10, "MONTE LE SON", font(F_BOLD, int(S*0.062)), (255,255,255,255))
    # MLS au centre
    fmls = font(F_ITAL, int(S*0.20))
    bb = d.textbbox((0,0), "MLS", font=fmls)
    d.text(((S-(bb[2]-bb[0]))/2, cy-(bb[3]-bb[1])/2-bb[1]), "MLS",
           font=fmls, fill=(255,255,255,255))
    ctext(S*0.83, "SONO · ÉCLAIRAGE · ÉVÈNEMENTIEL",
          font(F_BOLD, int(S*0.040)), (235,235,235,255))
    return out

if os.path.exists(LOGO_PNG):
    base_logo = Image.open(LOGO_PNG).convert("RGBA")
    print("Logo: utilisation de", LOGO_PNG)
else:
    base_logo = make_logo(560)
    print("Logo: provisoire genere (pas de mls-logo.png)")

# ---------------------------------------------------------------- helpers
def hue_matrix(h):
    c, s = math.cos(h), math.sin(h)
    return np.array([
        [0.213+c*0.787-s*0.213, 0.715-c*0.715-s*0.715, 0.072-c*0.072+s*0.928],
        [0.213-c*0.213+s*0.143, 0.715+c*0.285+s*0.140, 0.072-c*0.072-s*0.283],
        [0.213-c*0.213-s*0.787, 0.715-c*0.715+s*0.715, 0.072+c*0.928+s*0.072],
    ], np.float32)

def apply_hue(rgb, h):
    m = hue_matrix(h)
    flat = rgb.reshape(-1, 3) @ m.T
    return flat.reshape(rgb.shape)

# glow sprite (gaussien) pour les points
GS = 41
gy, gx = np.mgrid[0:GS, 0:GS].astype(np.float32)
gd = np.sqrt((gx-GS//2)**2 + (gy-GS//2)**2)
GLOW = np.clip(1 - gd/(GS/2), 0, 1) ** 2

def add_sprite(canvas, sprite_rgb, x, y):
    """Ajoute (additif) un petit sprite RGB centre en (x,y)."""
    h, w = sprite_rgb.shape[:2]
    x0, y0 = int(x-w//2), int(y-h//2)
    x1, y1 = x0+w, y0+h
    cx0, cy0 = max(0, x0), max(0, y0)
    cx1, cy1 = min(W, x1), min(H, y1)
    if cx0 >= cx1 or cy0 >= cy1: return
    sx0, sy0 = cx0-x0, cy0-y0
    canvas[cy0:cy1, cx0:cx1] += sprite_rgb[sy0:sy0+(cy1-cy0), sx0:sx0+(cx1-cx0)]

def hsl_rgb(h, s=1.0, l=0.6):
    h = h % 360 / 60.0
    cc = (1 - abs(2*l-1)) * s
    x = cc * (1 - abs(h % 2 - 1)); m = l - cc/2
    r,g,b = [(cc,x,0),(x,cc,0),(0,cc,x),(0,x,cc),(x,0,cc),(cc,0,x)][int(h)%6]
    return np.array([(r+m),(g+m),(b+m)], np.float32)*255

# vignette de fond precalculee
yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
vig = np.clip(1 - np.sqrt((xx-W/2)**2+(yy-H/2)**2)/(W*0.62), 0, 1)
BG = np.zeros((H, W, 3), np.float32)
BG[..., 2] = 18 * vig
BG[..., 0] = 10 * vig

# ---------------------------------------------------------------- particules
rng = np.random.default_rng(7)
NP_ = 230
P = dict(
    ang=rng.uniform(0, 2*math.pi, NP_),
    rad=rng.uniform(120, 560, NP_),
    spin=rng.uniform(0.2, 0.9, NP_)*np.where(rng.random(NP_)<0.5,-1,1),
    size=rng.uniform(0.5, 2.4, NP_),
    hue=rng.uniform(0, 360, NP_),
    huesp=rng.uniform(0.5, 3, NP_),
    tw=rng.uniform(0, 2*math.pi, NP_),
    twsp=rng.uniform(0.02, 0.1, NP_),
)
CXP, CYP = W/2, H*0.46

# ---------------------------------------------------------------- texte booth
def make_marquee():
    txt = "  MONTE LE SON   ·   SONORISATION   ·   ÉCLAIRAGE   ·   ÉVÈNEMENTIEL   ·"
    f = ImageFont.truetype(F_ITAL, 64)
    bb = f.getbbox(txt)
    tw, th = bb[2]-bb[0], bb[3]-bb[1]
    strip = Image.new("RGBA", (tw+40, th+40), (0,0,0,0))
    ImageDraw.Draw(strip).text((20-bb[0], 20-bb[1]), txt, font=f, fill=(255,255,255,255))
    return strip
MARQ = make_marquee()
MW = MARQ.width

# ---------------------------------------------------------------- rendu frames
print(f"Rendu de {NF} frames...")
for f in range(NF):
    t = f / FPS
    beat = 0.5 + 0.5*math.sin(t*2*math.pi*2.0)          # pseudo-tempo
    beat = beat**3
    canvas = BG.copy()

    # ---- strobes / faisceaux depuis le haut
    if (f % 8) < 2:
        flash = 1.0
    else:
        flash = 0.0
    beams = Image.new("RGB", (W, H), (0,0,0))
    bd = ImageDraw.Draw(beams)
    for i in range(7):
        bx = W*(i+0.5)/7
        sway = math.sin(t*1.2 + i)*120
        col = tuple(int(c) for c in hsl_rgb((t*60 + i*50) % 360, 1, 0.5))
        bd.polygon([(bx, -20), (bx+sway-70, H), (bx+sway+70, H)], fill=col)
    beams = beams.filter(ImageFilter.GaussianBlur(28))
    canvas += np.asarray(beams, np.float32) * (0.10 + 0.5*flash + 0.25*beat)

    # ---- points psychedeliques
    P["ang"] += P["spin"]*(0.03)*(1+beat*1.2)
    P["hue"] += P["huesp"]
    P["tw"]  += P["twsp"]
    rr = P["rad"] * (1 + 0.10*np.sin(P["tw"])) * (1 + beat*0.18)
    px = CXP + np.cos(P["ang"])*rr
    py = CYP + np.sin(P["ang"])*rr*0.78
    inten = (0.4 + 0.6*np.sin(P["tw"])) * (0.6 + beat)
    for i in range(NP_):
        col = hsl_rgb(P["hue"][i], 1, 0.62) * inten[i] * 1.1
        spr = GLOW[..., None] * col[None, None, :]
        s = max(0.4, P["size"][i]*(0.7+0.6*math.sin(P["tw"][i])))
        if abs(s-1) > 0.05:
            ns = max(8, int(GS*s))
            spr = np.asarray(Image.fromarray(
                np.clip(spr,0,255).astype(np.uint8)).resize((ns,ns)), np.float32)
        add_sprite(canvas, spr, px[i], py[i])

    # ---- logo central (glitch + couleur + clignotement)
    scale = 0.80 + 0.06*beat
    lw = int(W*0.42*scale)
    logo = base_logo.resize((lw, lw))
    la = np.asarray(logo, np.float32)
    rgb, alpha = la[..., :3], la[..., 3:4]/255.0
    rgb = apply_hue(rgb, t*1.4 + 0.5)                    # cycle couleur
    # flash colore facon LED
    if (f % 24) < 3:
        tint = hsl_rgb((t*200) % 360, 1, 0.7)
        rgb = rgb*0.4 + tint[None,None,:]*0.9
    rgb = np.clip(rgb*(1.25+0.5*beat), 0, 255)
    # RGB split (glitch) sur certains frames
    if rng.random() < 0.22:
        sh = rng.integers(4, 14)
        rgb[..., 0] = np.roll(rgb[..., 0], sh, axis=1)
        rgb[..., 2] = np.roll(rgb[..., 2], -sh, axis=1)
    # decoupes horizontales glitch
    if rng.random() < 0.30:
        for _ in range(rng.integers(2, 6)):
            y0 = rng.integers(0, lw-12); hh = rng.integers(4, 14)
            off = rng.integers(-20, 20)
            rgb[y0:y0+hh] = np.roll(rgb[y0:y0+hh], off, axis=1)
    # clignotement
    blink = 1.0
    if (f % 30) in (10, 12): blink = 0.15
    layer = np.zeros((lw, lw, 3), np.float32)
    layer = rgb * alpha * blink
    lx = int(W/2 - lw/2); ly = int(H*0.40 - lw/2)
    add_sprite(canvas, layer*0.9, W/2, H*0.40)          # halo glow
    # pose nette par-dessus (composite alpha)
    x0,y0 = max(0,lx),max(0,ly); x1,y1 = min(W,lx+lw),min(H,ly+lw)
    a = alpha[y0-ly:y1-ly, x0-lx:x1-lx]*blink
    canvas[y0:y1, x0:x1] = canvas[y0:y1, x0:x1]*(1-a) + rgb[y0-ly:y1-ly, x0-lx:x1-lx]*a

    # ---- bandeau texte defilant (booth)
    by = int(H*0.86)
    bh = MARQ.height
    off = int((t*220) % MW)
    strip = Image.new("RGB", (W, bh), (0,0,0))
    m = MARQ
    x = -off
    while x < W:
        strip.paste(m, (x, 0), m); x += MW
    sa = np.asarray(strip, np.float32)
    shue = apply_hue(sa, t*2.0)
    yb0, yb1 = by, min(H, by+bh)
    canvas[yb0:yb1] += shue[:yb1-yb0]*1.0

    # ---- glitch global occasionnel (RGB shift plein cadre)
    if rng.random() < 0.10:
        s = rng.integers(3, 10)
        canvas[..., 0] = np.roll(canvas[..., 0], s, axis=1)
        canvas[..., 2] = np.roll(canvas[..., 2], -s, axis=1)
    # scanlines
    canvas[::3] *= 0.92

    Image.fromarray(np.clip(canvas,0,255).astype(np.uint8)).save(
        f"{OUT_DIR}/f_{f:04d}.png")
    if f % 30 == 0: print(f"  {f}/{NF}")

print("Encodage mp4...")
OUT = "/home/user/lucie/mls-mapping/mls-mapping.mp4"
subprocess.run([
    "ffmpeg","-y","-framerate",str(FPS),"-i",f"{OUT_DIR}/f_%04d.png",
    "-c:v","libx264","-pix_fmt","yuv420p","-crf","19","-movflags","+faststart",
    OUT], check=True)
print("OK ->", OUT)
