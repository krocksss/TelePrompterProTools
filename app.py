# -*- coding: utf-8 -*-
"""
Prompter - teleprompter sincronizado com o Pro Tools. Windows e macOS.
Feito por Marllon Machado - https://github.com/krocksss

Duas fontes de sincronia, usadas juntas:
  1. PTSL (Pro Tools Scripting Library, gRPC em localhost:31416): sem driver, sem configuracao.
     Da o nome da sessao, o estado do transporte (play/stop), a posicao do cursor e permite
     COMANDAR o Pro Tools (play, stop, locate). Funciona no Pro Tools Intro (>= 2022.12).
  2. MTC (MIDI Time Code) por uma porta MIDI virtual, opcional: posicao exata frame a frame enquanto
     toca. Windows: loopMIDI (instalado junto). macOS: o proprio Prompter cria a porta virtual (CoreMIDI).
     Quando existe, manda; quando nao existe, a posicao e estimada a partir do ponto de partida + relogio
     local (erro ~0,05 s, suficiente para letra).

Transcricao em segundo plano: PyAV -> WAV, Demucs (isola a voz) + faster-whisper (tempo por palavra).
Serve a tela do prompter, o estudio de letras e a configuracao em http://localhost:PORT
"""
import os, sys, json, time, threading, re, unicodedata, traceback, webbrowser, subprocess, difflib, socket
from pathlib import Path

VERSION = "2.0.3"
REPO = "krocksss/TelePrompterProTools"
AUTHOR = {"name": "Marllon Machado", "github": "https://github.com/krocksss", "repo": "https://github.com/" + REPO}
WIN = sys.platform == "win32"
MAC = sys.platform == "darwin"
FROZEN = bool(getattr(sys, "frozen", False))
BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))          # static/ (somente leitura)
if FROZEN and WIN:
    APPDIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Prompter"   # dados gravaveis
elif FROZEN and MAC:
    APPDIR = Path.home() / "Library" / "Application Support" / "Prompter"
else:
    APPDIR = Path(__file__).resolve().parent
DATA = APPDIR / "data"
STATIC = BASE / "static"
DATA.mkdir(parents=True, exist_ok=True)
CFG_PATH = APPDIR / "config.json"
LIB_PATH = DATA / "library.json"
LOG_PATH = DATA / "prompter.log"
NOWIN = 0x08000000 if WIN else 0                 # CREATE_NO_WINDOW
LOWPRIO = (0x4000 | 0x08000000) if WIN else 0    # BELOW_NORMAL_PRIORITY_CLASS | CREATE_NO_WINDOW

MUSIC_DEFAULT = (Path.home() / "Documents" / "Prompter") if FROZEN else (APPDIR / "musicas")
DEFAULT_CFG = {
    "pasta_musicas": str(MUSIC_DEFAULT),
    "porta": 8797,
    "midi_port_contains": "Pro Tools MTC",
    "modelo_whisper": "large-v3-turbo",
    "idioma": "pt",
    "avanco_segundos": 0.3,
    "cpu_threads": max(2, min(8, (os.cpu_count() or 4) - 2)),
    "separar_vocal": True,
    "abrir_navegador": True,       # toda vez que abre: tela do prompter no navegador
    "abrir_protools": True,        # toda vez que abre: abre o Pro Tools junto
    "sessao_auto": True,           # sessao aberta no Pro Tools entra sozinha na biblioteca
    "ptsl": True,
    "checar_atualizacao": True,    # olha as releases do GitHub
}

WHISPER_REPOS = {  # tamanho aproximado do download (MB) so para mostrar progresso
    "large-v3-turbo": ("mobiuslabsgmbh/faster-whisper-large-v3-turbo", 1620),
    "medium": ("Systran/faster-whisper-medium", 1530),
    "small": ("Systran/faster-whisper-small", 480),
    "base": ("Systran/faster-whisper-base", 150),
}


def log(*a):
    line = time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a)
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > 2_000_000:
            LOG_PATH.replace(LOG_PATH.with_suffix(".old"))
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_cfg():
    cfg = dict(DEFAULT_CFG)
    if CFG_PATH.exists():
        try:
            cfg.update(json.loads(CFG_PATH.read_text(encoding="utf-8")))
        except Exception as e:
            log("config.json invalido, usando padrao:", e)
    save_cfg(cfg)
    return cfg


def save_cfg(cfg):
    CFG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


CFG = load_cfg()


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
    return s


def open_path(p):
    """Abre pasta/arquivo/URL no programa padrao do sistema."""
    p = str(p)
    try:
        if WIN:
            os.startfile(p)
        elif MAC:
            subprocess.Popen(["open", p])
        else:
            subprocess.Popen(["xdg-open", p])
    except Exception as e:
        log("nao abriu", p, e)


def port_open(port, host="127.0.0.1", timeout=0.4):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(timeout)
        s.connect((host, port))
        return True
    except Exception:
        return False
    finally:
        s.close()


# ----------------------------------------------------------------------------
# Pro Tools: achar, abrir
# ----------------------------------------------------------------------------
def protools_exe():
    if WIN:
        for pf in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            for name in ("Pro Tools", "Pro Tools Intro", "Pro Tools Artist", "Pro Tools Studio", "Pro Tools Ultimate"):
                p = Path(pf) / "Avid" / name / "ProTools.exe"
                if p.exists():
                    return str(p)
    elif MAC:
        for name in ("Pro Tools", "Pro Tools Intro", "Pro Tools Artist", "Pro Tools Studio", "Pro Tools Ultimate"):
            p = Path("/Applications") / (name + ".app")
            if p.exists():
                return str(p)
    return None


def protools_running():
    if WIN:
        try:
            import win32gui
            found = []
            win32gui.EnumWindows(lambda h, _: found.append(h) if win32gui.GetClassName(h) == "DigiAppWndClass" else None, None)
            if found:
                return True
        except Exception:
            pass
        try:
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq ProTools.exe"], capture_output=True, creationflags=NOWIN).stdout
            return b"ProTools.exe" in out
        except Exception:
            return False
    try:
        r = subprocess.run(["pgrep", "-f", "Pro Tools"], capture_output=True)
        return r.returncode == 0
    except Exception:
        return port_open(31416)


def launch_protools():
    """Abre o Pro Tools se nao estiver aberto. Devolve True se abriu/ja estava."""
    if protools_running():
        return True
    exe = protools_exe()
    if not exe:
        log("Pro Tools nao encontrado para abrir junto")
        return False
    try:
        if MAC:
            subprocess.Popen(["open", "-a", exe])
        else:
            subprocess.Popen([exe], cwd=str(Path(exe).parent))
        log("abrindo o Pro Tools:", exe)
        return True
    except Exception as e:
        log("erro abrindo o Pro Tools:", e)
        return False


# ----------------------------------------------------------------------------
# Biblioteca de musicas (json em data/library.json)
# ----------------------------------------------------------------------------
class Library:
    def __init__(self):
        self.lock = threading.RLock()
        self.songs = {}
        if LIB_PATH.exists():
            try:
                self.songs = json.loads(LIB_PATH.read_text(encoding="utf-8")).get("songs", {})
            except Exception as e:
                log("library.json invalido:", e)

    def save(self):
        with self.lock:
            tmp = LIB_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps({"songs": self.songs}, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, LIB_PATH)

    def get(self, sid):
        return self.songs.get(sid)

    def find_by_session(self, session_name):
        """Casa o nome da sessao do Pro Tools com uma musica da biblioteca."""
        if not session_name:
            return None
        n = norm(session_name)
        with self.lock:
            for sid, s in self.songs.items():
                if s.get("session_alias") and norm(s["session_alias"]) == n:
                    return sid
            for sid, s in self.songs.items():
                if norm(s["name"]) == n:
                    return sid
            for sid, s in self.songs.items():
                ns = norm(s["name"])
                if ns and (ns in n or n in ns):
                    return sid
        return None

    def public(self):
        with self.lock:
            return {sid: dict({k: v for k, v in s.items() if k not in ("words", "lines")},
                              words_n=len(s.get("words") or []), n_lines=len(s.get("lines") or []))
                    for sid, s in self.songs.items()}


LIB = Library()

AUDIO_EXT = {".wav", ".mp3", ".m4a", ".flac", ".aif", ".aiff", ".ogg", ".wma", ".aac"}
SKIP_DIRS = {"audio files", "session file backups", "bounced files", "clip groups", "renders", "video files", "wavecache"}


def folder_info(d):
    """Descreve uma pasta de musica/sessao: nome, audios soltos e Audio Files/*.wav"""
    d = Path(d)
    if not d.is_dir():
        return None
    files = [f.name for f in d.iterdir() if f.is_file()]
    ptx = [f for f in files if f.lower().endswith((".ptx", ".ptf"))]
    loose_audio = [d / f for f in files if Path(f).suffix.lower() in AUDIO_EXT]
    af = d / "Audio Files"
    session_audio = (sorted(af.glob("*.wav")) + sorted(af.glob("*.aif")) + sorted(af.glob("*.aiff"))) if af.exists() else []
    if not ptx and not loose_audio and not session_audio:
        return None
    name = Path(ptx[0]).stem if ptx else d.name
    return {"name": name, "folder": str(d), "originals": [str(p) for p in loose_audio],
            "session_audio": [str(p) for p in session_audio]}


def register(found):
    """Entra com pastas descobertas na biblioteca. found = {nome: info}. Devolve True se mudou.
    A mesma musica pode vir de dois lugares (MP3 na pasta de musicas + sessao do Pro Tools): os audios se somam."""
    changed = False

    def dedupe(*lists):
        out = []
        for lst in lists:
            for x in lst or []:
                if x not in out and os.path.exists(x):
                    out.append(x)
        return out
    with LIB.lock:
        for name, info in found.items():
            sid = norm(name).replace(" ", "-") or name
            s = LIB.songs.get(sid)
            if s is None:
                candidates = info["originals"] or info["session_audio"]
                try:
                    sig = json.dumps([[c, os.path.getmtime(c)] for c in candidates])
                except OSError:
                    sig = json.dumps(candidates)
                LIB.songs[sid] = {"name": name, "folder": info["folder"], "candidates": candidates,
                                  "originals": info["originals"], "session_audio": info["session_audio"], "sig": sig,
                                  "status": "pendente", "lines": [], "offset": 0.0, "source": None, "erro": None, "progresso": None}
                changed = True
                log("musica nova na biblioteca:", name, "(%d arquivos)" % len(candidates))
                continue
            originals = dedupe(s.get("originals"), info["originals"])
            session_audio = dedupe(s.get("session_audio"), info["session_audio"])
            candidates = originals or session_audio
            try:
                sig = json.dumps([[c, os.path.getmtime(c)] for c in candidates])
            except OSError:
                sig = json.dumps(candidates)
            if s.get("sig") != sig:
                s.update({"candidates": candidates, "originals": originals, "session_audio": session_audio, "sig": sig})
                if s.get("status") not in ("manual", "alinhado", "transcrevendo"):
                    s.update({"status": "pendente", "erro": None})
                changed = True
    if changed:
        LIB.save()
    return changed


def scan_folder():
    """Descobre musicas na pasta configurada: pasta com .ptx (sessao), pasta com audio, ou audio solto na raiz."""
    root = Path(CFG["pasta_musicas"])
    try:
        root.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        log("pasta das musicas inacessivel:", e)
        return False
    found = {}
    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        if d.name.lower() in SKIP_DIRS:
            dirnames[:] = []
            continue
        if d == root:
            for f in filenames:
                p = d / f
                if p.suffix.lower() in AUDIO_EXT:
                    found[p.stem] = {"name": p.stem, "folder": str(d), "originals": [str(p)], "session_audio": []}
            continue
        info = folder_info(d)
        if info:
            found[info["name"]] = info
            dirnames[:] = []
    return register(found)


def add_session_folder(path):
    """Sessao aberta no Pro Tools (caminho do .ptx) -> entra na biblioteca automaticamente."""
    try:
        p = Path(path)
        d = p.parent if p.suffix.lower() in (".ptx", ".ptf") else p
        info = folder_info(d)
        if not info:
            return False
        if p.suffix.lower() in (".ptx", ".ptf"):
            info["name"] = p.stem
        return register({info["name"]: info})
    except Exception as e:
        log("erro lendo pasta da sessao:", e)
        return False


# ----------------------------------------------------------------------------
# Letra: alinhamento com as palavras ouvidas, reflow apos edicao
# ----------------------------------------------------------------------------
def wdict(x):
    return {"w": x.word.strip(), "s": round(x.start, 2), "e": round(x.end, 2)}


def _fill_times(off, words_end):
    """off = [[line_idx, tok, norm, s, e]] com alguns s/e conhecidos -> preenche o resto por interpolacao."""
    n = len(off)
    known = [k for k in range(n) if off[k][3] is not None]
    for k in range(n):
        if off[k][3] is not None:
            continue
        prev = max((j for j in known if j < k), default=None)
        nxt = min((j for j in known if j > k), default=None)
        if prev is not None and nxt is not None:
            a, b = off[prev][4], off[nxt][3]
            frac = (k - prev) / (nxt - prev)
            st = a + (b - a) * frac
            off[k][3], off[k][4] = st, min(b, st + (b - a) / (nxt - prev))
        elif prev is not None:
            st = off[prev][4] + 0.4 * (k - prev - 1)
            off[k][3], off[k][4] = min(st, words_end), min(st + 0.4, words_end)
        elif nxt is not None:
            st = max(0.0, off[nxt][3] - 0.4 * (nxt - k))
            off[k][3], off[k][4] = st, st + 0.4
        else:
            off[k][3], off[k][4] = k * 0.4, k * 0.4 + 0.4
    for k in range(1, n):  # monotonico
        if off[k][3] < off[k - 1][3]:
            off[k][3] = off[k - 1][3] + 0.05
        if off[k][4] < off[k][3]:
            off[k][4] = off[k][3] + 0.2


def align_lyrics(text, words):
    """Alinha a letra OFICIAL (uma linha por verso) com as palavras ouvidas no audio.
    words = [{"s","e","w"}]. Devolve linhas com tempo E palavras com tempo (as que nao casaram sao interpoladas)."""
    off_lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not off_lines:
        return []
    off = []  # [line_idx, texto_original, norm, s, e]
    for i, l in enumerate(off_lines):
        for tok in l.split():
            nt = norm(tok)
            if nt:
                off.append([i, tok, nt, None, None])
    tw = [norm(w["w"]) for w in words]
    sm = difflib.SequenceMatcher(a=[o[2] for o in off], b=tw, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                off[i1 + k][3] = words[j1 + k]["s"]
                off[i1 + k][4] = words[j1 + k]["e"]
    matched_words = sum(1 for o in off if o[3] is not None)
    matched_lines = len({o[0] for o in off if o[3] is not None})
    _fill_times(off, max((w["e"] for w in words), default=0.0))
    lines = []
    for i, l in enumerate(off_lines):
        ws = [o for o in off if o[0] == i]
        if not ws:
            continue
        lines.append({"t": round(ws[0][3], 2), "end": round(ws[-1][4], 2), "text": l,
                      "words": [{"w": o[1], "s": round(o[3], 2), "e": round(o[4], 2)} for o in ws]})
    log("  alinhamento: %d de %d palavras e %d de %d linhas casaram com o audio" % (matched_words, len(off), matched_lines, len(lines)))
    return lines


def reflow_words(text, old_words, t, end):
    """Texto da linha mudou: mantem o tempo das palavras que continuam iguais, interpola as novas."""
    toks = text.split()
    if not toks:
        return []
    off = [[0, tok, norm(tok), None, None] for tok in toks]
    old = [w for w in (old_words or []) if norm(w.get("w", ""))]
    if old:
        sm = difflib.SequenceMatcher(a=[o[2] for o in off], b=[norm(w["w"]) for w in old], autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                for k in range(i2 - i1):
                    off[i1 + k][3], off[i1 + k][4] = old[j1 + k]["s"], old[j1 + k]["e"]
    if not any(o[3] is not None for o in off):
        b = max(t + 0.5, end if end and end > t else t + 3)
        step = (b - t) / len(toks)
        return [{"w": tok, "s": round(t + k * step, 2), "e": round(t + (k + 1) * step, 2)} for k, tok in enumerate(toks)]
    _fill_times(off, max(t, end or t) + 1.0)
    return [{"w": o[1], "s": round(o[3], 2), "e": round(o[4], 2)} for o in off]


def shift_words(words, delta):
    return [{"w": w["w"], "s": round(w["s"] + delta, 2), "e": round(w["e"] + delta, 2)} for w in (words or [])]


def lyrics_txt_for(song):
    """letra.txt (ou <nome>.txt) na pasta da musica = letra oficial."""
    folder = Path(song.get("folder") or "")
    for cand in (folder / "letra.txt", folder / (song["name"] + ".txt")):
        if cand.exists():
            try:
                return cand.read_text(encoding="utf-8-sig")
            except Exception:
                return cand.read_text(encoding="cp1252", errors="replace")
    return song.get("official") or None


# ----------------------------------------------------------------------------
# Audio: conversao para WAV com o PyAV (sem depender de ffmpeg instalado)
# ----------------------------------------------------------------------------
def to_wav(src, dst, rate=44100):
    import av, wave
    with av.open(str(src)) as c:
        stream = c.streams.audio[0]
        res = av.AudioResampler(format="s16", layout="stereo", rate=rate)
        with wave.open(str(dst), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(rate)
            for frame in c.decode(stream):
                for f in res.resample(frame):
                    w.writeframes(f.to_ndarray().tobytes())
            for f in res.resample(None):
                w.writeframes(f.to_ndarray().tobytes())
    return str(dst)


def audio_duration(path):
    try:
        import av
        with av.open(str(path)) as c:
            return float(c.duration / 1_000_000) if c.duration else 0.0
    except Exception:
        return 0.0


def demucs_worker(argv):
    """Processo filho: isola a voz. argv = [entrada.wav, saida_vocals.wav]. Progresso em stdout: PROG 0.42"""
    import soundfile as sf, torch
    from demucs.api import Separator
    src, dst = argv[0], argv[1]
    torch.set_num_threads(max(1, int(CFG.get("cpu_threads", 4))))

    def cb(info):
        try:
            if info.get("state") == "end":
                done = info.get("segment_offset", 0) + info.get("segment_length", 0)
                print("PROG %.3f" % (done / max(1, info.get("audio_length", 1))), flush=True)
        except Exception:
            pass
    sep = Separator(model="htdemucs", device="cpu", progress=False, callback=cb)
    wav, sr = sf.read(src, dtype="float32", always_2d=True)
    origin, stems = sep.separate_tensor(torch.from_numpy(wav.T.copy()), sr)
    v = stems["vocals"].numpy().T
    sf.write(dst, v, sep.samplerate)
    print("DONE", flush=True)


# ----------------------------------------------------------------------------
# Transcricao em segundo plano (faster-whisper, CPU, prioridade baixa)
# ----------------------------------------------------------------------------
class Transcriber(threading.Thread):
    def __init__(self, state):
        super().__init__(daemon=True, name="transcriber")
        self.state = state
        self.model = None
        self.model_name = None
        self.wake = threading.Event()
        self.current = None
        self.preload = False

    def set_prog(self, sid, etapa, pct=None, extra=None):
        s = LIB.get(sid)
        if s is not None:
            with LIB.lock:
                s["progresso"] = {"etapa": etapa, "pct": None if pct is None else round(float(pct) * 100),
                                  "extra": extra, "at": time.time()}

    @staticmethod
    def hub_dir():
        return Path(os.environ.get("HF_HUB_CACHE") or (Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"))

    def model_dir(self, name=None):
        return DATA / "models" / (name or CFG["modelo_whisper"])

    def whisper_cached(self, name=None):
        name = name or CFG["modelo_whisper"]
        d = self.model_dir(name)
        return d if (d / "model.bin").is_file() and not (d / "model.bin").is_symlink() else None

    def hub_snapshot(self, repo):
        """Pasta do snapshot no cache do Hugging Face, se o modelo ja foi baixado por la."""
        d = self.hub_dir() / ("models--" + repo.replace("/", "--")) / "snapshots"
        if not d.exists():
            return None
        for snap in sorted(d.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if (snap / "model.bin").exists():
                return snap
        return None

    def materialize(self, repo, mdir, sid=None):
        """Garante mdir com arquivos reais (sem symlink): copia do cache do hub ou baixa com local_dir."""
        import shutil
        mdir.mkdir(parents=True, exist_ok=True)
        snap = self.hub_snapshot(repo)
        if snap is not None:
            log("  copiando modelo do cache do hub para", mdir)
            for f in snap.iterdir():
                real = Path(os.path.realpath(f))
                dst = mdir / f.name
                if dst.exists() and dst.stat().st_size == real.stat().st_size:
                    continue
                tmp = mdir / (f.name + ".copiando")
                shutil.copyfile(real, tmp)
                os.replace(tmp, dst)
            return
        from faster_whisper.utils import download_model
        log("  baixando modelo para", mdir)
        download_model(repo, output_dir=str(mdir))   # local_dir: arquivos reais
        for f in list(mdir.iterdir()):                  # por garantia, desfaz qualquer link
            if f.is_symlink():
                real = Path(os.path.realpath(f))
                f.unlink()
                shutil.copyfile(real, f)

    def demucs_cached(self):
        for cand in (Path.home() / ".cache" / "torch" / "hub" / "checkpoints", self.hub_dir() / "models--adefossez--HTDemucs"):
            if cand.exists() and any(cand.iterdir()):
                return True
        return False

    def get_model(self, sid=None):
        name = CFG["modelo_whisper"]
        if self.model is not None and self.model_name == name:
            return self.model
        from faster_whisper import WhisperModel
        self.model = None
        repo, size_mb = WHISPER_REPOS.get(name, (name, 0))
        mdir = self.model_dir(name)
        cached = self.whisper_cached(name)
        log("carregando modelo whisper", name, "(pronto em %s)" % mdir if cached else "(primeira vez: baixando ~%d MB)" % size_mb)
        stop = threading.Event()
        if not cached and sid:
            def watch():
                while not stop.is_set():
                    try:
                        got = sum(f.stat().st_size for f in mdir.rglob("*") if f.is_file()) if mdir.exists() else 0
                        self.set_prog(sid, "baixando modelo de transcrição (só uma vez, %d MB)" % size_mb, min(0.99, got / (size_mb * 1e6)))
                    except Exception:
                        pass
                    stop.wait(2)
            threading.Thread(target=watch, daemon=True).start()
        try:
            if not cached:
                self.materialize(repo, mdir, sid)
            last = None
            for tentativa in range(6):
                try:
                    self.model = WhisperModel(str(mdir), device="cpu", compute_type="int8", cpu_threads=int(CFG["cpu_threads"]))
                    break
                except Exception as e:   # logo apos o download o arquivo pode estar travado (antivirus) -> espera e tenta de novo
                    last = e
                    log("  modelo nao abriu (tentativa %d): %s" % (tentativa + 1, str(e)[:160]))
                    if sid:
                        self.set_prog(sid, "modelo baixado, aguardando o arquivo liberar (tentativa %d de 6)" % (tentativa + 2), None)
                    time.sleep(8)
            else:
                raise last
        finally:
            stop.set()
        self.model_name = name
        return self.model

    def run(self):
        if WIN:
            try:
                import win32api, win32process
                win32process.SetThreadPriority(win32api.GetCurrentThread(), win32process.THREAD_PRIORITY_LOWEST)
            except Exception:
                pass
        while True:
            try:
                scan_folder()
                if self.preload:
                    self.preload = False
                    self.get_model()
                sid = None
                with LIB.lock:
                    for k, s in LIB.songs.items():
                        if s.get("status") == "pendente" and s.get("candidates"):
                            sid = k
                            break
                if sid is None:
                    self.wake.wait(15)
                    self.wake.clear()
                    continue
                self.transcribe_song(sid)
            except Exception as e:
                log("erro no transcritor:", e, traceback.format_exc())
                time.sleep(10)

    def wait_if_playing(self):
        while self.state.playing():   # nunca pesa a maquina enquanto o Pro Tools esta tocando
            time.sleep(1)

    def separate_vocals(self, wav, sid):
        """Isola a voz com o Demucs em processo filho de prioridade baixa. Devolve vocals.wav ou o original."""
        if not CFG.get("separar_vocal", True):
            return wav
        out = DATA / "sep" / (Path(wav).stem + ".vocals.wav")
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            if out.exists() and out.stat().st_mtime >= os.path.getmtime(wav) and out.stat().st_size > 1000:
                return str(out)
            self.wait_if_playing()
            log("  separando vocal (demucs):", os.path.basename(wav))
            self.set_prog(sid, "isolando a voz" if self.demucs_cached() else "baixando o separador de voz (só uma vez, 80 MB) e isolando a voz", 0)
            cmd = [sys.executable, "--demucs", str(wav), str(out)] if FROZEN else [sys.executable, str(BASE / "app.py"), "--demucs", str(wav), str(out)]
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=LOWPRIO, text=True, encoding="utf-8", errors="replace")
            if not WIN:
                try:
                    os.setpriority(os.PRIO_PROCESS, p.pid, 10)
                except Exception:
                    pass
            err = []
            threading.Thread(target=lambda: err.extend(p.stderr.read().splitlines()[-30:]), daemon=True).start()
            for line in p.stdout:
                if line.startswith("PROG"):
                    self.set_prog(sid, "isolando a voz", float(line.split()[1]))
            p.wait(timeout=3600)
            if p.returncode != 0 or not out.exists():
                log("  demucs falhou, usando o audio original:", "\n".join(err[-8:]))
                return wav
            return str(out)
        except Exception as e:
            log("  demucs erro, usando o audio original:", e)
            return wav

    HALLUC = {"musica", "legendas", "obrigado", "obrigada", "tchau", "amara org", "legendas pela comunidade amara org",
              "inscreva se no canal", "curta o video"}

    def transcribe_file(self, path, sid):
        wavdir = DATA / "wav"
        wavdir.mkdir(exist_ok=True)
        wav = wavdir / (norm(Path(path).stem).replace(" ", "_") + ".wav")
        if not wav.exists() or wav.stat().st_mtime < os.path.getmtime(path):
            self.set_prog(sid, "lendo o áudio", None)
            to_wav(path, wav)
        model = self.get_model(sid)
        src = self.separate_vocals(str(wav), sid)
        self.set_prog(sid, "ouvindo a letra", 0)
        # vad_filter desligado: o detector de fala descarta voz CANTADA
        segments, info = model.transcribe(src, language=CFG["idioma"] or None, vad_filter=False,
                                          word_timestamps=True, beam_size=5, condition_on_previous_text=False,
                                          initial_prompt="Letra da música, um verso por linha." if (CFG["idioma"] or "pt") == "pt" else None)
        dur = float(getattr(info, "duration", 0) or audio_duration(src) or 1)
        lines = []
        all_words = []
        for seg in segments:
            self.wait_if_playing()
            self.set_prog(sid, "ouvindo a letra", min(0.99, seg.end / dur))
            txt_all = seg.text.strip()
            nt = norm(txt_all)
            toks = nt.split()
            repetido = len(toks) >= 3 and len(set(toks)) <= max(1, len(toks) // 4)  # "boa boa boa", "la la la la"
            if ((getattr(seg, "no_speech_prob", 0) > 0.9 and getattr(seg, "avg_logprob", 0) < -1.0)
                    or getattr(seg, "compression_ratio", 0) > 2.4 or nt in self.HALLUC or len(nt) < 3 or repetido):
                continue
            words = [w for w in (seg.words or []) if w.word.strip()]
            if words and sum(getattr(w, "probability", 1.0) for w in words) / len(words) < 0.2:
                continue  # trecho instrumental "adivinhado"
            all_words.extend({"s": round(w.start, 2), "e": round(w.end, 2), "w": w.word.strip()} for w in words)
            if not words:
                if txt_all:
                    lines.append({"t": round(seg.start, 2), "end": round(seg.end, 2), "text": txt_all})
                continue
            cur = []
            for w in words:
                ws = w.word.strip()
                gap = (w.start - cur[-1].end) if cur else 0
                if cur and (gap > 1.0 or (ws[:1].isupper() and len("".join(x.word for x in cur).strip()) >= 12
                                          and cur[-1].word.strip()[-1:] not in ",.;:!?")):
                    lines.append(self._line(cur))
                    cur = []
                cur.append(w)
                txt = "".join(x.word for x in cur).strip()
                ends_punct = txt[-1] in ",.;:!?" if txt else False
                if (ends_punct and len(txt) >= 26) or len(txt) >= 46:
                    lines.append(self._line(cur))
                    cur = []
            if cur:
                lines.append(self._line(cur))
        return lines, len(all_words), all_words

    @staticmethod
    def _line(cur):
        txt = "".join(x.word for x in cur).strip()
        txt = re.sub(r"[.]+$", "", txt).strip()  # ponto final nao existe em letra
        return {"t": round(cur[0].start, 2), "end": round(cur[-1].end, 2), "text": txt, "words": [wdict(x) for x in cur]}

    def transcribe_song(self, sid):
        s = LIB.get(sid)
        with LIB.lock:
            s["status"] = "transcrevendo"
            s["progresso"] = {"etapa": "na fila", "pct": None}
            forced = s.pop("fonte_forcada", None)
        self.current = sid
        LIB.save()
        log("transcrevendo", s["name"], ("(faixa escolhida: %s)" % os.path.basename(forced)) if forced else "")
        best, best_words, best_file, best_wl = [], -1, None, []
        try:
            cands = [forced] if forced and os.path.exists(forced) else list(s["candidates"])
            for path in cands:
                if not os.path.exists(path):
                    continue
                self.wait_if_playing()
                log("  arquivo:", os.path.basename(path))
                lines, nwords, wl = self.transcribe_file(path, sid)
                log("  ->", nwords, "palavras,", len(lines), "linhas")
                if nwords > best_words:
                    best, best_words, best_file, best_wl = lines, nwords, path, wl
                if nwords > 20 and (path in (s.get("originals") or []) or len(cands) > 3):
                    break  # achou voz, nao precisa olhar o resto
            official = lyrics_txt_for(s)
            with LIB.lock:
                s["words"] = best_wl
                s["source"] = best_file
                s["duracao"] = round(audio_duration(best_file), 2) if best_file else None
                if official and best_wl:
                    s["official"] = official
                    s["lines"] = align_lyrics(official, best_wl)
                    s["status"] = "alinhado"
                    s["erro"] = None
                else:
                    s["lines"] = best
                    s["status"] = "pronto" if best_words > 0 else "sem-voz"
                    s["erro"] = None if best_words > 0 else "nenhuma voz encontrada nos arquivos"
                s["progresso"] = None
            log("pronto:", s["name"], "status", s["status"])
        except Exception as e:
            with LIB.lock:
                s["status"] = "erro"
                s["erro"] = str(e)[:300]
                s["progresso"] = None
            log("erro transcrevendo", s["name"], e, traceback.format_exc()[-800:])
        self.current = None
        LIB.save()


# ----------------------------------------------------------------------------
# Estado compartilhado: posicao/transporte vindo do MTC (preciso) e/ou do PTSL (estimado)
# ----------------------------------------------------------------------------
RATES = {0: 24.0, 1: 25.0, 2: 29.97, 3: 30.0}


class State:
    def __init__(self):
        self.lock = threading.Lock()
        # MTC
        self.tc_seconds = 0.0
        self.tc_at = 0.0
        self.last_qf = 0.0
        self.rate = 30.0
        self.midi_ok = False
        self.midi_port = None
        self.tc_str = "00:00:00:00"
        # PTSL
        self.ptsl_ok = False
        self.ptsl_playing = False
        self.est_start = 0.0
        self.est_at = 0.0
        self.sel_seconds = 0.0
        self.sel_at = 0.0
        self.session_path = None
        # geral
        self.session = None
        self.pt_found = False
        self.forced_song = None
        self.manual_line = None

    def mtc_live(self):
        return (time.monotonic() - self.last_qf) < 0.3

    def playing(self):
        return self.mtc_live() or (self.ptsl_ok and self.ptsl_playing)

    def source(self):
        if self.mtc_live():
            return "mtc"
        if self.ptsl_ok:
            return "ptsl"
        if self.midi_ok:
            return "mtc"
        return None

    def note_qf(self):
        now = time.monotonic()
        if now - self.last_qf > 1.0 and self.manual_line is not None:
            self.manual_line = None
        self.last_qf = now

    def seconds_now(self):
        with self.lock:
            now = time.monotonic()
            if self.mtc_live():
                return self.tc_seconds + (now - self.tc_at)
            if self.ptsl_ok:
                if self.ptsl_playing:
                    return self.est_start + (now - self.est_at)
                if self.sel_at >= self.tc_at:
                    return self.sel_seconds
            return self.tc_seconds

    def set_tc(self, h, m, s, f, rate):
        with self.lock:
            self.rate = rate
            self.tc_seconds = h * 3600 + m * 60 + s + f / rate
            self.tc_at = time.monotonic()
            self.tc_str = "%02d:%02d:%02d:%02d" % (h, m, s, int(f) % int(round(rate)))

    def tc_text(self):
        if self.mtc_live():
            return self.tc_str
        sec = max(0.0, self.seconds_now())
        return "%02d:%02d:%02d:%02d" % (int(sec // 3600), int(sec % 3600 // 60), int(sec % 60), int((sec - int(sec)) * self.rate))


class MTCReader(threading.Thread):
    """Le MTC. Windows: porta do loopMIDI. macOS: cria a propria porta virtual (CoreMIDI) com o mesmo nome."""

    def __init__(self, state):
        super().__init__(daemon=True, name="mtc")
        self.state = state
        self.qf = [None] * 8

    def run(self):
        import mido
        while True:
            try:
                want = CFG["midi_port_contains"]
                names = [n for n in mido.get_input_names() if want.lower() in n.lower()]
                if names:
                    port = mido.open_input(names[0])
                    label = names[0]
                elif MAC:
                    port = mido.open_input(want, virtual=True)
                    label = want + " (porta virtual do Prompter)"
                else:
                    self.state.midi_ok = False
                    time.sleep(3)
                    continue
                with port:
                    self.state.midi_ok = True
                    self.state.midi_port = label
                    log("MIDI aberto:", label)
                    for msg in port:
                        self.handle(msg)
            except Exception as e:
                self.state.midi_ok = False
                if str(e) != getattr(self, "_last_err", None):
                    self._last_err = str(e)
                    log("MIDI caiu, tentando de novo:", e, traceback.format_exc()[-600:])
                time.sleep(3)

    def handle(self, msg):
        st = self.state
        if msg.type == "quarter_frame":
            st.note_qf()
            if msg.frame_type == 0:
                self.qf = [None] * 8
            self.qf[msg.frame_type] = msg.frame_value
            if msg.frame_type == 7 and all(v is not None for v in self.qf):
                q = self.qf
                f = q[0] | (q[1] << 4)
                s = q[2] | (q[3] << 4)
                m = q[4] | (q[5] << 4)
                h = q[6] | ((q[7] & 1) << 4)
                rate = RATES[(q[7] >> 1) & 3]
                st.set_tc(h, m, s, f + 2, rate)   # 8 quarter frames levam 2 frames; o tempo lido e o do inicio
                self.qf = [None] * 8
        elif msg.type == "sysex" and len(msg.data) >= 8 and tuple(msg.data[:4]) == (0x7F, 0x7F, 0x01, 0x01):
            hh, mm, ss, ff = msg.data[4:8]
            st.set_tc(hh & 0x1F, mm, ss, ff, RATES[(hh >> 5) & 3])
            st.last_qf = 0.0  # full frame = locate parado


class PTLink(threading.Thread):
    """Conexao PTSL com o Pro Tools: sessao, transporte, cursor, e comandos (play/stop/locate)."""

    PTSL_LAG = 0.12   # medido: o transporte avisa 'playing' ~0,12 s depois de o audio ja estar andando

    def __init__(self, state):
        super().__init__(daemon=True, name="ptsl")
        self.state = state
        self.engine = None
        self.lock = threading.RLock()
        self.version = None
        self.err = None
        self.poll_s = 0.08

    def connect(self):
        import ptsl
        e = ptsl.Engine(company_name="Prompter", application_name="Prompter")
        self.version = e.ptsl_version()
        self.engine = e
        self.state.ptsl_ok = True
        self.err = None
        log("PTSL conectado, versao", self.version)

    def drop(self, why):
        if self.engine is not None:
            try:
                self.engine.close()
            except Exception:
                pass
        self.engine = None
        if self.state.ptsl_ok or str(why)[:200] != self.err:
            log("PTSL desconectado:" if self.state.ptsl_ok else "PTSL nao conectou:", str(why)[:300], traceback.format_exc()[-500:])
        self.state.ptsl_ok = False
        self.state.ptsl_playing = False
        self.err = str(why)[:200]

    def run(self):
        if not CFG.get("ptsl", True):
            return
        n = 0
        prev_end = time.monotonic()
        while True:
            try:
                if self.engine is None:
                    running = protools_running()
                    self.state.pt_found = running
                    if not running or not port_open(31416):
                        time.sleep(2)
                        continue
                    self.connect()
                    prev_end = time.monotonic()
                st = self.state
                with self.lock:
                    ts = self.engine.transport_state()
                    playing = ts in ("TS_TransportPlaying", "TS_TransportRecording", "TS_TransportPlayingHalfSpeed",
                                     "TS_TransportRecordingHalfSpeed")
                    now = time.monotonic()
                    if playing and not st.ptsl_playing:
                        with st.lock:   # play iniciado no Pro Tools: comecou entre a leitura anterior e esta
                            st.est_start = st.sel_seconds
                            st.est_at = (prev_end + now) / 2 - self.PTSL_LAG
                            st.ptsl_playing = True
                        if st.manual_line is not None:
                            st.manual_line = None
                    elif not playing and st.ptsl_playing:
                        with st.lock:
                            st.sel_seconds = st.est_start + (now - st.est_at)
                            st.sel_at = now
                            st.ptsl_playing = False
                    prev_end = now
                    if not playing and n % 3 == 0:
                        try:
                            from ptsl.PTSL_pb2 import TLType_Seconds
                            i, o = self.engine.get_timeline_selection(TLType_Seconds)
                            with st.lock:
                                st.sel_seconds = float(i)
                                st.sel_at = time.monotonic()
                        except Exception:
                            pass
                    if n % 10 == 0:
                        try:
                            name = self.engine.session_name()
                            if name != st.session:
                                log("sessao no Pro Tools (PTSL):", name)
                                st.session = name
                                st.manual_line = None
                                st.session_path = None
                            if CFG.get("sessao_auto", True) and st.session_path is None:
                                p = self.engine.session_path()
                                st.session_path = p
                                if add_session_folder(p):
                                    LIB.save()
                        except Exception as ex:
                            if "NoOpenedSession" in str(ex):
                                if st.session is not None:
                                    log("sessao fechada")
                                st.session = None
                                st.session_path = None
                            else:
                                raise
                n += 1
                time.sleep(self.poll_s)
            except Exception as e:
                msg = str(e)
                if "NoOpenedSession" in msg:
                    self.state.session = None
                    self.state.ptsl_playing = False
                    time.sleep(1)
                    continue
                self.drop(e)
                time.sleep(3)

    def _secs(self, sec):
        return "%.3f" % max(0.0, float(sec))

    def locate(self, sec):
        from ptsl.PTSL_pb2 import TLType_Seconds
        with self.lock:
            self.engine.set_timeline_selection(in_time=self._secs(sec), location_type=TLType_Seconds)
            with self.state.lock:
                self.state.sel_seconds = float(sec)
                self.state.sel_at = time.monotonic()

    def play(self, sec=None):
        with self.lock:
            if self.state.ptsl_playing:
                if sec is None:
                    return
                self.engine.toggle_play_state()
                self.state.ptsl_playing = False
                time.sleep(0.05)
            if sec is not None:
                self.locate(sec)
            else:
                sec = self.state.sel_seconds
            self.engine.toggle_play_state()
            with self.state.lock:
                self.state.est_start = float(sec)
                self.state.est_at = time.monotonic() + 0.04
                self.state.ptsl_playing = True
            self.state.manual_line = None

    def stop(self):
        with self.lock:
            if self.state.ptsl_playing or self.engine.transport_state() in ("TS_TransportPlaying", "TS_TransportRecording"):
                self.engine.toggle_play_state()
                now = time.monotonic()
                with self.state.lock:
                    if self.state.ptsl_playing:
                        self.state.sel_seconds = self.state.est_start + (now - self.state.est_at)
                        self.state.sel_at = now
                    self.state.ptsl_playing = False

    def toggle(self):
        if self.state.playing():
            self.stop()
        else:
            self.play()


class PTWatcher(threading.Thread):
    """Reserva (Windows) quando o PTSL nao esta disponivel: le o titulo das janelas 'Edit: Sessao' do Pro Tools."""

    def __init__(self, state):
        super().__init__(daemon=True, name="ptwatch")
        self.state = state

    def run(self):
        if not WIN:
            return
        import win32gui
        pat = re.compile(r"^(Edit|Mix):\s*(.+?)\s*$")
        while True:
            try:
                if self.state.ptsl_ok:
                    time.sleep(2)
                    continue
                titles = []

                def cb(h, _):
                    if win32gui.IsWindowVisible(h):
                        t = win32gui.GetWindowText(h)
                        if t:
                            titles.append(t)
                        if win32gui.GetClassName(h) == "DigiAppWndClass":   # MDI: "Edit: Sessao" e janela FILHA
                            win32gui.EnumChildWindows(h, child_cb, None)

                def child_cb(h, _):
                    if win32gui.IsWindowVisible(h):
                        t = win32gui.GetWindowText(h)
                        if t:
                            titles.append(t)
                win32gui.EnumWindows(cb, None)
                sess = None
                for t in titles:
                    mm = pat.match(t)
                    if mm:
                        sess = mm.group(2)
                        break
                self.state.pt_found = any(t.startswith("Pro Tools") or pat.match(t) for t in titles)
                if sess != self.state.session:
                    log("sessao no Pro Tools (janela):", sess)
                    self.state.session = sess
                    self.state.manual_line = None
            except Exception as e:
                log("erro lendo janelas:", e)
            time.sleep(1)


# ----------------------------------------------------------------------------
# Atualizacao: olha as releases do GitHub
# ----------------------------------------------------------------------------
UPDATE = {"checked": None, "latest": None, "url": None, "asset": None, "notes": None, "msg": None, "busy": False}


def vtuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:3])


def check_update():
    if not CFG.get("checar_atualizacao", True):
        return
    import urllib.request
    try:
        req = urllib.request.Request("https://api.github.com/repos/%s/releases/latest" % REPO,
                                     headers={"User-Agent": "Prompter/" + VERSION, "Accept": "application/vnd.github+json"})
        d = json.load(urllib.request.urlopen(req, timeout=15))
        tag = d.get("tag_name") or ""
        UPDATE["checked"] = time.time()
        UPDATE["latest"] = tag.lstrip("v")
        UPDATE["url"] = d.get("html_url")
        UPDATE["notes"] = (d.get("body") or "")[:600]
        UPDATE["msg"] = None
        asset = None
        for a in d.get("assets") or []:
            n = a.get("name", "").lower()
            if WIN and n.endswith(".exe"):
                asset = a.get("browser_download_url")
            elif MAC and n.endswith(".dmg"):
                import platform
                arch = "arm64" if platform.machine() == "arm64" else "x86_64"
                if arch in n or asset is None:
                    asset = a.get("browser_download_url")
        UPDATE["asset"] = asset
        if vtuple(UPDATE["latest"]) > vtuple(VERSION):
            log("atualizacao disponivel:", UPDATE["latest"])
    except Exception as e:
        UPDATE["checked"] = UPDATE["checked"] or time.time()
        UPDATE["msg"] = "não consegui checar no GitHub: %s" % str(e)[:120]


def update_available():
    return bool(UPDATE["latest"]) and vtuple(UPDATE["latest"]) > vtuple(VERSION)


def update_loop():
    time.sleep(20)
    while True:
        check_update()
        time.sleep(6 * 3600)


def install_update():
    """Windows: baixa o instalador e roda silencioso (ele fecha o Prompter e reabre). macOS: abre o .dmg."""
    if UPDATE["busy"]:
        return
    UPDATE["busy"] = True
    try:
        if not UPDATE["asset"]:
            open_path(UPDATE["url"] or AUTHOR["repo"] + "/releases")
            return
        import urllib.request
        if WIN:
            dst = Path(os.environ.get("TEMP", str(DATA))) / ("PrompterSetup-%s.exe" % UPDATE["latest"])
            UPDATE["msg"] = "baixando a versão %s…" % UPDATE["latest"]
            urllib.request.urlretrieve(UPDATE["asset"], dst)
            UPDATE["msg"] = "instalando…"
            subprocess.Popen([str(dst), "/SILENT", "/NORESTART"], creationflags=NOWIN)
            time.sleep(1)
            os._exit(0)
        else:
            open_path(UPDATE["asset"])
    except Exception as e:
        UPDATE["msg"] = "erro na atualização: %s" % str(e)[:160]
    finally:
        UPDATE["busy"] = False


# ----------------------------------------------------------------------------
# Estado publico para as telas
# ----------------------------------------------------------------------------
def current_view(state):
    sid = state.forced_song or LIB.find_by_session(state.session)
    song = LIB.get(sid) if sid else None
    secs = state.seconds_now()
    line_idx = None
    song_secs = None
    if song:
        song_secs = secs - float(song.get("offset") or 0)
        lines = song.get("lines") or []
        if state.manual_line is not None:
            line_idx = max(0, min(state.manual_line, len(lines) - 1)) if lines else None
        else:
            lead = float(CFG["avanco_segundos"])
            idx = -1
            for i, ln in enumerate(lines):
                if ln["t"] <= song_secs + lead:
                    idx = i
                else:
                    break
            line_idx = idx if idx >= 0 else None
    return {
        "midi": state.midi_ok, "midi_port": state.midi_port, "ptsl": state.ptsl_ok, "protools": state.pt_found,
        "source": state.source(),
        "session": state.session, "playing": state.playing(), "tc": state.tc_text(), "seconds": round(secs, 2),
        "song_id": sid, "song": song["name"] if song else None, "status": song["status"] if song else None,
        "song_seconds": round(song_secs, 2) if song_secs is not None else None,
        "line": line_idx, "manual": state.manual_line is not None, "forced": state.forced_song,
        "n_lines": len(song.get("lines") or []) if song else 0,
        "lead": float(CFG["avanco_segundos"]),
        "progresso": song.get("progresso") if song else None,
        "update": UPDATE["latest"] if update_available() else None,
    }


# ----------------------------------------------------------------------------
# Configuracao do sistema: loopMIDI (Windows), iniciar com o sistema
# ----------------------------------------------------------------------------
LOOPMIDI_EXE = (Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Tobias Erichsen" / "loopMIDI" / "loopMIDI.exe") if WIN else None
SETUP = {"loopmidi_job": None, "loopmidi_msg": None}


def loopmidi_running():
    if not WIN:
        return False
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq loopMIDI.exe"], capture_output=True, creationflags=NOWIN).stdout
        return b"loopMIDI.exe" in out
    except Exception:
        return False


def loopmidi_ensure_port():
    """Windows: cria a porta 'Pro Tools MTC' no registro do loopMIDI e (re)inicia o loopMIDI."""
    if not WIN:
        return
    import winreg
    key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Tobias Erichsen\loopMIDI\Ports")
    winreg.SetValueEx(key, CFG["midi_port_contains"], 0, winreg.REG_DWORD, 1)
    winreg.CloseKey(key)
    try:
        k2 = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Tobias Erichsen\loopMIDI")
        winreg.SetValueEx(k2, "autostart", 0, winreg.REG_DWORD, 1)
        winreg.CloseKey(k2)
        run = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run")
        winreg.SetValueEx(run, "loopMIDI", 0, winreg.REG_SZ, '"%s"' % LOOPMIDI_EXE)
        winreg.CloseKey(run)
    except Exception as e:
        log("autostart do loopMIDI:", e)
    if loopmidi_running():
        subprocess.run(["taskkill", "/IM", "loopMIDI.exe", "/F"], capture_output=True, creationflags=NOWIN)
        time.sleep(1)
    if LOOPMIDI_EXE.exists():
        subprocess.Popen([str(LOOPMIDI_EXE)], creationflags=NOWIN)


def install_loopmidi_job():
    """Windows: instala o loopMIDI (instalador oficial embutido, se houver; senao winget) e cria a porta."""
    try:
        if not LOOPMIDI_EXE.exists():
            bundled = BASE / "vendor" / "loopMIDISetup.exe"
            if bundled.exists():
                SETUP["loopmidi_msg"] = "instalando o loopMIDI (pede permissão de administrador)…"
                import ctypes
                r = ctypes.windll.shell32.ShellExecuteW(None, "runas", str(bundled), "/quiet /norestart", None, 0)
                t0 = time.time()
                while not LOOPMIDI_EXE.exists() and time.time() - t0 < 180 and r > 32:
                    time.sleep(2)
            if not LOOPMIDI_EXE.exists():
                SETUP["loopmidi_msg"] = "instalando o loopMIDI (winget)…"
                subprocess.run(["winget", "install", "--id", "TobiasErichsen.loopMIDI", "-e", "--silent",
                                "--accept-package-agreements", "--accept-source-agreements"],
                               capture_output=True, text=True, encoding="utf-8", errors="replace",
                               creationflags=NOWIN, timeout=900)
            if not LOOPMIDI_EXE.exists():
                SETUP["loopmidi_msg"] = "não consegui instalar. Baixe em tobias-erichsen.de/software/loopmidi.html, instale e clique de novo."
                return
        SETUP["loopmidi_msg"] = "criando a porta MIDI…"
        loopmidi_ensure_port()
        time.sleep(2)
        SETUP["loopmidi_msg"] = "loopMIDI pronto e porta criada. Agora ligue o MTC no Pro Tools (passos ao lado)."
    except Exception as e:
        SETUP["loopmidi_msg"] = "erro: %s" % str(e)[:200]
    finally:
        SETUP["loopmidi_job"] = None


LAUNCH_AGENT = Path.home() / "Library" / "LaunchAgents" / "com.krocksss.prompter.plist"


def autostart_get():
    if WIN:
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run")
            v, _ = winreg.QueryValueEx(k, "Prompter")
            return bool(v)
        except Exception:
            return False
    return LAUNCH_AGENT.exists()


def autostart_set(on):
    if WIN:
        import winreg
        k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run")
        if on:
            exe = ('"%s"' % sys.executable) if FROZEN else '"%s" "%s"' % (sys.executable.replace("python.exe", "pythonw.exe"), BASE / "app.py")
            winreg.SetValueEx(k, "Prompter", 0, winreg.REG_SZ, exe)
        else:
            try:
                winreg.DeleteValue(k, "Prompter")
            except FileNotFoundError:
                pass
        winreg.CloseKey(k)
        return
    if on:
        args = "<string>%s</string>" % sys.executable + ("" if FROZEN else "<string>%s</string>" % (BASE / "app.py"))
        LAUNCH_AGENT.parent.mkdir(parents=True, exist_ok=True)
        LAUNCH_AGENT.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                                '<plist version="1.0"><dict><key>Label</key><string>com.krocksss.prompter</string>'
                                '<key>ProgramArguments</key><array>%s</array><key>RunAtLoad</key><true/></dict></plist>\n' % args)
    elif LAUNCH_AGENT.exists():
        LAUNCH_AGENT.unlink()


def setup_status(state, transcriber, ptlink):
    try:
        import mido
        ports = mido.get_input_names()
    except Exception:
        ports = []
    return {
        "version": VERSION, "frozen": FROZEN, "porta": CFG["porta"], "os": "win" if WIN else ("mac" if MAC else "linux"),
        "author": AUTHOR,
        "pt_running": state.pt_found, "pt_exe": protools_exe(), "ptsl": state.ptsl_ok, "ptsl_version": ptlink.version, "ptsl_err": ptlink.err,
        "session": state.session, "session_path": state.session_path,
        "loopmidi_installed": bool(LOOPMIDI_EXE and LOOPMIDI_EXE.exists()) if WIN else True, "loopmidi_running": loopmidi_running() if WIN else True,
        "midi_ports": ports, "midi_port_ok": state.midi_ok, "midi_port": state.midi_port, "mtc_live": state.mtc_live(),
        "mtc_seen": state.tc_at > 0, "loopmidi_msg": SETUP["loopmidi_msg"], "loopmidi_job": SETUP["loopmidi_job"] is not None,
        "whisper_model": CFG["modelo_whisper"], "whisper_cached": transcriber.whisper_cached() is not None,
        "demucs_cached": transcriber.demucs_cached(), "transcribing": transcriber.current,
        "autostart": autostart_get(), "pasta_musicas": CFG["pasta_musicas"], "n_songs": len(LIB.songs),
        "data_dir": str(DATA), "log": str(LOG_PATH),
        "update": {"available": update_available(), "latest": UPDATE["latest"], "url": UPDATE["url"], "asset": UPDATE["asset"],
                   "notes": UPDATE["notes"], "msg": UPDATE["msg"], "busy": UPDATE["busy"], "checked": UPDATE["checked"]},
    }


# ----------------------------------------------------------------------------
# Servidor web (aiohttp) - tela do prompter, estudio, configuracao e API
# ----------------------------------------------------------------------------
def run_web(state, transcriber, ptlink):
    import asyncio
    from aiohttp import web

    def page(name):
        async def h(req):
            return web.FileResponse(STATIC / name, headers={"Cache-Control": "no-cache"})
        return h

    async def api_state(req):
        return web.json_response(current_view(state))

    async def api_stream(req):
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache",
                                           "X-Accel-Buffering": "no"})
        await resp.prepare(req)
        last = None
        n = 0
        try:
            while True:
                v = current_view(state)
                key = (v["song_id"], v["line"], v["playing"], v["midi"], v["ptsl"], v["protools"], v["session"],
                       v["status"], v["manual"], v["n_lines"], json.dumps(v["progresso"]), v["update"])
                n += 1
                if key != last or n % 5 == 0:
                    await resp.write(("data: " + json.dumps(v, ensure_ascii=False) + "\n\n").encode())
                    last = key
                await asyncio.sleep(0.1)
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        return resp

    async def api_songs(req):
        return web.json_response({"songs": LIB.public(), "config": CFG})

    async def api_song_get(req):
        s = LIB.get(req.match_info["sid"])
        if not s:
            raise web.HTTPNotFound()
        return web.json_response(s)

    async def api_song_audio(req):
        s = LIB.get(req.match_info["sid"])
        if not s:
            raise web.HTTPNotFound()
        cands = [s.get("source")] + list(s.get("originals") or []) + list(s.get("candidates") or [])
        for p in cands:
            if p and os.path.exists(p):
                return web.FileResponse(p, headers={"Cache-Control": "no-cache"})
        raise web.HTTPNotFound()

    def merge_lines(s, new):
        """Recebe linhas do estudio [{t,end,text,words?}] e devolve linhas com tempo por palavra coerente."""
        old = s.get("lines") or []
        out = []
        for l in new:
            txt = str(l.get("text", "")).strip()
            if not txt:
                continue
            t = float(l["t"])
            end = float(l.get("end") or 0) or None
            words = l.get("words") if isinstance(l.get("words"), list) and l.get("words") else None
            if words is None:
                o = next((x for x in old if x.get("words") and x["text"] == txt), None) or \
                    next((x for x in old if x.get("words") and abs(x["t"] - t) < 0.01), None)
                if o:
                    ow = o["words"]
                    if abs(o["t"] - t) > 0.01:
                        ow = shift_words(ow, t - o["t"])
                    words = reflow_words(txt, ow, t, end or o.get("end"))
                else:
                    words = reflow_words(txt, None, t, end)
            if not end:
                end = words[-1]["e"] if words else t + 3
            out.append({"t": round(t, 2), "end": round(float(end), 2), "text": txt, "words": words})
        out.sort(key=lambda x: x["t"])
        for i in range(len(out) - 1):
            if out[i]["end"] > out[i + 1]["t"]:
                out[i]["end"] = out[i + 1]["t"]
        return out

    async def api_song_put(req):
        s = LIB.get(req.match_info["sid"])
        if not s:
            raise web.HTTPNotFound()
        body = await req.json()
        with LIB.lock:
            if "lines" in body:
                if body.get("realign") and s.get("words"):
                    s["lines"] = align_lyrics("\n".join(str(l.get("text", "")).strip() for l in body["lines"]), s["words"])
                    s["status"] = "alinhado"
                else:
                    s["lines"] = merge_lines(s, body["lines"])
                    if s["status"] in ("pronto", "manual", "sem-voz", "alinhado"):
                        s["status"] = "manual"
            if "official" in body:
                s["official"] = str(body["official"])
                if s.get("words"):
                    s["lines"] = align_lyrics(s["official"], s["words"])
                    s["status"] = "alinhado"
                else:
                    txt = [l.strip() for l in s["official"].splitlines() if l.strip()]
                    dur = float(body.get("dur") or s.get("duracao") or 240)
                    step = dur / max(1, len(txt))
                    s["lines"] = [{"t": round(i * step, 2), "end": round((i + 1) * step, 2), "text": t}
                                  for i, t in enumerate(txt)]
                    s["status"] = "manual"
            if "offset" in body:
                s["offset"] = float(body["offset"])
            if "name" in body and str(body["name"]).strip():
                s["name"] = str(body["name"]).strip()
            if "session_alias" in body:
                s["session_alias"] = (str(body["session_alias"]).strip() or None)
        LIB.save()
        return web.json_response({"ok": True, "song": s})

    async def api_upload(req):
        """Musica arrastada/escolhida no estudio: salva em pasta_musicas/<nome>/, entra na biblioteca,
        fica vinculada a sessao aberta no Pro Tools e vai para a fila de transcricao."""
        reader = await req.multipart()
        saved = []
        link = None
        while True:
            part = await reader.next()
            if part is None:
                break
            if part.name == "session_alias":
                link = (await part.text()).strip() or None
                continue
            if part.name != "file" or not part.filename:
                continue
            fname = os.path.basename(part.filename)
            if Path(fname).suffix.lower() not in AUDIO_EXT:
                continue
            stem = Path(fname).stem
            folder = Path(CFG["pasta_musicas"]) / stem
            folder.mkdir(parents=True, exist_ok=True)
            dst = folder / fname
            tmp = folder / (fname + ".enviando")
            with open(tmp, "wb") as f:   # grava num temporario: o arquivo escolhido pode SER o proprio destino
                while True:
                    chunk = await part.read_chunk(1024 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
            if dst.exists() and dst.stat().st_size == tmp.stat().st_size:
                tmp.unlink()   # mesmo arquivo, ja esta na pasta
            else:
                os.replace(tmp, dst)
            saved.append((stem, dst))
        if not saved:
            return web.json_response({"ok": False, "erro": "nenhum arquivo de áudio recebido"}, status=400)
        sids = []
        for stem, dst in saved:
            register({stem: {"name": stem, "folder": str(dst.parent), "originals": [str(dst)], "session_audio": []}})
            sid = norm(stem).replace(" ", "-") or stem
            s = LIB.get(sid)
            with LIB.lock:
                if s is not None:
                    s["status"] = "pendente"
                    s["erro"] = None
                    s["fonte_forcada"] = str(dst)
                    alias = link if link is not None else state.session
                    if alias and norm(alias) != norm(stem) and norm(alias) not in ("untitled", "sem titulo", "new session"):
                        s["session_alias"] = alias
            sids.append(sid)
            log("musica recebida no estudio:", fname if False else dst.name, "-> sessao", link or state.session)
        LIB.save()
        transcriber.wake.set()
        return web.json_response({"ok": True, "song_ids": sids, "song_id": sids[0]})

    async def api_song_retry(req):
        """Retranscreve. body.source = caminho de UMA faixa (arquivo de audio) para transcrever so ela."""
        s = LIB.get(req.match_info["sid"])
        if not s:
            raise web.HTTPNotFound()
        body = {}
        try:
            body = await req.json()
        except Exception:
            pass
        with LIB.lock:
            s["status"] = "pendente"
            s["erro"] = None
            src = body.get("source")
            if src and os.path.exists(src):
                s["fonte_forcada"] = src
            if body.get("keep_lines") is False:
                s["official"] = None
        LIB.save()
        transcriber.wake.set()
        return web.json_response({"ok": True})

    async def api_song_delete(req):
        with LIB.lock:
            LIB.songs.pop(req.match_info["sid"], None)
        LIB.save()
        return web.json_response({"ok": True})

    async def api_transport(req):
        """Comanda o Pro Tools: play/stop/locate/toggle. seconds = tempo DA MUSICA (o offset e somado)."""
        body = await req.json()
        act = body.get("action")
        if not state.ptsl_ok:
            return web.json_response({"ok": False, "erro": "Pro Tools não conectado (PTSL)"}, status=409)
        off = 0.0
        if body.get("song_id"):
            s = LIB.get(body["song_id"])
            off = float(s.get("offset") or 0) if s else 0.0
        sec = None if body.get("seconds") is None else float(body["seconds"]) + off
        try:
            if act == "play":
                await asyncio.to_thread(ptlink.play, sec)
            elif act == "stop":
                await asyncio.to_thread(ptlink.stop)
            elif act == "locate":
                if state.playing():
                    await asyncio.to_thread(ptlink.play, sec)
                else:
                    await asyncio.to_thread(ptlink.locate, sec)
            elif act == "toggle":
                await asyncio.to_thread(ptlink.toggle)
        except Exception as e:
            log("erro no transporte:", e)
            return web.json_response({"ok": False, "erro": str(e)[:200]}, status=500)
        return web.json_response(dict(current_view(state), ok=True))

    async def api_control(req):
        body = await req.json()
        act = body.get("action")
        if act == "force_song":
            state.forced_song = body.get("song_id") or None
            state.manual_line = None
        elif act == "manual_line":
            state.manual_line = int(body["line"]) if body.get("line") is not None else None
        elif act == "next":
            v = current_view(state)
            base = v["line"] if v["line"] is not None else -1
            state.manual_line = min(base + 1, max(v["n_lines"] - 1, 0))
        elif act == "prev":
            v = current_view(state)
            base = v["line"] if v["line"] is not None else 0
            state.manual_line = max(base - 1, 0)
        elif act == "auto":
            state.manual_line = None
        elif act == "rescan":
            scan_folder()
            if state.session_path:
                add_session_folder(state.session_path)
            transcriber.wake.set()
        elif act == "calibrate":
            s = LIB.get(body["song_id"])
            if s and s.get("lines"):
                ln = s["lines"][int(body["line"])]
                with LIB.lock:
                    s["offset"] = round(state.seconds_now() - ln["t"], 2)
                LIB.save()
        elif act == "config":
            for k in ("pasta_musicas", "idioma", "modelo_whisper", "avanco_segundos", "separar_vocal", "sessao_auto",
                      "abrir_navegador", "abrir_protools", "checar_atualizacao"):
                if k in body:
                    CFG[k] = body[k]
            save_cfg(CFG)
            scan_folder()
            transcriber.wake.set()
        return web.json_response(current_view(state))

    async def api_setup(req):
        return web.json_response(setup_status(state, transcriber, ptlink))

    async def api_setup_post(req):
        body = await req.json()
        act = body.get("action")
        if act == "install_loopmidi":
            if WIN and SETUP["loopmidi_job"] is None:
                SETUP["loopmidi_job"] = threading.Thread(target=install_loopmidi_job, daemon=True)
                SETUP["loopmidi_job"].start()
        elif act == "create_port":
            await asyncio.to_thread(loopmidi_ensure_port)
        elif act == "autostart":
            autostart_set(bool(body.get("on")))
        elif act == "download_models":
            transcriber.preload = True
            transcriber.wake.set()
        elif act == "open_folder":
            Path(CFG["pasta_musicas"]).mkdir(parents=True, exist_ok=True)
            open_path(CFG["pasta_musicas"])
        elif act == "open_log":
            open_path(LOG_PATH)
        elif act == "monitor2":
            open_monitor2()
        elif act == "open_protools":
            await asyncio.to_thread(launch_protools)
        elif act == "check_update":
            await asyncio.to_thread(check_update)
        elif act == "install_update":
            threading.Thread(target=install_update, daemon=True).start()
        return web.json_response(setup_status(state, transcriber, ptlink))

    app = web.Application(client_max_size=2 * 1024 * 1024 * 1024)
    app.router.add_get("/", page("index.html"))
    app.router.add_get("/editar", page("editar.html"))
    app.router.add_get("/estudio", page("editar.html"))
    app.router.add_get("/config", page("config.html"))
    app.router.add_get("/api/state", api_state)
    app.router.add_get("/api/stream", api_stream)
    app.router.add_get("/api/songs", api_songs)
    app.router.add_get("/api/song/{sid}", api_song_get)
    app.router.add_get("/api/song/{sid}/audio", api_song_audio)
    app.router.add_put("/api/song/{sid}", api_song_put)
    app.router.add_post("/api/song/{sid}/retry", api_song_retry)
    app.router.add_delete("/api/song/{sid}", api_song_delete)
    app.router.add_post("/api/upload", api_upload)
    app.router.add_post("/api/control", api_control)
    app.router.add_post("/api/transport", api_transport)
    app.router.add_get("/api/setup", api_setup)
    app.router.add_post("/api/setup", api_setup_post)
    app.router.add_static("/static", STATIC)
    log("tela em http://localhost:%d  (estudio: /estudio, configuracao: /config)" % CFG["porta"])
    web.run_app(app, host=None, port=int(CFG["porta"]), print=None, handle_signals=False)  # IPv4 e IPv6


# ----------------------------------------------------------------------------
# Bandeja
# ----------------------------------------------------------------------------
def open_monitor2():
    url = "http://localhost:%d" % CFG["porta"]
    if WIN:
        subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(BASE / "abrir-monitor2.ps1"), url],
                         creationflags=NOWIN)
    else:
        webbrowser.open(url)


def tray(state):
    import pystray
    from PIL import Image, ImageDraw
    ico = STATIC / ("prompter.png" if MAC else "prompter.ico")
    if ico.exists():
        img = Image.open(ico)
    else:
        img = Image.new("RGB", (64, 64), (12, 12, 14))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((6, 6, 58, 58), 12, fill=(28, 28, 32), outline=(120, 220, 160), width=3)
        for y in (22, 32, 42):
            d.rectangle((16, y, 48, y + 4), fill=(235, 235, 240) if y == 32 else (110, 110, 120))
    url = "http://localhost:%d" % CFG["porta"]
    menu = pystray.Menu(
        pystray.MenuItem("Abrir prompter", lambda: webbrowser.open(url), default=True),
        pystray.MenuItem("Abrir no monitor 2 (tela cheia)", lambda: open_monitor2()),
        pystray.MenuItem("Estúdio de letras", lambda: webbrowser.open(url + "/estudio")),
        pystray.MenuItem("Abrir o Pro Tools", lambda: threading.Thread(target=launch_protools, daemon=True).start()),
        pystray.MenuItem("Configuração / primeiros passos", lambda: webbrowser.open(url + "/config")),
        pystray.MenuItem("Pasta das músicas", lambda: (Path(CFG["pasta_musicas"]).mkdir(parents=True, exist_ok=True), open_path(CFG["pasta_musicas"]))),
        pystray.MenuItem("Sair", lambda icon: (icon.stop(), os._exit(0))),
    )
    icon = pystray.Icon("prompter", img, "Prompter Pro Tools", menu)
    icon.run()


def main():
    if "--demucs" in sys.argv:
        i = sys.argv.index("--demucs")
        demucs_worker(sys.argv[i + 1:])
        return
    url = "http://localhost:%d" % CFG["porta"]
    if port_open(int(CFG["porta"])):
        # ja tem um Prompter rodando: so abre a tela (e o Pro Tools, se pedido)
        if CFG.get("abrir_protools", True):
            launch_protools()
        webbrowser.open(url)
        return
    log("=== Prompter %s iniciando (%s, %s) ===" % (VERSION, "instalado" if FROZEN else "fonte", sys.platform))
    with LIB.lock:   # musica que deu erro na ultima vez tenta de novo
        for s in LIB.songs.values():
            if s.get("status") == "erro":
                s["status"] = "pendente"
                s["erro"] = None
    state = State()
    try:
        import mido
        mido.get_input_names()   # carrega o backend MIDI na thread principal (evita corrida de import entre threads)
    except Exception as e:
        log("MIDI indisponivel:", e)
    scan_folder()
    tr = Transcriber(state)
    link = PTLink(state)
    MTCReader(state).start()
    PTWatcher(state).start()
    link.start()
    if "--sem-transcricao" not in sys.argv:
        tr.start()
    threading.Thread(target=run_web, args=(state, tr, link), daemon=True, name="web").start()
    threading.Thread(target=update_loop, daemon=True, name="update").start()
    first = not (DATA / ".welcome").exists()
    if first:
        (DATA / ".welcome").write_text(time.strftime("%Y-%m-%d %H:%M"))
    if CFG.get("abrir_protools", True) and "--sem-protools" not in sys.argv:
        threading.Thread(target=launch_protools, daemon=True).start()
    if (CFG.get("abrir_navegador", True) or first) and "--sem-navegador" not in sys.argv:
        time.sleep(1.2)
        webbrowser.open(url + ("/config" if first else ""))
    if "--sem-bandeja" in sys.argv:
        while True:
            time.sleep(3600)
    tray(state)


if __name__ == "__main__":
    main()
