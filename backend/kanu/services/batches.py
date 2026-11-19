"""Tandas: subir videos con opciones y nota, y procesarlos de una vez."""
import json
import threading
import time


from kanu import config
from kanu.services import export
from kanu.services import library


# ------------------------------------------------------------------ tandas (subir videos + indicaciones)
BATCH_OPTIONS = {
    "estable": "Ya viene estable (trípode, dron o gimbal)",
    "calido": "Conservar colores cálidos (amanecer o atardecer)",
    "sin_ralentizar": "Sin ralentizar",
}


def apply_batch(s):
    """Aplica las opciones de la tanda sobre la corrección automática. Devuelve las razones."""
    b = s.get("batch") or {}
    why = []
    if b.get("estable") and s["stabilize"] != "off":
        s["stabilize"] = "off"
        why.append("tanda: ya viene estable → sin estabilizar")
    if b.get("calido") and (s.get("temperature") or 0) < 0:
        s["temperature"] = 0
        why.append("tanda: conservo los colores cálidos")
    if b.get("sin_ralentizar"):
        s["segment"]["max_slow"] = 1
    if b.get("min") and b.get("max"):
        s["segment"]["min"], s["segment"]["max"] = float(b["min"]), float(b["max"])
    if b.get("nota"):
        why.append("nota de la tanda: " + b["nota"][:200])
    return why


class BatchRunner:
    """Procesa una tanda completa (como `cli.py stock`) dentro del editor."""

    def __init__(self, exporter):
        self.ex = exporter
        self.state = {"running": False}
        self.lock = threading.Lock()

    def start(self, names, options, note, title, process=True):
        with self.lock:
            if process and self.state.get("running"):
                raise RuntimeError("Ya hay una tanda procesándose")
            info = register_batch(names, options, note, title)
            if not process:
                return info
            self.state = {"running": True, "id": info["id"], "title": info["title"], "stage": "analizando",
                          "done": 0, "total": len(names)}
        threading.Thread(target=self._run, args=(names, info), daemon=True).start()
        return info

    def _run(self, names, info):
        st = self.state
        try:
            for i, n in enumerate(names):
                st.update(stage=f"corrigiendo {n}", done=i)
                s = library.load(n)
                if s["status"] not in ("manual", "aprobado"):
                    library.auto(n)
            st.update(stage="exportando", done=0)
            ids = set(self.ex.add(names, ["4k_h264"], keep_audio=False, to_upload=True))
            cleaned = set()
            while True:
                jobs = [j for j in self.ex.list() if j["id"] in ids]
                pend = [j for j in jobs if j["status"] in ("en cola", "procesando", "estabilizando")]
                for c in {j["clip"] for j in jobs} - {j["clip"] for j in pend} - cleaned:
                    export.finish_clip(c)
                    cleaned.add(c)
                st.update(done=len(jobs) - len(pend), total=len(jobs),
                          errors=sum(j["status"] not in ("listo", "en cola", "procesando", "estabilizando") for j in jobs))
                if not pend:
                    break
                time.sleep(2)
            st.update(stage="listo")
        except Exception as e:  # noqa
            st.update(stage="error", error=str(e)[-400:])
        st["running"] = False


def register_batch(names, options, note, title):
    """Guarda la ficha de la tanda y la anota en cada clip (sin procesar nada)."""
    config.TANDAS.mkdir(exist_ok=True)
    tid = time.strftime("%Y-%m-%d_%H%M%S")
    hoy = time.strftime("%Y-%m-%d %H:%M")
    info = {"id": tid, "title": title or f"Subida del {library.fecha(hoy)}", "date": hoy, "clips": names,
            "options": {k: bool(options.get(k)) for k in BATCH_OPTIONS},
            "min": options.get("min"), "max": options.get("max"), "nota": note or ""}
    (config.TANDAS / f"{tid}.json").write_text(json.dumps(info, indent=2, ensure_ascii=False))
    batch = dict(info["options"], min=info["min"], max=info["max"], nota=info["nota"], tanda=tid)
    for n in names:
        s = library.load(n)
        s["batch"] = batch
        if b := batch.get("min"):
            s["segment"]["min"], s["segment"]["max"] = float(b), float(batch.get("max") or b + 2)
        if batch.get("sin_ralentizar"):
            s["segment"]["max_slow"] = 1
        library.save(n, s)
    return info


_bidx = {"mtime": None, "data": {}}


def batch_index():
    m = config.TANDAS.stat().st_mtime if config.TANDAS.exists() else None
    if m != _bidx["mtime"]:
        _bidx.update(mtime=m, data={b["id"]: b for b in batches()})
    return _bidx["data"]


def batches():
    if not config.TANDAS.exists():
        return []
    return sorted((json.loads(f.read_text()) for f in config.TANDAS.glob("*.json")), key=lambda b: b["id"], reverse=True)
