import os
import struct
import sys

# magic consts from Amicitia
_TAG_SPR0 = b"SPR0"
_TAG_SPR4 = b"SPR4"
_TAG_SPR6 = 0x36525053   # little-endian int32: b"SPR6"
_TAG_TXP0 = b"TXP0"

_SPR_HEADER_SIZE   = 0x20
_TXP_HEADER_SIZE   = 0x10  # flag(2)+userId(2)+length(4)+tag(4)+unused(4)
_TYPE_PTR_ENTRY    = 8     # {i32 type, i32 offset}

# detection:
def _detect(data: bytes) -> str | None:
    """Return 'SPR0', 'SPR4', 'SPR6', 'TXP0', or None."""
    if len(data) < 12:
        return None
    # SPR6: first 4 bytes are little-endian int magic
    if struct.unpack_from("<I", data, 0)[0] == _TAG_SPR6:
        return "SPR6"
    # SPR0 / SPR4: tag is at offset 8
    tag = data[8:12]
    if tag == _TAG_SPR0:
        return "SPR0"
    if tag == _TAG_SPR4:
        return "SPR4"
    # TXP0: tag is at offset 8 as well (after flag+userId+length)
    if tag == _TAG_TXP0:
        return "TXP0"
    return None


# SPR0 / SPR4 reader

def _read_spr0_spr4(data: bytes) -> list[bytes]:
    """
    Parse SPR0 or SPR4 and return list of raw texture blobs.
    Layout is identical for both; only the texture format differs.
    """
    if len(data) < _SPR_HEADER_SIZE:
        return []

    # flags(2) + userId(2) + reserved(4) + tag(4) + headerSize(4) +
    # deprecatedSize(4) + numTextures(2) + numKeyFrames(2) +
    # texPtrTableOffset(4) + kfPtrTableOffset(4)
    (flags, user_id, reserved, tag,
     header_size, deprecated_size,
     num_textures, num_keyframes,
     tex_ptr_offset, kf_ptr_offset) = struct.unpack_from("<HHI4sIIHHII", data, 0)

    if num_textures == 0:
        return []

    textures = []
    for i in range(num_textures):
        entry_off = tex_ptr_offset + i * _TYPE_PTR_ENTRY
        if entry_off + 8 > len(data):
            break
        _type, tex_off = struct.unpack_from("<II", data, entry_off)
        if tex_off == 0 or tex_off >= len(data):
            continue
        # The texture blob extends to the next texture offset (or end of file).
        # Determine size: look at subsequent pointer table entry, fall back to EOF.
        if i + 1 < num_textures:
            next_entry_off = tex_ptr_offset + (i + 1) * _TYPE_PTR_ENTRY
            _, next_off = struct.unpack_from("<II", data, next_entry_off)
        else:
            next_off = len(data)
        blob = data[tex_off:next_off].rstrip(b"\x00")
        if blob:
            textures.append(blob)

    return textures


# TXP0 / TB reader:

def _read_txp0(data: bytes) -> list[bytes]:
    """
    Parse TXP0 (TbFile) and return list of raw TMX blobs.
    Header: flag(2)+userId(2)+length(4)+tag(4)+unused(4) = 0x10 bytes
    Then: numTextures(4)
    Then: numTextures * i32 pointer table (offsets from file start)
    Then: TMX data blocks aligned to 64 bytes.
    """
    if len(data) < _TXP_HEADER_SIZE + 4:
        return []

    num_textures = struct.unpack_from("<I", data, _TXP_HEADER_SIZE)[0]
    if num_textures == 0 or num_textures > 4096:
        return []

    ptr_table_off = _TXP_HEADER_SIZE + 4
    textures = []
    for i in range(num_textures):
        ptr_off = ptr_table_off + i * 4
        if ptr_off + 4 > len(data):
            break
        tex_off = struct.unpack_from("<I", data, ptr_off)[0]
        if tex_off == 0 or tex_off >= len(data):
            continue
        if i + 1 < num_textures:
            next_off = struct.unpack_from("<I", data, ptr_off + 4)[0]
        else:
            next_off = len(data)
        blob = data[tex_off:next_off].rstrip(b"\x00")
        if blob:
            textures.append(blob)

    return textures


# SPR6 reader:

def _read_spr6(data: bytes) -> list[bytes]:
    """
    Parse SPR6 and return list of raw TGA blobs.
    Header (from Amicitia Spr6File.Read):
      i32 magic
      i16 Field04
      i16 Field08
      i32 fileSize
      i16 Field0C
      i16 textureCount
      i16 spriteCount
      i16 panelCount
      i32 textureTableOffset (absolute, from ReadOffset)
      i32 spriteDataOffset
      i32 Field1C

    Each Spr6Texture entry (from Spr6Texture.Read):
      char[20] description
      i32 Field00
      i32 Field04
      i16 Field08
      i16 Field0A
      i32 size
      i32 Field14
      i32 dataOffset (absolute offset into file)
    Total fixed part: 20+4+4+2+2+4+4+4 = 44 bytes
    """
    if len(data) < 28:
        return []

    # magic(4)+F04(2)+F08(2)+fileSize(4)+F0C(2)+texCount(2)+sprCount(2)+panCount(2) = 20
    magic, f04, f08, file_size, f0c, tex_count, spr_count, pan_count = \
        struct.unpack_from("<IhhIhhhh", data, 0)

    if tex_count == 0 or tex_count > 4096:
        return []

    # Next two i32s are offsets to the texture array and sprite data
    tex_table_off = struct.unpack_from("<I", data, 20)[0]
    if tex_table_off == 0 or tex_table_off >= len(data):
        return []

    _TEX_ENTRY_SIZE = 44  # 20+4+4+2+2+4+4+4
    textures = []
    pos = tex_table_off
    for i in range(tex_count):
        if pos + _TEX_ENTRY_SIZE > len(data):
            break
        # description(20) + Field00(4) + Field04(4) + Field08(2) + Field0A(2)
        # + size(4) + Field14(4) + dataOffset(4)
        desc = data[pos:pos+20]
        size     = struct.unpack_from("<I", data, pos + 28)[0]
        data_off = struct.unpack_from("<I", data, pos + 36)[0]
        pos += _TEX_ENTRY_SIZE

        if size == 0 or data_off == 0 or data_off + size > len(data):
            continue
        textures.append(data[data_off:data_off + size])

    return textures


#Texture conversion
def _convert_texture(blob: bytes, out_dir: str, stem: str, index: int,
                     fmt: str, tmx_mod) -> tuple[bool, str]:
    """
    Write one texture blob to disk and convert if possible.
    fmt: 'TMX' or 'TGA'
    Returns (ok, output_filename).
    """
    if fmt == "TMX":
        if tmx_mod is not None:
            png_path = os.path.join(out_dir, f"{stem}_{index:02d}.png")
            result = tmx_mod.decode_tmx(blob)
            if result is not None:
                pixels, w, h = result
                try:
                    from PIL import Image
                    img = Image.new("RGBA", (w, h))
                    img.putdata(pixels[:w * h])
                    img.save(png_path, "PNG")
                    return True, os.path.basename(png_path)
                except Exception as e:
                    pass
        # Fallback: save raw TMX
        tmx_path = os.path.join(out_dir, f"{stem}_{index:02d}.tmx")
        with open(tmx_path, "wb") as f:
            f.write(blob)
        return True, os.path.basename(tmx_path)

    elif fmt == "TGA":
        tga_path = os.path.join(out_dir, f"{stem}_{index:02d}.tga")
        with open(tga_path, "wb") as f:
            f.write(blob)
        return True, os.path.basename(tga_path)

    return False, "unknown format"


# Public API
def process_spr(src_path: str, out_dir: str, log=print) -> dict:
    # Extract textures from an SPR/SPR4/SPR6/TXP file.
    result = dict(total=0, ok=0, outputs=[])
    os.makedirs(out_dir, exist_ok=True)

    try:
        with open(src_path, "rb") as f:
            data = f.read()
    except Exception as e:
        log(f"      SPR read error: {e}", 5)
        return result

    fmt = _detect(data)
    if fmt is None:
        log(f"      SPR: unrecognised format [{os.path.basename(src_path)}]", 5)
        return result

    # Load tmx_to_png
    tmx_mod = None
    _here = os.path.dirname(os.path.abspath(__file__))
    _tmx_py = os.path.join(_here, "tmx_to_png.py")
    if os.path.isfile(_tmx_py):
        try:
            import importlib.util as _ilu
            spec = _ilu.spec_from_file_location("tmx_to_png", _tmx_py)
            mod  = _ilu.module_from_spec(spec)
            spec.loader.exec_module(mod)
            tmx_mod = mod
        except Exception:
            pass

    stem = os.path.splitext(os.path.basename(src_path))[0]

    if fmt in ("SPR0", "SPR4"):
        blobs = _read_spr0_spr4(data)
        tex_fmt = "TMX" if fmt == "SPR0" else "TGA"
    elif fmt == "TXP0":
        blobs = _read_txp0(data)
        tex_fmt = "TMX"
    elif fmt == "SPR6":
        blobs = _read_spr6(data)
        tex_fmt = "TGA"
    else:
        blobs = []
        tex_fmt = "TMX"

    result["total"] = len(blobs)

    for i, blob in enumerate(blobs):
        ok, fname = _convert_texture(blob, out_dir, stem, i, tex_fmt, tmx_mod)
        if ok:
            result["ok"] += 1
            result["outputs"].append(fname)
            log(f"      {fmt} tex[{i}] -> {fname}", 4)
        else:
            log(f"      {fmt} tex[{i}] convert failed", 5)

    return result

def main():
    if len(sys.argv) < 2:
        print("Usage: spr_extract.py <file.spr|file.txp> [out_dir]")
        sys.exit(1)

    src = sys.argv[1].strip().strip('"')
    if not os.path.isfile(src):
        print(f"ERROR: not found: {src}")
        sys.exit(1)

    out_dir = (sys.argv[2] if len(sys.argv) >= 3
               else os.path.join(os.path.dirname(os.path.abspath(src)),
                                 os.path.splitext(os.path.basename(src))[0]))

    def cli_log(msg, pair=2):
        print(msg)

    res = process_spr(src, out_dir, log=cli_log)
    print(f"\nDone. {res['ok']}/{res['total']} textures extracted.")
    if res["outputs"]:
        for f in res["outputs"]:
            print(f"  {f}")


if __name__ == "__main__":
    main()
