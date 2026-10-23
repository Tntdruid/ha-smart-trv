"""Draw the Smart TRV brand icons into custom_components/smart_trv/brand/.

A thermostat dial (warm orange arc, the card's "heating" colour) around a radiator, with a
blue dot for the room sensor the dial is aimed at: the radiator, steered by the room.

Run:  python tools/make_brand.py   (needs Pillow)
"""

from math import cos, radians, sin
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "custom_components" / "smart_trv" / "brand"
SS = 4  # supersampling for smooth edges

ORANGE_A = (255, 179, 71)  # arc start (cool end of the dial)
ORANGE_B = (255, 90, 31)  # arc end (hot end)
BLUE = (3, 169, 244)  # room sensor, same as HA's primary colour
THEMES = {
    "light": {"radiator": (55, 71, 79), "track": (55, 71, 79, 40), "knob_ring": (255, 255, 255)},
    "dark": {"radiator": (225, 230, 233), "track": (225, 230, 233, 50), "knob_ring": (28, 28, 28)},
}


def lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def draw_icon(size: int, theme: str) -> Image.Image:
    s = size * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = s / 2
    t = THEMES[theme]

    # Dial: 270° arc, open at the bottom like HA's thermostat card.
    r = s * 0.43
    w = s * 0.085
    box = (c - r, c - r, c + r, c + r)
    start, end = 135, 405
    d.arc(box, start, end, fill=t["track"], width=round(w))
    steps = 180
    fill_to = 330  # how far the dial is "turned up"
    for i in range(steps):
        a0 = start + (fill_to - start) * i / steps
        a1 = start + (fill_to - start) * (i + 1) / steps + 0.6
        d.arc(box, a0, a1, fill=lerp(ORANGE_A, ORANGE_B, i / steps) + (255,), width=round(w))
    # round caps
    for ang, col in ((start, ORANGE_A), (fill_to, ORANGE_B)):
        x, y = c + (r - w / 2) * cos(radians(ang)), c + (r - w / 2) * sin(radians(ang))
        d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=col + (255,))

    # Room-sensor dot where the dial points.
    kx, ky = c + (r - w / 2) * cos(radians(fill_to)), c + (r - w / 2) * sin(radians(fill_to))
    kr = w * 0.95
    d.ellipse((kx - kr, ky - kr, kx + kr, ky + kr), fill=t["knob_ring"] + (255,))
    kr2 = w * 0.62
    d.ellipse((kx - kr2, ky - kr2, kx + kr2, ky + kr2), fill=BLUE + (255,))

    # Radiator: four fins joined by top and bottom pipes, with feet.
    col = t["radiator"] + (255,)
    fin_w, gap = s * 0.075, s * 0.04
    n = 4
    total = n * fin_w + (n - 1) * gap
    x0 = c - total / 2
    top, bottom = c - s * 0.17, c + s * 0.15
    rad = fin_w / 2
    for i in range(n):
        x = x0 + i * (fin_w + gap)
        d.rounded_rectangle((x, top, x + fin_w, bottom), radius=rad, fill=col)
    pipe_h = s * 0.035
    for y in (top + s * 0.045, bottom - s * 0.045 - pipe_h):
        d.rounded_rectangle((x0, y, x0 + total, y + pipe_h), radius=pipe_h / 2, fill=col)
    foot_w, foot_h = fin_w * 0.6, s * 0.04
    for x in (x0 + fin_w * 0.2, x0 + total - fin_w * 0.2 - foot_w):
        d.rounded_rectangle((x, bottom - foot_h * 0.3, x + foot_w, bottom + foot_h), radius=foot_w / 3, fill=col)

    # Heat: three small warm waves above the radiator.
    for i in (-1, 0, 1):
        hx = c + i * (fin_w + gap) * 1.05
        hy0, hy1 = top - s * 0.035, top - s * 0.11
        pts = []
        for k in range(21):
            u = k / 20
            pts.append((hx + sin(u * 6.283) * s * 0.012, hy0 + (hy1 - hy0) * u))
        d.line(pts, fill=lerp(ORANGE_A, ORANGE_B, 0.6) + (255,), width=round(s * 0.018), joint="curve")

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for theme, prefix in (("light", ""), ("dark", "dark_")):
        draw_icon(256, theme).save(OUT / f"{prefix}icon.png", optimize=True)
        draw_icon(512, theme).save(OUT / f"{prefix}icon@2x.png", optimize=True)
    print("wrote", sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()
