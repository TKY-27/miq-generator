"""Aspect-preserving media placement and the approved edge fades."""

from PIL import Image, ImageChops, ImageOps


def edge_mask(size, fade):
    def axis(n):
        values = []
        for pos in range(n):
            t = min(1, max(0, min(pos, n - 1 - pos) / fade))
            values.append(round(255 * t * t * (3 - 2 * t)))
        image = Image.new("L", (n, 1))
        image.putdata(values)
        return image

    w, h = size
    return ImageChops.multiply(
        axis(w).resize(size), axis(h).transpose(Image.Transpose.ROTATE_90).resize(size)
    )


def read_image(path):
    with Image.open(path) as source:
        return ImageOps.exif_transpose(source).convert("RGBA")


def classic_image(canvas, image, attachment=False):
    w, h = canvas.size
    kx, ky = w / 1920, h / 1080
    k = min(kx, ky)
    side = max(1, round(970 * k))
    if attachment:
        image = ImageOps.contain(image, (side, side), Image.Resampling.LANCZOS)
    else:
        image = ImageOps.fit(image, (side, side), Image.Resampling.LANCZOS)
    xy = (
        round(-12 * kx) + (side - image.width) // 2,
        round(65 * k) + (side - image.height) // 2,
    )
    layer = Image.new("RGBA", canvas.size)
    layer.alpha_composite(image, xy)
    horizontal = Image.new("L", (w, 1))
    values = []
    for x in range(w):
        t = max(0, min(1, (x - 555 * kx) / (405 * kx)))
        values.append(int(255 * (1 - t * t * (3 - 2 * t))))
    horizontal.putdata(values)
    vertical = Image.new("L", (1, h))
    top, bottom = round(65 * k), round(1035 * k)
    vertical.putdata(
        [
            max(0, int(255 * min(1, (y - top) / (92 * k), (bottom - y) / (115 * k))))
            if top <= y < bottom
            else 0
            for y in range(h)
        ]
    )
    mask = ImageChops.multiply(horizontal.resize((w, h)), vertical.resize((w, h)))
    edges = Image.new("L", (w, h))
    edges.paste(edge_mask(image.size, max(1, round(min(image.size) * 0.045))), xy)
    layer.putalpha(
        ImageChops.multiply(layer.getchannel("A"), ImageChops.multiply(mask, edges))
    )
    canvas.alpha_composite(layer)


def place_image(canvas, image, slot, attachment=False):
    sw, sh = slot[2] - slot[0], slot[3] - slot[1]
    if attachment:
        image = ImageOps.contain(image, (sw, sh), Image.Resampling.LANCZOS)
    else:
        side = min(sw, sh)
        image = ImageOps.fit(image, (side, side), Image.Resampling.LANCZOS)
    xy = (slot[0] + (sw - image.width) // 2, slot[1] + (sh - image.height) // 2)
    image.putalpha(
        ImageChops.multiply(
            image.getchannel("A"),
            edge_mask(image.size, max(3, round(min(image.size) * 0.06))),
        )
    )
    canvas.alpha_composite(image, xy)
