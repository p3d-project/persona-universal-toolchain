import sys
import subprocess

if sys.platform == "win32":
    try:
        import curses
    except ModuleNotFoundError:
        print("Installing windows-curses...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "windows-curses"])
        print("Done. Restarting...")
        subprocess.check_call([sys.executable] + sys.argv)
        sys.exit(0)

import curses
import os
import shutil
import threading
import queue
import urllib.request
import zipfile
import importlib.util as _epl_ilu

def _load_pipeline_module(name: str):
    _here = os.path.dirname(os.path.abspath(__file__))
    _path = os.path.join(_here, "pipeline", f"{name}.py")
    if not os.path.isfile(_path):
        return None
    spec = _epl_ilu.spec_from_file_location(name, _path)
    mod  = _epl_ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

_tmx = _load_pipeline_module("tmx_to_png")
_epl = _load_pipeline_module("epl_extract")
_bmd = _load_pipeline_module("bmd_decompile")
_spr = _load_pipeline_module("spr_extract")
_bvp = _load_pipeline_module("bvp_extract")
_amd = _load_pipeline_module("amd_extract")

import os as _os, importlib.util as _ilu
_here = _os.path.dirname(_os.path.abspath(__file__))
_cfg_path = _os.path.join(_here, "config.py")
if not _os.path.isfile(_cfg_path):
    _cfg_path = _os.path.join(_here, "config.example.py")
_spec = _ilu.spec_from_file_location("config", _cfg_path)
_cfg  = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_cfg)
INPUT_DIR     = _cfg.INPUT_DIR
OUT_DIR       = _cfg.OUT_DIR
TOOLS_DIR     = _cfg.TOOLS_DIR
NOESIS_PATH   = _cfg.NOESIS_PATH
THREADS       = _cfg.THREADS
RMDTOGLB_PATH = getattr(_cfg, "RMDTOGLB_PATH", "")
RECURSIVE     = getattr(_cfg, "RECURSIVE", False)

_runtime_threads = THREADS

def get_threads() -> int:
    return _runtime_threads

def set_threads(n: int):
    global _runtime_threads
    _runtime_threads = max(1, min(64, n))

import re as _re

def save_config(**kwargs):
    try:
        _here = os.path.dirname(os.path.abspath(__file__))
        _save_path = os.path.join(_here, "config.py")
        if not os.path.isfile(_save_path):
            import shutil as _shutil
            _shutil.copy2(_cfg_path, _save_path)
        with open(_save_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        written = set()
        new_lines = []
        for line in lines:
            replaced = False
            for key, val in kwargs.items():
                if _re.match(rf"^\s*{key}\s*=", line):
                    if isinstance(val, bool):
                        new_lines.append(f"{key:<14}= {val}\n")
                    elif isinstance(val, int):
                        new_lines.append(f"{key:<14}= {val}\n")
                    else:
                        new_lines.append(f"{key:<14}= {val!r}\n")
                    written.add(key)
                    replaced = True
                    break
            if not replaced:
                new_lines.append(line)
        for key, val in kwargs.items():
            if key not in written:
                if isinstance(val, bool):
                    new_lines.append(f"{key:<14}= {val}\n")
                elif isinstance(val, int):
                    new_lines.append(f"{key:<14}= {val}\n")
                else:
                    new_lines.append(f"{key:<14}= {val!r}\n")
        with open(_save_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
    except Exception:
        pass

AUDIO_EXTS = {".adx", ".acx", ".vag", ".hca", ".wav", ".flac"}
VIDEO_EXTS = {".sfd", ".pmf", ".pmsf"}

PAK_NAME_LEN = 252
PAK_ALIGN    = 64

MAGIC_TO_EXT = {
    b"OMG.":             ".gmo",   # P3P   - Generic Model Object
    b"\x00TMX":          ".tmx",   # P3/P4 - Bitmap Image Format
    b"SPR\x00":          ".spr",   # P3/P4 - TMX Sprite Container
    b"PSE\x00":          ".pse",   # P3P   - Sound Archive (battle voices)
    b"MSE\x00":          ".mse",   # P3P   - Sound Archive (battle voices)
    b"BED\x00":          ".bed",   # P3P   - Battle Event Data
    b"EPL\x00":          ".epl",   # P3/P4 - General Resource Package
    b"FLWC":             ".bf",    # P3/P4 - Flow Script (compiled)
    b"FLWS":             ".bf",    # P3/P4 - Flow Script (source)
    b"CPK ":             ".cpk",   # P3/P4 - CRI CPK Archive
    b"BVP\x00":          ".bvp",   # P3/P4 - Battle Voice Package
    b"CHNK":             ".amd",   # P3/P4 - Vita Resource Container
    b"RIFF":             ".wav",   # P3/P4 - RIFF/WAV Audio
    b"VAGp":             ".vag",   # P3/P4 - PS2 VAG Audio
    b"ADX\x00":          ".adx",   # P3/P4 - CRI ADX Audio
    b"\x80\x00":         ".adx",   # P3/P4 - CRI ADX Audio (ACX container variant)
    b"HCA\x00":          ".hca",   # P3/P4 - CRI HCA Audio
    b"fLaC":             ".flac",  # P3/P4 - FLAC Audio
    b"PMF\x00":          ".pmf",   # P3P   - PSP Movie Format
    b"MTSF":             ".pmsf",  # P3P   - Movie Sound Format
    b"SOFD":             ".sfd",   # P3/P4 - CRI Sofdec Video
    b"SFHD":             ".sfd",   # P3/P4 - CRI Sofdec Video (header variant)
    b"\x10\x00\x00\x00": ".rws",   # P3/P4 - RW Clump (character model)
    b"\x1B\x00\x00\x00": ".rws",   # P3/P4 - RW World (environment)
    b"\x16\x00\x00\x00": ".rws",   # P3/P4 - RW UVAnimDict
}

NOESIS_ZIP_URL = "https://www.richwhitehouse.com/filemirror/noesisv4474.zip"
VGMSTREAM_URL_WIN   = "https://github.com/vgmstream/vgmstream/releases/latest/download/vgmstream-win64.zip"
VGMSTREAM_URL_LINUX = "https://github.com/vgmstream/vgmstream/releases/latest/download/vgmstream-linux-cli.zip"

def to_native(path: str) -> str:
    if sys.platform == "win32":
        return path
    p = path.replace("\\", "/")
    if len(p) >= 2 and p[1] == ":":
        p = f"/mnt/{p[0].lower()}" + p[2:]
    return p

def find_vgmstream() -> str | None:
    if shutil.which("vgmstream-cli"):
        return "vgmstream-cli"
    tools = to_native(TOOLS_DIR)
    for name in ("vgmstream-cli.exe", "vgmstream-cli", "test.exe"):
        full = os.path.join(tools, name)
        if os.path.isfile(full):
            return full
    return None

def find_ffmpeg() -> str | None:
    return shutil.which("ffmpeg")

def _noesis_temp_dir() -> str:
    import tempfile
    return os.path.join(tempfile.gettempdir(), "p3extractor_noesis")

def find_noesis() -> str | None:
    if NOESIS_PATH:
        p = to_native(NOESIS_PATH)
        if os.path.isfile(p):
            return p
    for name in ("Noesis64.exe", "Noesis.exe", "noesis64", "noesis"):
        found = shutil.which(name)
        if found:
            return found
    tmp = _noesis_temp_dir()
    for name in ("Noesis64.exe", "Noesis.exe"):
        full = os.path.join(tmp, name)
        if os.path.isfile(full):
            return full
    return None

def install_vgmstream(log) -> tuple[bool, str]:
    tools = to_native(TOOLS_DIR)
    os.makedirs(tools, exist_ok=True)
    is_win = sys.platform == "win32"
    if not is_win and shutil.which("apt-get"):
        try:
            log("Running apt-get install vgmstream...")
            subprocess.run(["sudo", "apt-get", "install", "-y", "vgmstream"],
                           check=True, capture_output=True)
            if shutil.which("vgmstream-cli"):
                return True, "Installed via apt"
        except Exception:
            pass
    url = VGMSTREAM_URL_WIN if is_win else VGMSTREAM_URL_LINUX
    zip_path = os.path.join(tools, "vgmstream.zip")
    log("Downloading vgmstream...")
    try:
        urllib.request.urlretrieve(url, zip_path)
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(tools)
        os.remove(zip_path)
    except Exception as e:
        return False, f"Download failed: {e}"
    return (True, f"Installed to {tools}") if find_vgmstream() else \
           (False, "Extracted but could not find binary")

def install_ffmpeg(log) -> tuple[bool, str]:
    if sys.platform == "win32":
        for pkg, cmd in [("winget", ["winget", "install", "ffmpeg", "--silent"]),
                         ("choco",  ["choco", "install", "ffmpeg", "-y"])]:
            if shutil.which(pkg):
                try:
                    log(f"Running {pkg} install ffmpeg...")
                    subprocess.run(cmd, check=True, capture_output=True)
                    if shutil.which("ffmpeg"):
                        return True, f"Installed via {pkg}"
                except Exception:
                    pass
        return False, "Could not auto-install. Get ffmpeg from https://ffmpeg.org"
    if shutil.which("apt-get"):
        try:
            log("Running apt-get install ffmpeg...")
            subprocess.run(["sudo", "apt-get", "install", "-y", "ffmpeg"],
                           check=True, capture_output=True)
            if shutil.which("ffmpeg"):
                return True, "Installed via apt"
        except Exception:
            pass
    return False, "Could not auto-install ffmpeg"

def install_noesis(log) -> tuple[bool, str]:
    import tempfile
    tmp = _noesis_temp_dir()
    os.makedirs(tmp, exist_ok=True)
    zip_path = os.path.join(tempfile.gettempdir(), "noesis_dl.zip")
    log("Downloading Noesis...")
    try:
        req = urllib.request.Request(
            NOESIS_ZIP_URL,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                   "AppleWebKit/537.36 Chrome/124.0 Safari/537.36"}
        )
        with urllib.request.urlopen(req) as resp, open(zip_path, "wb") as out:
            out.write(resp.read())
        log("Extracting...")
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(tmp)
        os.remove(zip_path)
    except Exception as e:
        return False, f"Failed: {e} -- download manually from richwhitehouse.com and set NOESIS_PATH"
    return (True, f"Installed to temp ({tmp}) -- cleared on reboot") if find_noesis() else \
           (False, "Extracted but could not find Noesis exe -- set NOESIS_PATH manually")

def detect_extension(data: bytes, fallback_name: str) -> str:
    _fallback_ext = os.path.splitext(fallback_name)[1].lower()
    _MODEL_EXTS = {".rmd", ".rws", ".gmo"}
    for magic, ext in MAGIC_TO_EXT.items():
        if data[:len(magic)] == magic:
            if _fallback_ext in _MODEL_EXTS and ext == ".rws":
                return _fallback_ext
            return ext
    return _fallback_ext if _fallback_ext else ".bin"

ARCHIVE_EXTS = {".pac", ".bin", ".fpc"}
LOOSE_EXTS   = {
    ".rmd", ".rws", ".gmo", ".tmx", ".epl", ".cpk",
    ".bmd", ".bf",
    ".adx", ".acx", ".vag", ".hca", ".wav", ".flac",
    ".sfd", ".pmf", ".pmsf",
    ".spr", ".bvp", ".amd",
}

def _collect_input_files(
    pac_dir: str, recursive: bool
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    archives: list[tuple[str, str]] = []
    loose:    list[tuple[str, str]] = []
    walk = os.walk(pac_dir) if recursive else [(pac_dir, [], sorted(os.listdir(pac_dir)))]
    for root, _dirs, files in walk:
        for fname in sorted(files):
            ext = os.path.splitext(fname)[1].lower()
            abs_path = os.path.join(root, fname)
            rel = os.path.relpath(abs_path, pac_dir)
            if ext in ARCHIVE_EXTS:
                archives.append((rel, abs_path))
            elif ext in LOOSE_EXTS:
                loose.append((rel, abs_path))
    return archives, loose

def _pak_align(pos: int) -> int:
    return (pos + PAK_ALIGN - 1) & ~(PAK_ALIGN - 1)

def process_pac(pac_path: str, out_dir: str) -> tuple[int, list[str]]:
    with open(pac_path, "rb") as f:
        data = f.read()
    pos = 0
    extracted = []
    seen: dict[str, int] = {}
    while pos + PAK_NAME_LEN + 4 <= len(data):
        raw_name = data[pos:pos + PAK_NAME_LEN].split(b"\x00")[0].decode("ascii", errors="ignore").strip()
        pos += PAK_NAME_LEN
        data_len = int.from_bytes(data[pos:pos + 4], "little", signed=True)
        pos += 4
        if data_len <= 0:
            break
        if pos + data_len > len(data):
            break
        file_data = data[pos:pos + data_len]
        pos = _pak_align(pos + data_len)
        ext  = detect_extension(file_data, raw_name)
        base = os.path.splitext(os.path.basename(raw_name))[0] if raw_name else \
               os.path.splitext(os.path.basename(pac_path))[0]
        key = (base + ext).lower()
        if key in seen:
            seen[key] += 1
            out_name = f"{base}_{seen[key]}{ext}"
        else:
            seen[key] = 0
            out_name = base + ext
        with open(os.path.join(out_dir, out_name), "wb") as wf:
            wf.write(file_data)
        extracted.append(out_name)
    return len(extracted), extracted

def convert_audio_to_mp3(src: str, dst: str, vgm: str, ffmpeg: str) -> tuple[bool, str]:
    wav_path = src + ".tmp.wav"
    try:
        r = subprocess.run([vgm, src, "-o", wav_path, "-i"], capture_output=True)
        if r.returncode != 0 or not os.path.isfile(wav_path):
            return False, f"vgmstream failed: {r.stderr.decode(errors='ignore')[-80:]}"
        r2 = subprocess.run([ffmpeg, "-y", "-i", wav_path, "-q:a", "2", dst],
                            capture_output=True)
        if r2.returncode != 0:
            return False, f"ffmpeg failed: {r2.stderr.decode(errors='ignore')[-80:]}"
        return True, "ok"
    finally:
        if os.path.isfile(wav_path):
            os.remove(wav_path)

def convert_video_to_mp4(src: str, dst: str, ffmpeg: str) -> tuple[bool, str]:
    r = subprocess.run([ffmpeg, "-y", "-i", src, "-c:v", "libx264", "-c:a", "aac", dst],
                       capture_output=True)
    if r.returncode != 0:
        return False, r.stderr.decode(errors="ignore")[-80:]
    return True, "ok"

def _rmdtoglb_dir() -> str:
    return os.path.join(to_native(TOOLS_DIR), "rmdtoglb")

def find_rmdtoglb() -> str | None:
    if RMDTOGLB_PATH:
        p = to_native(RMDTOGLB_PATH)
        if os.path.isfile(p):
            return p
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    built = os.path.join(_script_dir, "bin", "Debug", "net472", "RmdToGlb.exe")
    cs_src = os.path.join(_script_dir, "RmdToGlb_Program.cs")
    if os.path.isfile(built) and os.path.isfile(cs_src):
        if os.path.getmtime(cs_src) > os.path.getmtime(built):
            _rebuild_rmdtoglb(_script_dir)
    if os.path.isfile(built):
        return built
    for name in ("RmdToGlb.exe", "RmdToGlb"):
        full = os.path.join(_rmdtoglb_dir(), name)
        if os.path.isfile(full):
            return full
        found = shutil.which(name)
        if found:
            return found
    return None

def _rebuild_rmdtoglb(script_dir: str) -> bool:
    dotnet = shutil.which("dotnet")
    if not dotnet:
        return False
    csproj = os.path.join(script_dir, "RmdToGlb.csproj")
    if not os.path.isfile(csproj):
        return False
    try:
        r = subprocess.run(
            [dotnet, "build", csproj, "-c", "Debug", "--nologo", "-v", "q"],
            capture_output=True, timeout=60, cwd=script_dir
        )
        return r.returncode == 0
    except Exception:
        return False

def convert_rmd_to_glb(rmd_path: str, out_dir: str, rmdtoglb: str) -> tuple[bool, str, list[str]]:
    try:
        r = subprocess.run(
            [rmdtoglb, rmd_path, out_dir],
            capture_output=True, timeout=120
        )
        if r.returncode != 0:
            stderr = r.stderr.decode(errors='ignore').strip()
            stdout = r.stdout.decode(errors='ignore').strip()
            detail = stderr or stdout
            if r.returncode == 0xE0434352:
                return False, (f"AmicitiaLibrary cannot parse this file "
                               f"(unsupported RenderWare chunk). "
                               f"File kept as-is: {os.path.basename(rmd_path)}"), []
            return False, f"RmdToGlb rc={r.returncode} [{os.path.basename(rmd_path)}]: {detail[-600:]}", []

        base    = os.path.splitext(os.path.basename(rmd_path))[0]
        outputs = [f for f in os.listdir(out_dir)
                   if f.startswith(base) and f.lower().endswith((".glb", ".png"))]
        return True, "ok", outputs
    except subprocess.TimeoutExpired:
        return False, "RmdToGlb timed out", []
    except Exception as e:
        return False, str(e), []

def convert_gmo_to_fbx(gmo_path: str, out_dir: str, noesis: str,
                        vgm: str | None, ffm: str | None) -> tuple[bool, str, list[str]]:
    base      = os.path.splitext(os.path.basename(gmo_path))[0]
    model_dir = out_dir
    os.makedirs(model_dir, exist_ok=True)

    fbx_path = os.path.join(model_dir, base + ".fbx")
    r = subprocess.run([noesis, "?cmode", gmo_path, fbx_path, "-cf", "-gmokeeptexnames"],
                       capture_output=True, timeout=120)
    found_fbx = None
    if os.path.isfile(fbx_path):
        found_fbx = fbx_path
    else:
        for f in os.listdir(model_dir):
            if f.lower().endswith(".fbx"):
                found_fbx = os.path.join(model_dir, f)
                break
    if not found_fbx:
        stderr = r.stderr.decode(errors="ignore")[-200:]
        stdout = r.stdout.decode(errors="ignore")[-200:]
        return False, f"Noesis rc={r.returncode}: {stdout} {stderr}".strip(), []

    outputs = [base + ".fbx"]
    for f in os.listdir(model_dir):
        if f.lower().endswith((".png", ".tga", ".dds", ".tm2", ".tmx")):
            outputs.append(f)

    for ext in (".pse", ".mse", ".vag"):
        sibling = os.path.join(os.path.dirname(gmo_path), base + ext)
        if os.path.isfile(sibling):
            if vgm and ffm:
                mp3_path = os.path.join(model_dir, base + ".mp3")
                ok, _ = convert_audio_to_mp3(sibling, mp3_path, vgm, ffm)
                if ok:
                    outputs.append(base + ".mp3")
            else:
                dst = os.path.join(model_dir, base + ext)
                shutil.copy2(sibling, dst)
                outputs.append(base + ext)
            break
    return True, "ok", outputs

def init_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(2, curses.COLOR_WHITE, -1)
    curses.init_pair(3, curses.COLOR_CYAN,  -1)
    curses.init_pair(4, curses.COLOR_GREEN, -1)
    curses.init_pair(5, curses.COLOR_RED,   -1)
    curses.init_pair(6, curses.COLOR_YELLOW,-1)

def draw_box(win, y, x, h, w, title=""):
    try:
        win.attron(curses.color_pair(3))
        win.addch(y, x, curses.ACS_ULCORNER)
        win.addch(y, x+w-1, curses.ACS_URCORNER)
        win.addch(y+h-1, x, curses.ACS_LLCORNER)
        win.addch(y+h-1, x+w-1, curses.ACS_LRCORNER)
        for i in range(1, w-1):
            win.addch(y,     x+i, curses.ACS_HLINE)
            win.addch(y+h-1, x+i, curses.ACS_HLINE)
        for i in range(1, h-1):
            win.addch(y+i, x,     curses.ACS_VLINE)
            win.addch(y+i, x+w-1, curses.ACS_VLINE)
        if title:
            win.addstr(y, x+2, f" {title} ", curses.color_pair(3) | curses.A_BOLD)
        win.attroff(curses.color_pair(3))
    except curses.error:
        pass

def safe_addstr(win, y, x, text, attr=0, max_w=None):
    try:
        h, w = win.getmaxyx()
        if y >= h or x >= w:
            return
        if max_w is None:
            max_w = w - x - 1
        win.addstr(y, x, text[:max_w], attr)
    except curses.error:
        pass

_MENU_LEFT  = -10   # sentinel: left arrow on a lr_row
_MENU_RIGHT = -11   # sentinel: right arrow on a lr_row

def arrow_menu(win, y, x, items, selected=0, item_width=36, lr_rows=None):
    curses.curs_set(0)
    if lr_rows is None:
        lr_rows = set()

    def draw():
        for i, item in enumerate(items):
            label = f"  {item}  ".ljust(item_width)
            if i == selected:
                safe_addstr(win, y+i, x, f" > {label}", curses.color_pair(1) | curses.A_BOLD)
            else:
                safe_addstr(win, y+i, x, f"   {label}", curses.color_pair(2))
        win.refresh()

    while True:
        draw()
        k = win.getch()
        if k == curses.KEY_RESIZE:
            win.clear()
            win.refresh()
        elif k == curses.KEY_UP:
            selected = (selected - 1) % len(items)
        elif k == curses.KEY_DOWN:
            selected = (selected + 1) % len(items)
        elif k == curses.KEY_LEFT and selected in lr_rows:
            return _MENU_LEFT
        elif k == curses.KEY_RIGHT and selected in lr_rows:
            return _MENU_RIGHT
        elif k in (curses.KEY_ENTER, ord("\n"), ord("\r"), ord(" ")):
            return selected
        elif k == 27:
            return -1

def make_progress_screen(stdscr, title: str):
    stdscr.clear()
    h, w = stdscr.getmaxyx()
    draw_box(stdscr, 0, 0, h-1, w, title)
    log_lines = []
    error_log = []
    LOG_Y = 7
    stats = {"done": 0, "total": 0, "converted": 0, "errors": 0}
    lock = threading.Lock()
    _title = title

    def redraw():
        h, w = stdscr.getmaxyx()
        log_h = h - LOG_Y - 3
        bar_w = w - 22
        stdscr.clear()
        draw_box(stdscr, 0, 0, h-1, w, _title)
        done  = stats["done"]
        total = stats["total"] or 1
        pct   = int(100 * done / total)
        filled = max(0, int(bar_w * done / total))
        safe_addstr(stdscr, 2, 2,
            f"Files: {done}/{stats['total']}  Converted: {stats['converted']}  Errors: {stats['errors']}   ",
            curses.color_pair(3) | curses.A_BOLD)
        safe_addstr(stdscr, 3, 2, f"{pct:3d}% ", curses.color_pair(3))
        safe_addstr(stdscr, 3, 7, "#" * filled,           curses.color_pair(1))
        safe_addstr(stdscr, 3, 7+filled, "-"*(bar_w-filled), curses.color_pair(2))
        visible = log_lines[-log_h:]
        for i, (line, pair) in enumerate(visible):
            safe_addstr(stdscr, LOG_Y+i, 2, line.ljust(w-4)[:w-4], curses.color_pair(pair))
        stdscr.refresh()

    def log(msg, pair=2):
        import datetime
        with lock:
            log_lines.append((msg, pair))
            if pair == 5:
                ts = datetime.datetime.now().strftime("%H:%M:%S")
                error_log.append(f"[{ts}] {msg}")
            redraw()

    def bump(key, n=1):
        with lock:
            stats[key] += n
            redraw()

    return stats, log, bump, redraw, error_log

def screen_ensure_tools(stdscr):
    ast = _bmd.find_atlus_script_compiler(to_native(TOOLS_DIR)) if _bmd else True
    if find_vgmstream() and find_ffmpeg() and find_noesis() and find_rmdtoglb() and ast:
        return

    stdscr.clear()
    h, w = stdscr.getmaxyx()
    draw_box(stdscr, 0, 0, h-1, w, "SETTING UP TOOLS")
    row = 2

    def log(msg, pair=2):
        nonlocal row
        safe_addstr(stdscr, row, 2, msg[:w-4], curses.color_pair(pair))
        row += 1
        stdscr.refresh()

    if not find_vgmstream():
        log("Installing vgmstream...", 6)
        ok, msg = install_vgmstream(lambda m: log(f"  {m}", 6))
        log(f"  vgmstream: {'OK' if ok else 'FAILED -- ' + msg}", 4 if ok else 5)

    if not find_ffmpeg():
        log("Installing ffmpeg...", 6)
        ok, msg = install_ffmpeg(lambda m: log(f"  {m}", 6))
        log(f"  ffmpeg: {'OK' if ok else 'FAILED -- ' + msg}", 4 if ok else 5)

    if not find_noesis():
        log("Installing Noesis...", 6)
        ok, msg = install_noesis(lambda m: log(f"  {m}", 6))
        log(f"  Noesis: {'OK' if ok else 'FAILED -- ' + msg}", 4 if ok else 5)

    if _bmd and not _bmd.find_atlus_script_compiler(to_native(TOOLS_DIR)):
        log("Installing AtlusScriptCompiler...", 6)
        ok, msg = _bmd.install_atlus_script_compiler(
            to_native(TOOLS_DIR), log=lambda m: log(f"  {m}", 6))
        log(f"  AtlusScript: {'OK' if ok else 'FAILED -- ' + msg}", 4 if ok else 5)

    log("", 2)
    log("Done. Press any key.", 2)
    stdscr.getch()

def screen_run(stdscr, recursive: bool = False):
    pac_dir = to_native(INPUT_DIR)
    out_dir = to_native(OUT_DIR)

    stdscr.clear()
    h, w = stdscr.getmaxyx()
    draw_box(stdscr, 0, 0, h-1, w, "EXTRACTING")

    if not os.path.isdir(pac_dir):
        safe_addstr(stdscr, 2, 2, "ERROR: PAC folder not found:", curses.color_pair(5)|curses.A_BOLD)
        safe_addstr(stdscr, 3, 2, pac_dir, curses.color_pair(2))
        safe_addstr(stdscr, 5, 2, "Press any key.", curses.color_pair(2))
        stdscr.refresh(); stdscr.getch(); return

    os.makedirs(out_dir, exist_ok=True)
    pac_entries, loose_entries = _collect_input_files(pac_dir, recursive)
    if not pac_entries and not loose_entries:
        safe_addstr(stdscr, 2, 2,
            f"No supported files found {'(recursive)' if recursive else ''}.",
            curses.color_pair(5))
        safe_addstr(stdscr, 3, 2, pac_dir, curses.color_pair(2))
        safe_addstr(stdscr, 4, 2, "Press any key.", curses.color_pair(2))
        stdscr.refresh(); stdscr.getch(); return

    vgm          = find_vgmstream()
    ffm          = find_ffmpeg()
    rmdtoglb     = find_rmdtoglb()
    noesis       = find_noesis()
    ast_compiler = _bmd.find_atlus_script_compiler(to_native(TOOLS_DIR)) if _bmd else None
    n_threads    = get_threads()

    title = (f"EXTRACTING  [{n_threads}T{'  recursive' if recursive else ''}]")
    stats, log, bump, redraw, error_log = make_progress_screen(stdscr, title)
    stats["total"] = len(pac_entries) + len(loose_entries)
    redraw()

    work_q: queue.Queue = queue.Queue()
    for entry in pac_entries:
        work_q.put(("archive", entry))
    for entry in loose_entries:
        work_q.put(("loose", entry))

    def _process_file(out_name: str, src: str, file_out_dir: str):
        ext = os.path.splitext(out_name)[1].lower()
        log(f"  OK  {out_name}", 4)
        if ext in (".rmd", ".rws") and rmdtoglb:
            if not os.path.isfile(src):
                log(f"      rmd/rws MISSING before convert: {src}", 5)
                bump("errors")
            else:
                ok2, msg, outputs = convert_rmd_to_glb(src, file_out_dir, rmdtoglb)
                if ok2:
                    if outputs and os.path.isfile(src):
                        os.remove(src)
                    for o in outputs:
                        log(f"      rmd/rws -> {o}", 4)
                    bump("converted")
                else:
                    is_parse_fail = ("unsupported RenderWare chunk" in msg
                                     or "RmdScene parse failed" in msg
                                     or "rc=3762504530" in msg
                                     or "rc=-532459726" in msg)
                    pair = 6 if is_parse_fail else 5
                    log(f"      rmd/rws kept (AmicitiaLibrary parse fail) [{out_name}]" if is_parse_fail
                        else f"      rmd/rws failed [{out_name}]: {msg}", pair)
                    if not is_parse_fail:
                        bump("errors")
        elif ext in (".rmd", ".rws") and not rmdtoglb:
            log(f"      rmd/rws SKIP (RmdToGlb.exe not found)", 6)
        elif ext == ".gmo" and noesis:
            ok2, msg, outputs = convert_gmo_to_fbx(src, file_out_dir, noesis, vgm, ffm)
            if ok2:
                os.remove(src)
                for o in outputs:
                    log(f"      GMO -> {o}", 4)
                bump("converted")
            else:
                log(f"      GMO failed [{out_name}]: {msg}", 5)
                bump("errors")
        elif ext == ".gmo" and not noesis:
            log(f"      GMO SKIP (Noesis not found -- run Check/Install Tools)", 6)
        elif ext in AUDIO_EXTS and vgm and ffm:
            mp3 = os.path.join(file_out_dir, os.path.splitext(out_name)[0] + ".mp3")
            ok2, msg = convert_audio_to_mp3(src, mp3, vgm, ffm)
            if ok2:
                os.remove(src)
                log(f"      audio -> {os.path.basename(mp3)}", 4)
                bump("converted")
            else:
                log(f"      audio failed: {msg}", 5)
        elif ext in VIDEO_EXTS and ffm:
            mp4 = os.path.join(file_out_dir, os.path.splitext(out_name)[0] + ".mp4")
            ok2, msg = convert_video_to_mp4(src, mp4, ffm)
            if ok2:
                os.remove(src)
                log(f"      video -> {os.path.basename(mp4)}", 4)
                bump("converted")
            else:
                log(f"      video failed: {msg}", 5)
        elif ext == ".epl" and _epl:
            epl_stem    = os.path.splitext(out_name)[0]
            epl_out_dir = os.path.join(file_out_dir, epl_stem)
            res = _epl.process_epl(src, epl_out_dir, rmdtoglb=rmdtoglb, noesis=noesis, log=log)
            total_out = res["rmd_ok"] + res["tmx_ok"]
            if total_out > 0:
                os.remove(src)
                bump("converted", total_out)
            if res["rmd_total"] == 0 and res["tmx_total"] == 0:
                log(f"      epl: no RMD/TMX found inside [{out_name}]", 6)
        elif ext == ".epl" and not _epl:
            log(f"      epl SKIP (epl_extract.py not found in pipeline/)", 6)
        elif ext == ".cpk":
            log(f"      cpk SKIP (cpk_extract.py not found in pipeline/)", 6)
        elif ext in (".bmd", ".bf") and _bmd and ast_compiler:
            ok2, result = _bmd.process_script(src, file_out_dir, ast_compiler, log=log)
            if ok2:
                log(f"      {ext[1:].upper()} -> {result}", 4)
                bump("converted")
            else:
                log(f"      {ext[1:].upper()} failed [{out_name}]: {result}", 5)
                bump("errors")
        elif ext in (".bmd", ".bf") and _bmd and not ast_compiler:
            log(f"      {ext[1:].upper()} SKIP (AtlusScriptCompiler not found -- run Check/Install Tools)", 6)
        elif ext in (".bmd", ".bf") and not _bmd:
            log(f"      {ext[1:].upper()} SKIP (bmd_decompile.py not found in pipeline/)", 6)
        elif ext == ".tmx":
            if _tmx:
                png = os.path.join(file_out_dir, os.path.splitext(out_name)[0] + ".png")
                ok2, msg = _tmx.convert(src, png)
                if ok2:
                    os.remove(src)
                    log(f"      TMX -> {os.path.basename(png)}", 4)
                    bump("converted")
                else:
                    log(f"      TMX failed [{out_name}]: {msg}", 5)
                    bump("errors")
            else:
                log(f"      TMX SKIP (tmx_to_png.py not found in pipeline/)", 6)
        elif ext == ".spr" and _spr:
            spr_stem    = os.path.splitext(out_name)[0]
            spr_out_dir = os.path.join(file_out_dir, spr_stem)
            res = _spr.process_spr(src, spr_out_dir, log=log)
            if res["ok"] > 0:
                os.remove(src)
                bump("converted", res["ok"])
            else:
                log(f"      SPR: no textures extracted [{out_name}]", 6)
        elif ext == ".spr" and not _spr:
            log(f"      spr SKIP (spr_extract.py not found in pipeline/)", 6)
        elif ext == ".bvp" and _bvp:
            bvp_stem    = os.path.splitext(out_name)[0]
            bvp_out_dir = os.path.join(file_out_dir, bvp_stem)
            res = _bvp.process_bvp(src, bvp_out_dir, compiler=ast_compiler, log=log)
            if res["extracted"] > 0:
                os.remove(src)
                bump("converted", res["extracted"])
            else:
                log(f"      BVP: no entries extracted [{out_name}]", 6)
        elif ext == ".bvp" and not _bvp:
            log(f"      bvp SKIP (bvp_extract.py not found in pipeline/)", 6)
        elif ext == ".amd" and _amd:
            amd_stem    = os.path.splitext(out_name)[0]
            amd_out_dir = os.path.join(file_out_dir, amd_stem)
            res = _amd.extract(src, amd_out_dir, log=log)
            if res["ok"] > 0:
                os.remove(src)
                bump("converted", res["ok"])
            else:
                log(f"      AMD: no chunks extracted [{out_name}]", 6)
        elif ext == ".amd" and not _amd:
            log(f"      amd SKIP (amd_extract.py not found in pipeline/)", 6)

    def worker():
        while True:
            try:
                kind, (rel_name, src_path) = work_q.get_nowait()
            except queue.Empty:
                return
            rel_subdir = os.path.dirname(rel_name)
            stem       = os.path.splitext(os.path.basename(rel_name))[0]
            if rel_subdir:
                file_out_dir = os.path.join(out_dir, rel_subdir, stem)
            else:
                file_out_dir = os.path.join(out_dir, stem)
            os.makedirs(file_out_dir, exist_ok=True)
            try:
                if kind == "loose":
                    fname = os.path.basename(rel_name)
                    dst   = os.path.join(file_out_dir, fname)
                    if os.path.abspath(src_path) != os.path.abspath(dst):
                        shutil.copy2(src_path, dst)
                    _process_file(fname, dst, file_out_dir)
                else:
                    count, out_names = process_pac(src_path, file_out_dir)
                    if not count:
                        log(f"  -  {rel_name} (empty)", 2)
                    else:
                        for out_name in out_names:
                            src = os.path.join(file_out_dir, out_name)
                            log(f"  OK  {rel_name} -> {out_name}", 4)
                            _process_file(out_name, src, file_out_dir)
            except Exception as e:
                log(f"  ERR  {rel_name}: {e}", 5)
                bump("errors")
            bump("done")
            work_q.task_done()

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    import datetime
    log_path = os.path.join(out_dir, "putc_errors.log")
    h, w = stdscr.getmaxyx()
    if error_log:
        try:
            with open(log_path, "a", encoding="utf-8") as lf:
                lf.write(f"\n=== Run {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
                lf.write("\n".join(error_log) + "\n")
        except Exception:
            pass
        safe_addstr(stdscr, h-3, 2,
            f" {stats['errors']} error(s) written to: putc_errors.log ",
            curses.color_pair(5))

    safe_addstr(stdscr, h-2, 2,
        f" Done! {stats['done']} extracted, {stats['converted']} converted, "
        f"{stats['errors']} errors. Press any key. ",
        curses.color_pair(3) | curses.A_BOLD)
    stdscr.refresh()
    stdscr.getch()

def screen_flatten(stdscr):
    out_dir = to_native(OUT_DIR)
    stdscr.clear()
    h, w = stdscr.getmaxyx()
    draw_box(stdscr, 0, 0, h-1, w, "FLATTEN OUTPUT DIR")

    if not os.path.isdir(out_dir):
        safe_addstr(stdscr, 2, 2, "ERROR: output dir not found:", curses.color_pair(5) | curses.A_BOLD)
        safe_addstr(stdscr, 3, 2, out_dir, curses.color_pair(2))
        safe_addstr(stdscr, 5, 2, "Press any key.", curses.color_pair(2))
        stdscr.refresh()
        stdscr.getch()
        return

    safe_addstr(stdscr, 2, 2, f"Target: {out_dir}"[:w-4], curses.color_pair(2))
    safe_addstr(stdscr, 3, 2, "Move all files into the root of the output dir and remove empty subdirs.", curses.color_pair(6))
    safe_addstr(stdscr, 4, 2, "Conflicts (duplicate filenames) get a numeric suffix.", curses.color_pair(6))
    safe_addstr(stdscr, 6, 2, "Press Enter to proceed, Esc to cancel.", curses.color_pair(2))
    stdscr.refresh()

    while True:
        k = stdscr.getch()
        if k == 27:
            return
        if k in (curses.KEY_ENTER, ord("\n"), ord("\r"), ord(" ")):
            break

    log_lines = []
    LOG_Y     = 8
    moved  = 0
    errors = 0

    def log(msg, pair=2):
        log_lines.append((msg, pair))
        h, w = stdscr.getmaxyx()
        log_h = h - LOG_Y - 3
        visible = log_lines[-log_h:]
        for i, (line, p) in enumerate(visible):
            safe_addstr(stdscr, LOG_Y + i, 2, line.ljust(w - 4)[:w - 4], curses.color_pair(p))
        stdscr.refresh()

    for root, dirs, files in os.walk(out_dir, topdown=False):
        if os.path.abspath(root) == os.path.abspath(out_dir):
            continue
        for fname in files:
            src = os.path.join(root, fname)
            dst = os.path.join(out_dir, fname)
            if os.path.exists(dst):
                base, ext = os.path.splitext(fname)
                counter = 1
                while os.path.exists(dst):
                    dst = os.path.join(out_dir, f"{base}_{counter}{ext}")
                    counter += 1
            try:
                shutil.move(src, dst)
                log(f"  {os.path.relpath(src, out_dir)}  ->  {os.path.basename(dst)}", 4)
                moved += 1
            except Exception as e:
                log(f"  ERR {fname}: {e}", 5)
                errors += 1

    for root, dirs, files in os.walk(out_dir, topdown=False):
        if os.path.abspath(root) == os.path.abspath(out_dir):
            continue
        try:
            if not os.listdir(root):
                os.rmdir(root)
        except Exception:
            pass

    h, w = stdscr.getmaxyx()
    safe_addstr(stdscr, h - 2, 2,
        f" Done. {moved} moved, {errors} errors. Press any key. ",
        curses.color_pair(3) | curses.A_BOLD)
    stdscr.refresh()
    stdscr.getch()

def main(stdscr):
    init_colors()
    curses.curs_set(0)

    cpu_cores   = os.cpu_count() or 4
    MAX_THREADS = cpu_cores * 2
    THREADS_ROW = 1

    recursive = RECURSIVE
    set_threads(max(1, min(MAX_THREADS, THREADS)))
    last_sel  = 0

    screen_ensure_tools(stdscr)

    while True:
        stdscr.clear()
        h, w = stdscr.getmaxyx()
        draw_box(stdscr, 0, 0, h-1, w, "P3 BATCH EXTRACTOR")

        safe_addstr(stdscr, 2, 2, f"INPUT DIR : {INPUT_DIR}"[:w-4], curses.color_pair(2))
        safe_addstr(stdscr, 3, 2, f"OUT DIR : {OUT_DIR}"[:w-4], curses.color_pair(2))

        t = get_threads()
        menu_items = [
            f"Recursive scan   : {'ON ' if recursive else 'OFF'}",
            f"Threads          : ◄ {t:2d} ►  (max {MAX_THREADS})",
            "Run extraction",
            "Flatten output dir",
            "Quit",
        ]
        draw_box(stdscr, 5, 2, len(menu_items)+2, 56, "MENU")
        choice = arrow_menu(stdscr, 6, 3, menu_items, selected=last_sel,
                            item_width=52, lr_rows={THREADS_ROW})

        if choice == -1 or choice == 4:
            break
        elif choice == _MENU_LEFT:
            set_threads(max(1, get_threads() - 1))
            save_config(THREADS=get_threads())
            last_sel = THREADS_ROW
        elif choice == _MENU_RIGHT:
            set_threads(min(MAX_THREADS, get_threads() + 1))
            save_config(THREADS=get_threads())
            last_sel = THREADS_ROW
        elif choice == 0:
            recursive = not recursive
            save_config(RECURSIVE=recursive)
            last_sel = 0
        elif choice == 1:
            last_sel = 1
        elif choice == 2:
            last_sel = 2
            screen_run(stdscr, recursive=recursive)
        elif choice == 3:
            last_sel = 3
            screen_flatten(stdscr)

if __name__ == "__main__":
    curses.wrapper(main)
