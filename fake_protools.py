# -*- coding: utf-8 -*-
"""
Simulador do Pro Tools para testar o prompter SEM o Pro Tools instalado.
Abre uma janela com titulo "Edit: <musica>" (igual ao Pro Tools) e manda MTC
pela porta loopMIDI "Pro Tools MTC" quando voce aperta Play.
"""
import sys, time, threading, tkinter as tk
from tkinter import ttk
import mido

PORT_CONTAINS = "Pro Tools MTC"
RATE = 30.0
RATE_CODE = 3  # 30 fps


class MTCGen:
    def __init__(self):
        names = [n for n in mido.get_output_names() if PORT_CONTAINS.lower() in n.lower()]
        if not names:
            raise SystemExit("porta loopMIDI '%s' nao encontrada. Abra o loopMIDI." % PORT_CONTAINS)
        self.out = mido.open_output(names[0])
        self.pos = 0.0          # segundos
        self.playing = False
        self.lock = threading.Lock()
        threading.Thread(target=self.loop, daemon=True).start()

    def hmsf(self):
        p = self.pos
        h = int(p // 3600); m = int(p % 3600 // 60); s = int(p % 60); f = int((p - int(p)) * RATE)
        return h, m, s, f

    def locate(self, seconds):
        with self.lock:
            self.pos = max(0.0, seconds)
            h, m, s, f = self.hmsf()
        self.out.send(mido.Message("sysex", data=[0x7F, 0x7F, 0x01, 0x01, (RATE_CODE << 5) | h, m, s, f]))

    def loop(self):
        while True:
            if not self.playing:
                time.sleep(0.05)
                continue
            with self.lock:
                h, m, s, f = self.hmsf()
            vals = [f & 0xF, f >> 4, s & 0xF, s >> 4, m & 0xF, m >> 4, h & 0xF, ((h >> 4) & 1) | (RATE_CODE << 1)]
            t0 = time.perf_counter()
            for i, v in enumerate(vals):
                self.out.send(mido.Message("quarter_frame", frame_type=i, frame_value=v))
                # 8 quarter frames por 2 frames
                target = t0 + (i + 1) * (2.0 / RATE) / 8
                while time.perf_counter() < target:
                    time.sleep(0.001)
            with self.lock:
                self.pos += 2.0 / RATE


def main():
    gen = MTCGen()
    root = tk.Tk()
    root.geometry("560x200+80+80")
    name = tk.StringVar(value=sys.argv[1] if len(sys.argv) > 1 else "Minha Musica Teste")

    def set_title(*_):
        root.title("Edit: " + name.get())
    set_title()
    name.trace_add("write", set_title)

    frm = ttk.Frame(root, padding=14); frm.pack(fill="both", expand=True)
    ttk.Label(frm, text="Sessao (vira o titulo 'Edit: ...' como no Pro Tools)").pack(anchor="w")
    ttk.Entry(frm, textvariable=name, width=50).pack(fill="x")
    pos = tk.StringVar(value="00:00:00:00")
    ttk.Label(frm, textvariable=pos, font=("Consolas", 22)).pack(pady=8)
    btns = ttk.Frame(frm); btns.pack()
    ttk.Button(btns, text="|<  inicio", command=lambda: gen.locate(0)).pack(side="left", padx=4)
    ttk.Button(btns, text="Play", command=lambda: setattr(gen, "playing", True)).pack(side="left", padx=4)
    ttk.Button(btns, text="Stop", command=lambda: (setattr(gen, "playing", False), gen.locate(gen.pos))).pack(side="left", padx=4)
    ttk.Button(btns, text="-10s", command=lambda: gen.locate(gen.pos - 10)).pack(side="left", padx=4)
    ttk.Button(btns, text="+10s", command=lambda: gen.locate(gen.pos + 10)).pack(side="left", padx=4)

    def tick():
        h, m, s, f = gen.hmsf()
        pos.set("%02d:%02d:%02d:%02d %s" % (h, m, s, f, "PLAY" if gen.playing else "STOP"))
        root.after(100, tick)
    tick()
    root.mainloop()


if __name__ == "__main__":
    main()
