import os
import sys
import shutil
import subprocess
import urllib.request
import zipfile

_AST_API_URL = "https://api.github.com/repos/tge-was-taken/Atlus-Script-Tools/releases/latest"

# Try these in order until one produces output
_LIBRARY_ATTEMPTS = [
    ("p3f", "P3"),
    ("p3p", "P3"),
    ("p3",  "P3"),
]

def find_atlus_script_compiler(tools_dir: str) -> str | None:
    # Locate AtlusScriptCompiler.exe in tools or PATH
    # Check tools/AtlusScriptTools/
    ast_dir = os.path.join(tools_dir, "AtlusScriptTools")
    for name in ("AtlusScriptCompiler.exe", "AtlusScriptCompiler"):
        full = os.path.join(ast_dir, name)
        if os.path.isfile(full):
            return full
    # PATH fallback
    found = shutil.which("AtlusScriptCompiler")
    if found:
        return found
    return None


def install_atlus_script_compiler(tools_dir: str, log=print) -> tuple[bool, str]:
    # Download latest AtlusScriptCompiler release from GitHub
    import json

    ast_dir = os.path.join(tools_dir, "AtlusScriptTools")
    os.makedirs(ast_dir, exist_ok=True)

    log("Fetching AtlusScriptTools release info...")
    try:
        req = urllib.request.Request(
            _AST_API_URL,
            headers={"User-Agent": "PUTC/1.0", "Accept": "application/vnd.github+json"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            info = json.loads(resp.read())
    except Exception as e:
        return False, f"GitHub API error: {e}"

    # Find a Windows zip asset
    asset_url = None
    for asset in info.get("assets", []):
        name = asset.get("name", "").lower()
        if name.endswith(".zip") and ("win" in name or "release" in name or "tools" in name):
            asset_url = asset["browser_download_url"]
            break
    # orrr just grab the first zip
    if not asset_url:
        for asset in info.get("assets", []):
            if asset.get("name", "").lower().endswith(".zip"):
                asset_url = asset["browser_download_url"]
                break

    if not asset_url:
        return False, "No zip release asset found on GitHub"

    zip_path = os.path.join(tools_dir, "ast_dl.zip")
    log(f"Downloading {os.path.basename(asset_url)}...")
    try:
        urllib.request.urlretrieve(asset_url, zip_path)
    except Exception as e:
        return False, f"Download failed: {e}"

    log("Extracting...")
    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(ast_dir)
        os.remove(zip_path)
    except Exception as e:
        return False, f"Extraction failed: {e}"

    exe = find_atlus_script_compiler(tools_dir)
    if exe:
        return True, f"Installed to {ast_dir}"
    return False, f"Extracted but AtlusScriptCompiler.exe not found in {ast_dir}"


# main decompilation
def decompile_bmd(bmd_path: str, out_dir: str,
                  compiler: str,
                  log=print) -> tuple[bool, str]:
    base     = os.path.splitext(os.path.basename(bmd_path))[0]
    out_path = os.path.join(out_dir, base + ".msg")

    for library, encoding in _LIBRARY_ATTEMPTS:
        cmd = [
            compiler,
            bmd_path,
            "-Decompile",
            "-Library", library,
            "-Encoding", encoding,
            "-Out", out_path,
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=60)
            if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
                os.remove(bmd_path)
                return True, out_path
        except subprocess.TimeoutExpired:
            return False, "AtlusScriptCompiler timed out"
        except Exception as e:
            return False, str(e)

    err = (r.stderr.decode(errors="ignore") +
           r.stdout.decode(errors="ignore")).strip()
    return False, f"rc={r.returncode}: {err[-200:]}"


def decompile_bf(bf_path: str, out_dir: str,
                 compiler: str,
                 log=print) -> tuple[bool, str]:
    base     = os.path.splitext(os.path.basename(bf_path))[0]
    out_path = os.path.join(out_dir, base + ".flow")

    for library, encoding in _LIBRARY_ATTEMPTS:
        cmd = [
            compiler,
            bf_path,
            "-Decompile",
            "-Library", library,
            "-Encoding", encoding,
            "-Out", out_path,
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=60)
            if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
                os.remove(bf_path)
                return True, out_path
        except subprocess.TimeoutExpired:
            return False, "AtlusScriptCompiler timed out"
        except Exception as e:
            return False, str(e)

    err = (r.stderr.decode(errors="ignore") +
           r.stdout.decode(errors="ignore")).strip()
    return False, f"rc={r.returncode}: {err[-200:]}"


def process_script(src_path: str, out_dir: str,
                   compiler: str,
                   log=print) -> tuple[bool, str]:
    ext = os.path.splitext(src_path)[1].lower()
    if ext == ".bmd":
        ok, result = decompile_bmd(src_path, out_dir, compiler, log)
    elif ext == ".bf":
        ok, result = decompile_bf(src_path, out_dir, compiler, log)
    else:
        return False, f"Unknown script extension: {ext}"

    if ok:
        return True, os.path.basename(result)
    return False, result

def main():
    if len(sys.argv) >= 2:
        src = sys.argv[1].strip().strip('"')
    else:
        src = input("BMD or BF file path: ").strip().strip('"')

    if not os.path.isfile(src):
        print(f"ERROR: not found: {src}")
        sys.exit(1)

    out_dir = (sys.argv[2] if len(sys.argv) >= 3
               else os.path.dirname(os.path.abspath(src)))

    _here     = os.path.dirname(os.path.abspath(__file__))  # pipeline/
    _root     = os.path.dirname(_here)                       # repo root
    tools_dir = os.path.join(_root, "tools")

    compiler = find_atlus_script_compiler(tools_dir)
    if not compiler:
        print("AtlusScriptCompiler.exe not found -- attempting download...")
        ok, msg = install_atlus_script_compiler(tools_dir)
        print(f"{'OK' if ok else 'FAILED'}: {msg}")
        if not ok:
            sys.exit(1)
        compiler = find_atlus_script_compiler(tools_dir)

    print(f"Compiler : {compiler}")
    print(f"Input    : {src}")
    print(f"Out dir  : {out_dir}")
    print()

    ok, result = process_script(src, out_dir, compiler)
    if ok:
        print(f"OK -> {result}")
    else:
        print(f"FAILED: {result}")
        sys.exit(1)


if __name__ == "__main__":
    main()
