"""Erzeugt packaging/visualcut.ico: Filmstreifen mit Schnittmarke in den Farben aus design/mockups/README.md."""

from pathlib import Path

from PIL import Image, ImageDraw

BG, PANEL, ACCENT, CUT = "#09090b", "#18181b", "#338EF7", "#F31260"


def draw(size: int) -> Image.Image:
    s = 256
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((8, 8, s - 8, s - 8), radius=56, fill=BG)
    d.rounded_rectangle((40, 64, s - 40, s - 64), radius=20, fill=PANEL, outline=ACCENT, width=10)
    for x in range(58, s - 50, 30):  # Perforation
        d.rectangle((x, 76, x + 14, 88), fill=ACCENT)
        d.rectangle((x, s - 88, x + 14, s - 76), fill=ACCENT)
    d.polygon([(118, 34), (138, 34), (150, 222), (106, 222)], fill=CUT)  # Schnitt
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    out = Path(__file__).with_name("visualcut.ico")
    draw(256).save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(out)
