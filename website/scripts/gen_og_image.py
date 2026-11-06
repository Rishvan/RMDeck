from PIL import Image, ImageDraw, ImageFont
import math

W, H = 1280, 720

def lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))

stops = [(0.0, (124, 147, 255)), (0.45, (76, 110, 245)), (1.0, (39, 67, 209))]

def color_at(t):
    for i in range(len(stops) - 1):
        t0, c0 = stops[i]
        t1, c1 = stops[i + 1]
        if t0 <= t <= t1:
            local = (t - t0) / (t1 - t0) if t1 > t0 else 0
            return lerp(c0, c1, local)
    return stops[-1][1]

img = Image.new("RGB", (W, H))
px = img.load()
for y in range(H):
    for x in range(W):
        t = (x + y) / (W + H)
        px[x, y] = color_at(t)

# --- big logo on the left ---
logo = Image.open("assets/logo-source.png").convert("RGBA")
logo_size = 340
logo = logo.resize((logo_size, logo_size), Image.LANCZOS)

pad = 28
plate_size = logo_size + pad * 2
plate = Image.new("RGBA", (plate_size, plate_size), (0, 0, 0, 0))
pdraw = ImageDraw.Draw(plate)
pdraw.rounded_rectangle([0, 0, plate_size, plate_size], radius=56, fill=(255, 255, 255, 235))
plate.alpha_composite(logo, (pad, pad))

left_cx = 300
plate_x = left_cx - plate_size // 2
plate_y = H // 2 - plate_size // 2
img.paste(plate, (plate_x, plate_y), plate)

img = img.convert("RGBA")

# --- text content on the right ---
font_bold = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 72)
font_reg = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 28)
font_small = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 17)

right_x = 600
right_edge = W - 70

draw = ImageDraw.Draw(img)

def wrap_text(text, font, max_width):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textbbox((0, 0), trial, font=font)[2] <= max_width:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines

max_text_width = right_edge - right_x

title = "RMDex"
tagline_lines = wrap_text(
    "Send exactly the audio you want, from gaming PC to streaming PC.",
    font_reg,
    max_text_width,
)
badge_text = "FREE & OPEN SOURCE · WINDOWS"

title_h = draw.textbbox((0, 0), title, font=font_bold)[3]
line_h = draw.textbbox((0, 0), "Ag", font=font_reg)[3] + 20
badge_pad_x, badge_pad_y = 16, 9
badge_bbox = draw.textbbox((0, 0), badge_text, font=font_small)
badge_w = (badge_bbox[2] - badge_bbox[0]) + badge_pad_x * 2
badge_h = (badge_bbox[3] - badge_bbox[1]) + badge_pad_y * 2

gap_title_tagline = 22
gap_tagline_badge = 26
total_h = title_h + gap_title_tagline + len(tagline_lines) * line_h + gap_tagline_badge + badge_h

y = H // 2 - total_h // 2

draw.text((right_x, y), title, font=font_bold, fill=(255, 255, 255, 255))
y += title_h + gap_title_tagline

for line in tagline_lines:
    draw.text((right_x, y), line, font=font_reg, fill=(255, 255, 255, 235))
    y += line_h

badge_y = y + gap_tagline_badge - line_h + (line_h - badge_h) // 2
badge_x = right_x

badge_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
bl_draw = ImageDraw.Draw(badge_layer)
bl_draw.rounded_rectangle(
    [badge_x, badge_y, badge_x + badge_w, badge_y + badge_h],
    radius=badge_h / 2,
    fill=(255, 255, 255, 40),
    outline=(255, 255, 255, 150),
    width=1,
)
img = Image.alpha_composite(img, badge_layer)
draw = ImageDraw.Draw(img)
draw.text((badge_x + badge_pad_x, badge_y + badge_pad_y - 2), badge_text, font=font_small, fill=(255, 255, 255))

img.convert("RGB").save("public/og-image.png", format="JPEG", quality=85, optimize=True, progressive=True)
print("saved", img.size)
