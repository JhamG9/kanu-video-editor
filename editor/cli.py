"""Uso desde terminal (lo usa Claude para trabajar sin abrir el editor).

  python3 editor/cli.py stock [clip ...] [--rehacer] [--probar]
        TODO en un paso: corrige color, ruido, estabilización y enderezado, y exporta la versión final
        4K a "videos subir/". Sin clips: solo los que aún no tienen su final. Respeta los clips que
        ajustaste a mano (estado manual/aprobado). --probar solo muestra qué haría, sin exportar.
  python3 editor/cli.py auto [clip ...]          corrección automática (todos si no se indica)
  python3 editor/cli.py export PRESET [clip ...] exporta (presets: 4k_h264, 4k_hevc10, 4k_prores, 1080_h264, vertical_h264)
  python3 editor/cli.py estado                    resumen de ajustes por clip
  python3 editor/cli.py limpiar                   borra intermedios estabilizados y fotogramas temporales
"""
import json
import sys
import time

import media
import project


def final_path(name):
    return project.SUBIR / (name.rsplit(".", 1)[0] + "." + media.PRESETS["4k_h264"]["ext"])


def stock(names, redo=False, dry=False):
    """Flujo completo para stock. Lo usa Claude cuando le pasan una tanda nueva de videos."""
    names = names or [n for n in project.clips() if redo or not final_path(n).exists()]
    if not names:
        print('Todos los clips ya tienen su final en "videos subir/". Usa --rehacer para repetirlos.')
        return
    rows = []
    for n in names:
        t = time.time()
        s = project.load(n)
        if s["status"] in ("manual", "aprobado"):  # tus ajustes nunca se pisan, ni con --rehacer
            nota = "ajustes tuyos (no se tocan)"
        else:
            s = project.auto(n)
            nota = "auto"
        i = project.clip_info(n)
        pl = i["plan"]
        rows.append((n, nota, s["denoise"], s["stabilize"], s.get("rotate") or 0, len(i["segments"]), pl["clip_len"],
                     pl["speed"], round(time.time() - t, 1)))
        r = rows[-1]
        print(f"{n}: {r[1]} · ruido {r[2]} · estab. {r[3]} · giro {r[4]:+.1f}° · "
              f"{r[5]} clip(s) de {r[6]} s{f' a {r[7]:.2f}×' if r[7] > 1.001 else ''} ({r[8]} s)", flush=True)
    if dry:
        print("\n--probar: no se exportó nada.")
        return
    ex = project.Exporter(workers=2)
    ex.add(names, ["4k_h264"], keep_audio=False, to_upload=True)
    t0 = time.time()
    cleaned = set()
    while True:
        jobs = ex.list()
        pend = [j for j in jobs if j["status"] in ("en cola", "procesando", "estabilizando")]
        # cada estabilizado ocupa ~2.5 GB: se borra en cuanto su clip termina (en tandas grandes llenaría el disco)
        for c in {j["clip"] for j in jobs} - {j["clip"] for j in pend} - cleaned:
            project.finish_clip(c)  # copia ligera estabilizada para el visor + borra el intermedio grande
            cleaned.add(c)
        print(f"\rExportando: {len(jobs) - len(pend)}/{len(jobs)} listos · {int(time.time() - t0)} s", end="", flush=True)
        if not pend:
            break
        time.sleep(2)
    print()
    bad = [j for j in jobs if j["status"] != "listo"]
    for j in jobs:
        print(("✓ " if j["status"] == "listo" else "✗ ") + j["out"] + ("" if j["status"] == "listo" else f"  {j['status']}: {(j['error'] or '')[:300]}"))
    print(f"\n{len(jobs) - len(bad)} de {len(jobs)} archivos listos en \"videos subir/\".")


def main(argv):
    if not argv:
        print(__doc__)
        return
    cmd, rest = argv[0], argv[1:]
    if cmd == "auto":
        for n in rest or project.clips():
            t = time.time()
            s = project.auto(n)
            print(f"{n}: listo en {time.time() - t:.1f}s · ruido {s['auto']['noise']} ({s['denoise']}) · "
                  + "; ".join(s["auto"]["why"]))
    elif cmd == "export":
        preset, names = rest[0], rest[1:] or project.clips()
        ex = project.Exporter(workers=2)
        ex.add(names, [preset])
        while True:
            jobs = ex.list()
            pend = [j for j in jobs if j["status"] in ("en cola", "procesando", "estabilizando")]
            done = len(jobs) - len(pend)
            print(f"\r{done}/{len(jobs)} listos", end="", flush=True)
            if not pend:
                break
            time.sleep(1)
        print()
        for j in jobs:
            print(j["status"], j["out"], j.get("seconds", ""), (j["error"] or "")[:300])
    elif cmd == "stock":
        stock([a for a in rest if not a.startswith("--")], "--rehacer" in rest, "--probar" in rest)
    elif cmd == "limpiar":
        print(f"Liberados {project.clean_cache() / 1e9:.1f} GB")
    elif cmd == "estado":
        for n in project.clips():
            i = project.clip_info(n)
            s = i["settings"]
            print(n, s["status"], f"{len(i['segments'])} clip(s)", json.dumps({k: s[k] for k in media.grade.COLOR_KEYS}))
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
