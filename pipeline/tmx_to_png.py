"""
Based on PersonaEditor source (PersonaEditorLib/Sprite/TMX*.cs)

TMX header layout (0x40 bytes, little-endian):
  +0x00  u16  ID          (must be 0x0002)
  +0x02  u16  UnknownID
  +0x04  i32  FileSize
  +0x08  u32  MagicNumber (must be 0x30584D54 = "TMX0")
  +0x0C  i32  Padding     (must be 0)
  +0x10  u8   PaletteCount
  +0x11  u8   PaletteFormat
  +0x12  u16  Width
  +0x14  u16  Height
  +0x16  u8   PixelFormat
  +0x17  u8   MipMapCount (must be 0)
  +0x18  u8   MipMapK
  +0x19  u8   MipMapL
  +0x1A  u16  WrapMode    (must be 0xFF00)
  +0x1C  u32  TextureID
  +0x20  u32  ClutID
  +0x24  28 bytes Comment
"""

import os, struct, sys

try:
    from PIL import Image
    _PIL = True
except ImportError:
    _PIL = False

HEADER_SIZE  = 0x40
MAGIC        = 0x30584D54
TMX_ID       = 0x0002

PSMTC32  = 0x00
PSMTC24  = 0x01
PSMTC16  = 0x02
PSMTC16S = 0x0A
PSMT8    = 0x13
PSMT4    = 0x14

def _ensure_pil():
    global Image, _PIL
    if _PIL: return True
    try:
        import subprocess
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "pillow", "-q"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        from PIL import Image
        _PIL = True
        return True
    except: return False

def _tile_palette(palette_bytes):
    """Reorder PSMT8 256-color palette from PS2 tile storage to linear order."""
    pal = list(struct.iter_unpack("4s", palette_bytes))
    out = []
    index = 0
    for _ in range(8):
        for x in range(8):  out.append(pal[index + x])
        index += 16
        for x in range(8):  out.append(pal[index + x])
        index -= 8
        for x in range(8):  out.append(pal[index + x])
        index += 16
        for x in range(8):  out.append(pal[index + x])
        index += 8
    return b"".join(c[0] for c in out)

def _decode_rgba32_ps2(data, count):
    """PS2 RGBA32: alpha is 0-128, map to 0-255."""
    pixels = []
    for i in range(count):
        r, g, b, a = struct.unpack_from("BBBB", data, i * 4)
        a = min(255, a * 2)
        pixels.append((r, g, b, a))
    return pixels

def _indexed8(image_data, palette):
    return [palette[b] for b in image_data]

def _indexed4(image_data, palette, width):
    """PSMT4: low nibble first per byte, reversed within each row pair."""
    pixels = []
    for b in image_data:
        pixels.append(palette[b & 0x0F])
        pixels.append(palette[(b >> 4) & 0x0F])
    return pixels

def _stride(pixel_format, width):
    if pixel_format == PSMT8:   return width
    if pixel_format == PSMT4:   return (width + 1) // 2
    if pixel_format == PSMTC32: return width * 4
    if pixel_format == PSMTC24: return width * 3
    if pixel_format in (PSMTC16, PSMTC16S): return width * 2
    return width

def decode_tmx(data):
    """
    Decode TMX bytes to list of (r,g,b,a) tuples plus (width, height).
    Returns (pixels, width, height) or None on failure.
    """
    if len(data) < HEADER_SIZE:
        return None

    tmx_id, unknown_id, file_size, magic, padding = struct.unpack_from("<HHiIi", data, 0)
    if tmx_id != TMX_ID or magic != MAGIC:
        return None

    palette_count  = data[0x10]
    palette_format = data[0x11]
    width          = struct.unpack_from("<H", data, 0x12)[0]
    height         = struct.unpack_from("<H", data, 0x14)[0]
    pixel_format   = data[0x16]

    if width == 0 or height == 0:
        return None

    pos = HEADER_SIZE

    palettes = []
    for _ in range(palette_count):
        if pixel_format == PSMT8:
            raw = data[pos: pos + 256 * 4]
            tiled = _tile_palette(raw)
            palettes.append(_decode_rgba32_ps2(tiled, 256))
            pos += 256 * 4
        elif pixel_format == PSMT4:
            raw = data[pos: pos + 16 * 4]
            palettes.append(_decode_rgba32_ps2(raw, 16))
            pos += 16 * 4

    stride = _stride(pixel_format, width)
    image_data = data[pos: pos + stride * height]

    if pixel_format == PSMTC32:
        pixels = _decode_rgba32_ps2(image_data, width * height)
    elif pixel_format == PSMT8:
        pal = palettes[0] if palettes else [(0,0,0,255)]*256
        pixels = _indexed8(image_data, pal)
    elif pixel_format == PSMT4:
        pal = palettes[0] if palettes else [(0,0,0,255)]*16
        pixels = _indexed4(image_data, pal, width)
    elif pixel_format == PSMTC16 or pixel_format == PSMTC16S:
        pixels = []
        for i in range(width * height):
            v = struct.unpack_from("<H", image_data, i * 2)[0]
            r = ((v      ) & 0x1F) << 3
            g = ((v >>  5) & 0x1F) << 3
            b = ((v >> 10) & 0x1F) << 3
            a = 255 if (v >> 15) else 0
            pixels.append((r, g, b, a))
    else:
        return None

    return pixels, width, height

def convert(tmx_path, png_path):
    if not _ensure_pil():
        return False, "Pillow not available"
    try:
        with open(tmx_path, "rb") as f:
            data = f.read()
    except Exception as e:
        return False, f"Read error: {e}"

    result = decode_tmx(data)
    if result is None:
        return False, f"Unrecognized TMX (magic={data[8:12].hex() if len(data)>=12 else '?'} id={struct.unpack_from('<H',data,0)[0] if len(data)>=2 else '?'})"

    pixels, w, h = result
    try:
        img = Image.new("RGBA", (w, h))
        img.putdata(pixels[:w * h])
        os.makedirs(os.path.dirname(os.path.abspath(png_path)), exist_ok=True)
        img.save(png_path, "PNG")
    except Exception as e:
        return False, f"Save error: {e}"

    return True, f"{w}x{h}"

def main():
    if len(sys.argv) < 2:
        print("Usage: tmx_to_png.py <file.tmx> [out.png]")
        print("       tmx_to_png.py <folder>")
        sys.exit(1)

    target = sys.argv[1].strip().strip('"')

    if os.path.isdir(target):
        ok = fail = 0
        for root, _, files in os.walk(target):
            for f in files:
                if f.lower().endswith(".tmx"):
                    src = os.path.join(root, f)
                    dst = os.path.splitext(src)[0] + ".png"
                    good, msg = convert(src, dst)
                    if good: ok += 1;   print(f"  OK    {f}  ({msg})")
                    else:    fail += 1; print(f"  FAIL  {f}: {msg}")
        print(f"\nDone. {ok} converted, {fail} failed.")
    else:
        out = sys.argv[2] if len(sys.argv) >= 3 else os.path.splitext(target)[0] + ".png"
        ok, msg = convert(target, out)
        print(f"OK: {out}  ({msg})" if ok else f"FAILED: {msg}")
        if not ok: sys.exit(1)

if __name__ == "__main__":
    main()
