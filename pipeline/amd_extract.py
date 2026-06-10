import os
import struct
import sys

_MAGIC    = b"CHNK"
_TAG_SIZE = 16

_MAGIC_TO_EXT = {
    b"OMG.":     ".gmo",
    b"\x00TMX":  ".tmx",
    b"SPR\x00":  ".spr",
    b"PSE\x00":  ".pse",
    b"MSE\x00":  ".mse",
    b"BED\x00":  ".bed",
    b"EPL\x00":  ".epl",
    b"FLWC":     ".bf",
    b"FLWS":     ".bf",
    b"AFS\x00":  ".afs",
    b"CPK ":     ".cpk",
    b"BVP\x00":  ".bvp",
    b"RIFF":     ".wav",
    b"VAGp":     ".vag",
    b"ADX\x00":  ".adx",
    b"\x80\x00": ".adx",
    b"HCA\x00":  ".hca",
    b"fLaC":     ".flac",
    b"PMF\x00":  ".pmf",
    b"MTSF":     ".pmsf",
    b"SOFD":     ".sfd",
    b"SFHD":     ".sfd",
    b"CHNK":     ".amd",
}

def _guess_ext(data: bytes) -> str:
    for magic, ext in _MAGIC_TO_EXT.items():
        if data[:len(magic)] == magic:
            return ext
    return ".bin"


# Parser (mirrors AmdFile.Read + AmdChunk.InternalRead)

def _parse_amd(data: bytes) -> list[tuple[str, int, bytes]]:
    # Return list of (tag, flags, chunk_data) tuples.
    if len(data) < 8:
        return []
    if data[:4] != _MAGIC:
        return []

    num_chunks = struct.unpack_from("<i", data, 4)[0]
    if num_chunks <= 0 or num_chunks > 65536:
        return []

    chunks = []
    pos = 8
    for _ in range(num_chunks):
        if pos + _TAG_SIZE + 8 > len(data):
            break
        raw_tag = data[pos:pos + _TAG_SIZE]
        tag = raw_tag.split(b"\x00")[0].decode("ascii", errors="replace").strip()
        pos += _TAG_SIZE
        flags = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        size = struct.unpack_from("<i", data, pos)[0]
        pos += 4
        if size < 0 or pos + size > len(data):
            break
        chunks.append((tag, flags, data[pos:pos + size]))
        pos += size

    return chunks
# api
def extract(src_path: str, out_dir: str, log=print) -> dict:
    result = dict(total=0, ok=0, outputs=[])
    os.makedirs(out_dir, exist_ok=True)

    try:
        with open(src_path, "rb") as f:
            data = f.read()
    except Exception as e:
        log(f"      AMD read error: {e}", 5)
        return result

    chunks = _parse_amd(data)
    result["total"] = len(chunks)

    if not chunks:
        log(f"      AMD: no chunks found [{os.path.basename(src_path)}]", 6)
        return result

    seen: dict[str, int] = {}
    for tag, flags, chunk_data in chunks:
        ext  = _guess_ext(chunk_data)
        base = tag if tag else "chunk"
        key  = (base + ext).lower()
        if key in seen:
            seen[key] += 1
            fname = f"{base}_{seen[key]}{ext}"
        else:
            seen[key] = 0
            fname = base + ext

        out_path = os.path.join(out_dir, fname)
        try:
            with open(out_path, "wb") as f:
                f.write(chunk_data)
            result["ok"] += 1
            result["outputs"].append(fname)
            log(f"      AMD chunk '{tag}' -> {fname}", 4)
        except Exception as e:
            log(f"      AMD chunk '{tag}' write error: {e}", 5)

    return result


# cli
def main():
    if len(sys.argv) < 2:
        print("Usage: amd_extract.py <file.amd> [out_dir]")
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

    print(f"Input  : {src}")
    print(f"Output : {out_dir}")
    print()

    res = extract(src, out_dir, log=cli_log)
    print(f"\nDone. {res['ok']}/{res['total']} chunks extracted.")
    for f in res["outputs"]:
        print(f"  {f}")


if __name__ == "__main__":
    main()
