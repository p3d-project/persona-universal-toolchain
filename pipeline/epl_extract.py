import struct
import sys
import os
import subprocess
import shutil

# EPL format constants
_RMD_SIZE_OFFSET = 172          # bytes before RMD magic where size field lives
_RMD_MAGIC       = bytes.fromhex("F000F0F002")
_TMX_MAGIC       = b"TMX0"


# extraction
def _extract_raw(epl_data: bytes, out_dir: str) -> tuple[list[str], list[str]]:
    os.makedirs(out_dir, exist_ok=True)
    rmd_paths: list[str] = []
    tmx_paths: list[str] = []

    # TMX:
    tmx_number = 0
    pos = 0
    while True:
        loc = epl_data.find(_TMX_MAGIC, pos)
        if loc == -1:
            break
        pos = loc + 1
        size_off = loc - 4
        if size_off < 0:
            continue
        be_val  = int(epl_data[size_off:size_off + 4].hex(), 16)
        le_size = int(struct.pack("<I", be_val).hex(), 16)
        entry_start = loc - 8
        if entry_start < 0 or entry_start + le_size > len(epl_data):
            continue
        tmx_number += 1
        out_path = os.path.join(out_dir, f"{tmx_number}.tmx")
        with open(out_path, "wb") as f:
            f.write(epl_data[entry_start: entry_start + le_size])
        tmx_paths.append(out_path)

    # RMD 
    rmd_number = 0
    pos = 0
    while True:
        loc = epl_data.find(_RMD_MAGIC, pos)
        if loc == -1:
            break
        pos = loc + 1
        size_off = loc - _RMD_SIZE_OFFSET
        if size_off < 0:
            continue
        be_val  = int(epl_data[size_off:size_off + 4].hex(), 16)
        le_size = int(struct.pack("<I", be_val).hex(), 16)
        if le_size <= 0 or loc + le_size > len(epl_data):
            le_size = len(epl_data) - loc
        rmd_number += 1
        out_path = os.path.join(out_dir, f"{rmd_number}.RMD")
        with open(out_path, "wb") as f:
            f.write(epl_data[loc: loc + le_size])
        rmd_paths.append(out_path)

    return rmd_paths, tmx_paths

def _rmd_to_fbx(rmd_path: str, out_dir: str, rmdtoglb: str) -> tuple[bool, str]:
    #Convert one RMD to FBX. Returns ok
    try:
        r = subprocess.run(
            [rmdtoglb, rmd_path, out_dir],
            capture_output=True, timeout=120
        )
        if r.returncode != 0:
            detail = (r.stderr.decode(errors="ignore") +
                      r.stdout.decode(errors="ignore")).strip()
            return False, f"rc={r.returncode}: {detail[-200:]}"
        fbx = os.path.join(out_dir,
                           os.path.splitext(os.path.basename(rmd_path))[0] + ".fbx")
        if os.path.isfile(fbx) and os.path.getsize(fbx) > 0:
            os.remove(rmd_path)
            return True, fbx
        return False, "RmdToGlb ran but produced no FBX"
    except subprocess.TimeoutExpired:
        return False, "RmdToGlb timed out"
    except Exception as e:
        return False, str(e)


def _tmx_to_png(tmx_path: str, out_dir: str, noesis: str | None) -> tuple[bool, str]:
    #Convert one TMX to PNG. Uses tmx_to_png.py if available, fall back to Noesis.
    png_path = os.path.join(out_dir,
                            os.path.splitext(os.path.basename(tmx_path))[0] + ".png")
    _here = os.path.dirname(os.path.abspath(__file__))  # pipeline/
    _tmx_py = os.path.join(_here, "tmx_to_png.py")  # pipeline/tmx_to_png.py
    if os.path.isfile(_tmx_py):
        try:
            import importlib.util as _ilu
            spec = _ilu.spec_from_file_location("tmx_to_png", _tmx_py)
            mod  = _ilu.module_from_spec(spec)
            spec.loader.exec_module(mod)
            ok, msg = mod.convert(tmx_path, png_path)
            if ok:
                os.remove(tmx_path)
                return True, png_path
            return False, msg
        except Exception as e:
            pass
    if not noesis:
        return False, "tmx_to_png.py not found and Noesis not available"
    try:
        r = subprocess.run(
            [noesis, "?cmode", tmx_path, png_path],
            capture_output=True, timeout=60
        )
        if os.path.isfile(png_path) and os.path.getsize(png_path) > 0:
            os.remove(tmx_path)
            return True, png_path
        detail = (r.stderr.decode(errors="ignore") +
                  r.stdout.decode(errors="ignore")).strip()
        return False, f"Noesis rc={r.returncode}: {detail[-200:]}"
    except subprocess.TimeoutExpired:
        return False, "Noesis timed out"
    except Exception as e:
        return False, str(e)

def process_epl(epl_path: str, out_dir: str,
                rmdtoglb: str | None, noesis: str | None,
                log=print) -> dict:
    result = dict(rmd_total=0, rmd_ok=0, tmx_total=0, tmx_ok=0, outputs=[])

    with open(epl_path, "rb") as f:
        epl_data = f.read()

    rmd_paths, tmx_paths = _extract_raw(epl_data, out_dir)
    result["rmd_total"] = len(rmd_paths)
    result["tmx_total"] = len(tmx_paths)

    # rmd to fbx conv
    for rmd_path in rmd_paths:
        name = os.path.basename(rmd_path)
        if rmdtoglb:
            ok, msg = _rmd_to_fbx(rmd_path, out_dir, rmdtoglb)
            if ok:
                fbx_name = os.path.splitext(name)[0] + ".fbx"
                log(f"      RMD -> {fbx_name}", 4)
                result["rmd_ok"] += 1
                result["outputs"].append(fbx_name)
            else:
                log(f"      RMD kept (convert failed) [{name}]: {msg}", 5)
                result["outputs"].append(name)   # keep raw RMD as fallback
        else:
            log(f"      RMD kept (RmdToGlb not available) [{name}]", 6)
            result["outputs"].append(name)

    # TMX to PNG
    for tmx_path in tmx_paths:
        name = os.path.basename(tmx_path)
        if noesis:
            ok, msg = _tmx_to_png(tmx_path, out_dir, noesis)
            if ok:
                png_name = os.path.splitext(name)[0] + ".png"
                log(f"      TMX -> {png_name}", 4)
                result["tmx_ok"] += 1
                result["outputs"].append(png_name)
            else:
                log(f"      TMX kept (convert failed) [{name}]: {msg}", 5)
                result["outputs"].append(name)
        else:
            log(f"      TMX kept (Noesis not available) [{name}]", 6)
            result["outputs"].append(name)

    return result


def main():
    if len(sys.argv) >= 2:
        epl_path = sys.argv[1]
    else:
        epl_path = input("EPL file path: ").strip().strip('"')

    if not os.path.isfile(epl_path):
        print(f"ERROR: not found: {epl_path}")
        sys.exit(1)

    if len(sys.argv) >= 3:
        out_dir = sys.argv[2]
    else:
        base    = os.path.splitext(os.path.basename(epl_path))[0]
        out_dir = os.path.join(os.path.dirname(os.path.abspath(epl_path)), base)

    _here  = os.path.dirname(os.path.abspath(__file__))   # pipeline/
    _root  = os.path.dirname(_here)                        # repo root
    _tools = os.path.join(_root, "tools")

    rmdtoglb = None
    for candidate in (
        os.path.join(_root, "bin", "Debug", "net472", "RmdToGlb.exe"),
        os.path.join(_tools, "rmdtoglb", "RmdToGlb.exe"),
        shutil.which("RmdToGlb") or "",
    ):
        if candidate and os.path.isfile(candidate):
            rmdtoglb = candidate
            break

    noesis = None
    for candidate in (
        os.path.join(_tools, "Noesis", "Noesis64.exe"),
        shutil.which("Noesis64.exe") or "",
        shutil.which("noesis64") or "",
    ):
        if candidate and os.path.isfile(candidate):
            noesis = candidate
            break

    def cli_log(msg, pair=2):
        print(msg)

    print(f"Input  : {epl_path}")
    print(f"Output : {out_dir}")
    print(f"RmdToGlb : {rmdtoglb or 'NOT FOUND -- RMDs will be kept raw'}")
    print(f"Noesis   : {noesis   or 'NOT FOUND -- TMXs will be kept raw'}")
    print()

    res = process_epl(epl_path, out_dir, rmdtoglb, noesis, log=cli_log)
    print(f"\nDone.  RMD: {res['rmd_ok']}/{res['rmd_total']} -> FBX   "
          f"TMX: {res['tmx_ok']}/{res['tmx_total']} -> PNG")
    input("Press Enter to close.")


if __name__ == "__main__":
    main()
