"""python -m kanu [--no-browser] [--port 8765]: arranca el motor de Kanu."""
import os
import sys
import threading
import webbrowser

import uvicorn


def main():
    port = int(os.environ.get("KANU_PORT", "8765"))
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    url = f"http://localhost:{port}"
    print(f"Kanu listo en {url}  (Ctrl+C para cerrar)", flush=True)
    if "--no-browser" not in sys.argv:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run("kanu.api.app:app", host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
