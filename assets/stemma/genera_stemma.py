from PIL import Image, ImageDraw
import math

# Stessi valori di ic_launcher_background.xml / ic_launcher_foreground.xml
# (Jarvis-App-Android): sfondo #0B0F1A, anello #5B7CFA largo 3/108, cerchio
# pieno #00D9C0 raggio 20/108, tutto centrato su un viewport 108x108.
BG = "#0B0F1A"
RING = "#5B7CFA"
FILL = "#00D9C0"
VIEWPORT = 108.0
RING_R = 34.0
RING_W = 3.0
FILL_R = 20.0
CX = CY = 54.0

def render(size, path, rounded=False, transparent_bg=False):
    ss = 4  # supersampling per anti-aliasing
    big = size * ss
    scale = big / VIEWPORT
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0) if transparent_bg else BG)
    draw = ImageDraw.Draw(img)
    if not transparent_bg:
        draw.rectangle([0, 0, big, big], fill=BG)
    cx, cy = CX * scale, CY * scale
    ring_r = RING_R * scale
    ring_w = RING_W * scale
    fill_r = FILL_R * scale
    draw.ellipse([cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r],
                 outline=RING, width=round(ring_w))
    draw.ellipse([cx - fill_r, cy - fill_r, cx + fill_r, cy + fill_r], fill=FILL)
    img = img.resize((size, size), Image.LANCZOS)
    if rounded:
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, size, size], fill=255)
        out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        out.paste(img, (0, 0), mask)
        img = out
    img.save(path)
    print("scritto", path, size)

if __name__ == "__main__":
    import sys
    out_dir = sys.argv[1]
    render(192, f"{out_dir}/stemma-192.png")
    render(512, f"{out_dir}/stemma-512.png")
    render(1024, f"{out_dir}/stemma-1024.png")
    render(64, f"{out_dir}/stemma-64.png")
    render(32, f"{out_dir}/stemma-32.png")
    render(180, f"{out_dir}/stemma-180.png")  # apple-touch-icon
