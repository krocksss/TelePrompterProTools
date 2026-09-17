# Teste automatico: finge o Pro Tools (janela "Edit: <musica>" + MTC) e imprime a linha que o prompter mostra.
import sys, time, threading, json, urllib.request, tkinter as tk
from fake_protools import MTCGen

name = sys.argv[1] if len(sys.argv) > 1 else "Minha Musica Teste"
start = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
dur = float(sys.argv[3]) if len(sys.argv) > 3 else 20.0

root = tk.Tk(); root.title("Edit: " + name); root.geometry("300x80+900+80")
gen = MTCGen()

def run():
    time.sleep(2.5)
    gen.locate(start); time.sleep(0.5)
    gen.playing = True
    t0 = time.time()
    last = None
    while time.time() - t0 < dur:
        v = json.load(urllib.request.urlopen("http://127.0.0.1:8797/api/state"))
        key = (v["song"], v["line"], v["playing"])
        if key != last:
            print("%5.1fs  tc=%s play=%s song=%s line=%s" % (time.time() - t0, v["tc"], v["playing"], v["song"], v["line"]), flush=True)
            last = key
        time.sleep(0.2)
    gen.playing = False; gen.locate(gen.pos); time.sleep(0.6)
    v = json.load(urllib.request.urlopen("http://127.0.0.1:8797/api/state"))
    print("STOP   tc=%s play=%s line=%s" % (v["tc"], v["playing"], v["line"]), flush=True)
    root.after(0, root.destroy)

threading.Thread(target=run, daemon=True).start()
root.mainloop()
