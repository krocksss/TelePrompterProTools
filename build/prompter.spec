# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec do Prompter (Windows: dist/Prompter/ onedir; macOS: dist/Prompter.app).
# Leva python, torch (CPU), demucs, faster-whisper, PyAV, mido/rtmidi, ptsl (gRPC), aiohttp, pystray.
# Modelos NAO vao junto (baixam na 1a transcricao para ~/.cache).
import os, sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).parent
MAC = sys.platform == "darwin"
datas = [(str(ROOT / "static"), "static")]
if not MAC:
    datas.append((str(ROOT / "abrir-monitor2.ps1"), "."))
binaries = []
hiddenimports = ["ptsl", "ptsl.ops", "ptsl.engine", "ptsl.client", "ptsl.errors", "ptsl.PTSL_pb2", "ptsl.PTSL_pb2_grpc",
                 "mido.backends.rtmidi", "rtmidi", "PIL.Image", "PIL.ImageDraw", "soundfile", "av", "wave",
                 "demucs.api", "demucs.pretrained", "demucs.htdemucs", "demucs.hdemucs", "demucs.apply",
                 "faster_whisper", "ctranslate2", "huggingface_hub", "tokenizers", "onnxruntime",
                 "aiohttp", "grpc", "google.protobuf",
                 "numpy.core", "numpy.core.multiarray", "numpy.core._multiarray_umath", "numpy._core", "numpy._core.multiarray"]
hiddenimports += ["pystray._darwin", "AppKit", "Foundation", "objc"] if MAC else ["pystray._win32", "win32gui", "win32api", "win32process", "winreg"]
for pkg in ("demucs", "faster_whisper", "ctranslate2", "av", "soundfile", "julius", "openunmix", "einops",
            "grpc", "ptsl", "huggingface_hub", "tokenizers", "onnxruntime", "dora", "treetable",
            "lameenc", "pystray", "mido", "rtmidi"):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception as e:
        print("collect_all falhou (ok se opcional):", pkg, e)
for pkg in ("torch", "demucs", "faster_whisper", "ctranslate2", "huggingface_hub", "tokenizers", "av", "soundfile"):
    try:
        datas += copy_metadata(pkg)
    except Exception:
        pass
hiddenimports += collect_submodules("torch.nn") + collect_submodules("torch.utils.data")

a = Analysis(
    [str(ROOT / "app.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=list(dict.fromkeys(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "IPython", "jupyter", "notebook", "pytest", "numba", "llvmlite", "librosa",
              "resampy", "sklearn", "scipy", "pandas", "torch.utils.tensorboard", "tensorboard", "torchvision",
              "triton", "cv2", "sympy.testing", "tensorflow", "keras", "onnx"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Prompter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(ROOT / "static" / ("prompter.icns" if MAC and (ROOT / "static" / "prompter.icns").exists() else "prompter.ico")),
    version=None if MAC else str(ROOT / "build" / "version.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Prompter")
if MAC:
    app = BUNDLE(coll, name="Prompter.app", icon=str(ROOT / "static" / "prompter.icns") if (ROOT / "static" / "prompter.icns").exists() else None,
                 bundle_identifier="com.krocksss.prompter",
                 info_plist={"CFBundleName": "Prompter", "CFBundleDisplayName": "Prompter", "CFBundleShortVersionString": "2.0.0",
                             "LSUIElement": True, "NSHighResolutionCapable": True, "LSMinimumSystemVersion": "12.0",
                             "NSHumanReadableCopyright": "Marllon Machado - github.com/krocksss"})
