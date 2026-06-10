import os
import struct
import sys
import importlib.util

HERE        = os.path.dirname(os.path.abspath(__file__))
PIPELINE    = os.path.join(HERE, "pipeline")
DEFAULT_IN  = os.path.join(HERE, "in")
DEFAULT_OUT = os.path.join(HERE, "out")

PAK_NAME_LEN = 252
PAK_ALIGN    = 64

MAGIC_TO_EXT = {
    b"SPR\x00": ".spr",
    b"\x00TMX": ".tmx",
    b"SPR0":    ".spr",
    b"SPR4":    ".spr",
    b"SPR6":    ".spr",
    b"TXP0":    ".txp",
}


def _load(name):
    path = os.path.join(PIPELINE, f"{name}.py")
    if not os.path.isfile(path):
        return None
    spec = importlib.util.spec_from_file_location(name, path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _detect_ext(data, fallback):
    for magic, ext in MAGIC_TO_EXT.items():
        if data[:len(magic)] == magic:
            return ext
    fb = os.path.splitext(fallback)[1].lower()
    return fb if fb else ".bin"


def _pak_align(pos):
    return (pos + PAK_ALIGN - 1) & ~(PAK_ALIGN - 1)


def extract_pak(pak_path, out_dir):
    with open(pak_path, "rb") as f:
        data = f.read()

    pos = 0
    extracted = []
    seen = {}

    while pos + PAK_NAME_LEN + 4 <= len(data):
        raw_name = data[pos:pos + PAK_NAME_LEN].split(b"\x00")[0].decode("ascii", errors="ignore").strip()
        pos += PAK_NAME_LEN
        data_len = struct.unpack_from("<i", data, pos)[0]
        pos += 4

        if data_len <= 0:
            break
        if pos + data_len > len(data):
            break

        file_data = data[pos:pos + data_len]
        pos = _pak_align(pos + data_len)

        ext  = _detect_ext(file_data, raw_name)
        base = os.path.splitext(os.path.basename(raw_name))[0] if raw_name else \
               os.path.splitext(os.path.basename(pak_path))[0]

        key = (base + ext).lower()
        if key in seen:
            seen[key] += 1
            name = f"{base}_{seen[key]}{ext}"
        else:
            seen[key] = 0
            name = base + ext

        dest = os.path.join(out_dir, name)
        with open(dest, "wb") as wf:
            wf.write(file_data)

        extracted.append((name, dest, ext))

    return extracted


def process_pak(pak_path, out_root):
    stem    = os.path.splitext(os.path.basename(pak_path))[0]
    pak_out = os.path.join(out_root, stem)
    os.makedirs(pak_out, exist_ok=True)

    print(f"\n=== {os.path.basename(pak_path)} -> {pak_out} ===")

    entries = extract_pak(pak_path, pak_out)
    if not entries:
        print("  No entries found in PAK.")
        return

    spr_mod = _load("spr_extract")
    tmx_mod = _load("tmx_to_png")

    spr_count = 0
    png_count = 0

    for name, path, ext in entries:
        if ext in (".spr", ".txp") and spr_mod:
            spr_stem    = os.path.splitext(name)[0]
            spr_out_dir = os.path.join(pak_out, spr_stem)
            print(f"  SPR: {name}")
            res = spr_mod.process_spr(path, spr_out_dir)
            spr_count += 1
            png_count += res["ok"]
            if res["ok"] == 0:
                print(f"    (no textures found)")
            if res["ok"] > 0:
                os.remove(path)

        elif ext == ".tmx" and tmx_mod:
            tmx_stem = os.path.splitext(name)[0]
            png_path = os.path.join(pak_out, tmx_stem + ".png")
            print(f"  TMX: {name}")
            ok, msg = tmx_mod.convert(path, png_path)
            if ok:
                os.remove(path)
                png_count += 1
                print(f"    -> {os.path.basename(png_path)}")
            else:
                print(f"    FAILED: {msg}")

        else:
            print(f"  skipped: {name}")

    print(f"\n  Done. {spr_count} spr(s), {png_count} png(s) extracted.")


def main():
    if len(sys.argv) >= 2:
        targets = [sys.argv[1].strip().strip('"')]
    else:
        if not os.path.isdir(DEFAULT_IN):
            print(f"No argument given and no 'in' folder found at: {DEFAULT_IN}")
            sys.exit(1)
        targets = [
            os.path.join(DEFAULT_IN, f)
            for f in os.listdir(DEFAULT_IN)
            if f.lower().endswith(".pak")
        ]
        if not targets:
            print(f"No .pak files found in: {DEFAULT_IN}")
            sys.exit(1)

    for t in targets:
        if not os.path.isfile(t):
            print(f"ERROR: not found: {t}")
            continue
        process_pak(t, DEFAULT_OUT)


if __name__ == "__main__":
    main()
