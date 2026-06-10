import os
import struct
import sys
import importlib.util as _ilu

_ENTRY_SIZE = 0x0C   # flag(4) + offset(4) + length(4)


# Parser (mirrors BvpFile.InternalRead + BvpEntry constructor)
def _parse_bvp(data: bytes) -> list[bytes]:
    # Return list of raw BMD blobs extracted from BVP data.
    entries = []
    pos = 0
    while pos + _ENTRY_SIZE <= len(data):
        flag, offset, length = struct.unpack_from("<iii", data, pos)
        pos += _ENTRY_SIZE
        if length == 0:
            break   # terminator entry
        if length < 0 or offset < 0 or offset + length > len(data):
            break   # corrupt / end of table
        entries.append(data[offset:offset + length])
    return entries


# BMD module loader

def _load_bmd_module():
    _here = os.path.dirname(os.path.abspath(__file__))
    _path = os.path.join(_here, "bmd_decompile.py")
    if not os.path.isfile(_path):
        return None
    spec = _ilu.spec_from_file_location("bmd_decompile", _path)
    mod  = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def process_bvp(src_path: str, out_dir: str,
                compiler: str | None,
                log=print) -> dict:

    result = dict(total=0, extracted=0, decompiled=0, outputs=[])
    os.makedirs(out_dir, exist_ok=True)

    try:
        with open(src_path, "rb") as f:
            data = f.read()
    except Exception as e:
        log(f"      BVP read error: {e}", 5)
        return result

    blobs = _parse_bvp(data)
    result["total"] = len(blobs)

    if not blobs:
        log(f"      BVP: no entries found [{os.path.basename(src_path)}]", 6)
        return result

    bmd_mod = _load_bmd_module()
    stem = os.path.splitext(os.path.basename(src_path))[0]

    for i, blob in enumerate(blobs):
        # Write intermediate BMD
        bmd_name = f"{stem}_Entry{i:03d}.BMD"
        bmd_path = os.path.join(out_dir, bmd_name)
        try:
            with open(bmd_path, "wb") as f:
                f.write(blob)
        except Exception as e:
            log(f"      BVP entry {i} write error: {e}", 5)
            continue

        result["extracted"] += 1

        # Decompile to MSG if compiler is available
        if bmd_mod and compiler:
            ok, res = bmd_mod.process_script(bmd_path, out_dir, compiler, log=log)
            if ok:
                os.remove(bmd_path)   # clean up intermediate BMD
                result["decompiled"] += 1
                result["outputs"].append(res)
                log(f"      BVP[{i}] -> {res}", 4)
            else:
                # Keep the BMD as fallback
                result["outputs"].append(bmd_name)
                log(f"      BVP[{i}] BMD kept (decompile failed): {res}", 5)
        else:
            result["outputs"].append(bmd_name)
            if not compiler:
                log(f"      BVP[{i}] BMD kept (AtlusScriptCompiler not available)", 6)
            else:
                log(f"      BVP[{i}] BMD kept (bmd_decompile.py not found in pipeline/)", 6)

    return result

def main():
    if len(sys.argv) < 2:
        print("Usage: bvp_extract.py <file.bvp> [out_dir]")
        sys.exit(1)

    src = sys.argv[1].strip().strip('"')
    if not os.path.isfile(src):
        print(f"ERROR: not found: {src}")
        sys.exit(1)

    out_dir = (sys.argv[2] if len(sys.argv) >= 3
               else os.path.join(os.path.dirname(os.path.abspath(src)),
                                 os.path.splitext(os.path.basename(src))[0]))

    bmd_mod = _load_bmd_module()
    compiler = None
    if bmd_mod:
        _here  = os.path.dirname(os.path.abspath(__file__))
        _root  = os.path.dirname(_here)
        _tools = os.path.join(_root, "tools")
        compiler = bmd_mod.find_atlus_script_compiler(_tools)
        if not compiler:
            print("AtlusScriptCompiler not found -- BMD entries will be kept raw.")

    def cli_log(msg, pair=2):
        print(msg)

    print(f"Input  : {src}")
    print(f"Output : {out_dir}")
    print(f"Compiler: {compiler or 'NOT FOUND'}")
    print()

    res = process_bvp(src, out_dir, compiler, log=cli_log)
    print(f"\nDone. {res['extracted']}/{res['total']} extracted, "
          f"{res['decompiled']} decompiled to MSG.")


if __name__ == "__main__":
    main()
