// Kanu.app: ventana nativa (WKWebView) para el editor web de Kanu.
// Dos modos:
//  - Instalada (desde el .dmg): trae Python, ffmpeg y el motor dentro de Contents/Resources;
//    los videos y ajustes van a ~/Movies/Kanu.
//  - Desarrollo (en la raíz del repositorio): la primera vez crea backend/.venv y usa el repo como datos.
// Arranca el motor si no está corriendo y lo apaga al cerrar si lo arrancó ella.
// Compilar: tools/app/build.sh · Instalador: tools/app/empaquetar.sh
import Cocoa
import WebKit

let fm = FileManager.default
let url = URL(string: "http://localhost:8765")!
let logURL = fm.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/Kanu.log")

let resources = Bundle.main.resourceURL!
let bundledPython = resources.appendingPathComponent("python/bin/python3")
let installed = fm.isExecutableFile(atPath: bundledPython.path)
let gyroflowApp = "/Applications/Gyroflow.app"
let gyroflowURL = URL(string: "https://gyroflow.xyz/download")!

// Raíz del código: dentro de la app si está instalada; si no, la carpeta del repo junto a Kanu.app (o ~/Kanu).
let kanuDir: URL = {
    if installed { return resources.appendingPathComponent("kanu") }
    let beside = Bundle.main.bundleURL.deletingLastPathComponent()
    if fm.fileExists(atPath: beside.appendingPathComponent("backend/pyproject.toml").path) { return beside }
    return fm.homeDirectoryForCurrentUser.appendingPathComponent("Kanu")
}()
let backendDir = kanuDir.appendingPathComponent("backend")
let venvPython = installed ? bundledPython : backendDir.appendingPathComponent(".venv/bin/python")
// Carpeta de datos: ~/Movies/Kanu instalada; la raíz del repo en desarrollo.
let dataDir = installed ? fm.homeDirectoryForCurrentUser.appendingPathComponent("Movies/Kanu") : kanuDir

func logHandle() -> FileHandle? {
    if !fm.fileExists(atPath: logURL.path) { fm.createFile(atPath: logURL.path, contents: nil) }
    let h = try? FileHandle(forWritingTo: logURL)
    h?.seekToEndOfFile()
    return h
}

@discardableResult
func run(_ exe: String, _ args: [String], cwd: URL? = nil) -> Int32 {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: exe)
    p.arguments = args
    if let cwd { p.currentDirectoryURL = cwd }
    let h = logHandle(); p.standardOutput = h; p.standardError = h
    do { try p.run() } catch { return -1 }
    p.waitUntilExit()
    return p.terminationStatus
}

// Primer Python 3.11+ que encuentre (las apps abiertas desde el Finder no heredan el PATH).
func findPython() -> String? {
    let candidates = ["/opt/homebrew/bin/python3", "/usr/local/bin/python3",
                      "/opt/homebrew/bin/python3.13", "/opt/homebrew/bin/python3.12", "/opt/homebrew/bin/python3.11",
                      "/Library/Frameworks/Python.framework/Versions/Current/bin/python3", "/usr/bin/python3"]
    for c in candidates where fm.isExecutableFile(atPath: c) {
        if run(c, ["-c", "import sys; sys.exit(sys.version_info < (3, 11))"]) == 0 { return c }
    }
    return nil
}


func serverUp() -> Bool {
    var req = URLRequest(url: url, timeoutInterval: 0.5)
    req.httpMethod = "HEAD"
    let sem = DispatchSemaphore(value: 0)
    var ok = false
    URLSession.shared.dataTask(with: req) { _, resp, _ in ok = resp != nil; sem.signal() }.resume()
    _ = sem.wait(timeout: .now() + 1)
    return ok
}

// Pantalla de carga: panel negro con el nombre y los créditos, y el tucán a sangre a la derecha.
func splashHTML() -> String {
    let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? ""
    let iconFile = kanuDir.appendingPathComponent("apps/legacy-ui/icon.png")
    let icon = (try? Data(contentsOf: iconFile)).map { "data:image/png;base64," + $0.base64EncodedString() } ?? ""
    return """
    <!doctype html><html><head><meta charset="utf-8"><style>
    *{box-sizing:border-box} html,body{margin:0;height:100%;overflow:hidden;-webkit-user-select:none;cursor:default}
    body{display:flex;font:13px/1.45 -apple-system,BlinkMacSystemFont,sans-serif;background:#0b0c0e;color:#e9e9ec}
    .l{width:47%;padding:58px 52px 44px;display:flex;flex-direction:column}
    .kanu{font-size:64px;font-weight:800;letter-spacing:-2px;line-height:.95;color:#8db4e0}
    .what{font-size:30px;font-weight:800;letter-spacing:-.6px;line-height:1.05;color:#fff;margin-top:6px}
    .sp{flex:1}
    .ill{font-weight:700;color:#fff;margin-bottom:18px}
    .c{color:#c9cbd0;font-size:14px;line-height:1.5}
    .st{color:#fff;font-size:14px;margin:14px 0 16px;min-height:21px}
    .st:after{content:"";display:inline-block;width:1.2em;text-align:left;animation:d 1.2s steps(4) infinite}
    @keyframes d{0%{content:""}25%{content:"."}50%{content:".."}75%{content:"..."}}
    .cr{color:#8f9299;font-size:12px;line-height:1.55}
    .r{flex:1;position:relative;overflow:hidden;background:#7a9ec6}
    .r img{position:absolute;width:126%;left:-21%;top:-24px;transform-origin:40% 40%;animation:z 14s ease-out forwards}
    @keyframes z{from{transform:scale(1.04)}to{transform:scale(1)}}
    .bar{position:absolute;left:0;right:0;bottom:0;height:3px;background:rgba(255,255,255,.25)}
    .bar i{display:block;height:100%;width:30%;background:#fff;animation:b 1.6s ease-in-out infinite}
    @keyframes b{from{transform:translateX(-100%)}to{transform:translateX(340%)}}
    </style></head><body>
    <div class="l">
      <div class="kanu">Kanu</div><div class="what">Editor de<br>Video Stock</div>
      <div class="sp"></div>
      <div class="ill">Ilustración: tucán a plumilla, hecho a pico.</div>
      <div class="c">© 2026 Jhampier Giron y colaboradores.<br>Código abierto con licencia MIT.<br>Versión \(version)</div>
      <div class="st" id="st">Abriendo</div>
      <div class="cr">Hecho con Python, FastAPI, NumPy, FFmpeg, Gyroflow y WebKit.<br>
        Tú sales a grabar. Kanu se encarga del resto.</div>
    </div>
    <div class="r"><img src="\(icon)" alt=""><div class="bar"><i></i></div></div>
    <script>function setStatus(t){document.getElementById('st').textContent=t}</script>
    </body></html>
    """
}

final class AppDelegate: NSObject, NSApplicationDelegate, WKUIDelegate, WKNavigationDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var server: Process?
    var splash: NSWindow?
    var splashWeb: WKWebView?
    var splashShownAt = Date()
    var revealed = false
    var pendingStatus: String?

    func applicationDidFinishLaunching(_ n: Notification) {
        buildMenu()
        let cfg = WKWebViewConfiguration()
        cfg.preferences.setValue(true, forKey: "developerExtrasEnabled")
        cfg.mediaTypesRequiringUserActionForPlayback = []
        web = WKWebView(frame: .zero, configuration: cfg)
        web.uiDelegate = self
        web.navigationDelegate = self

        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1500, height: 950),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = "Kanu"
        window.contentView = web
        window.setFrameAutosaveName("KanuVentana")
        if !window.setFrameUsingName("KanuVentana") { window.center() }

        showSplash()                                   // la ventana principal aparece cuando el editor ya cargó
        status("Leyendo preferencias")
        DispatchQueue.global().async {
            usleep(350_000)
            if !serverUp() {
                if let err = self.prepare() { DispatchQueue.main.async { self.fail(err) }; return }
                self.startServer()
            }
            for _ in 0..<120 { if serverUp() { break }; usleep(250_000) }
            self.status("Cargando tus tandas")
            DispatchQueue.main.async { self.web.load(URLRequest(url: url)) }
        }
    }

    func showSplash() {
        let size = NSSize(width: 880, height: 540)
        let w = NSWindow(contentRect: NSRect(origin: .zero, size: size), styleMask: [.borderless],
                         backing: .buffered, defer: false)
        w.isOpaque = false
        w.backgroundColor = .clear
        w.hasShadow = true
        w.level = .floating
        w.isMovableByWindowBackground = true
        let sw = WKWebView(frame: NSRect(origin: .zero, size: size))
        sw.navigationDelegate = self
        sw.setValue(false, forKey: "drawsBackground")
        sw.wantsLayer = true
        sw.layer?.cornerRadius = 16
        sw.layer?.masksToBounds = true
        w.contentView = sw
        sw.loadHTMLString(splashHTML(), baseURL: nil)
        w.center()
        splash = w; splashWeb = sw
        // se muestra cuando el HTML (con el tucán) ya está pintado; por si tarda, a los 0.6 s igual
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) { self.presentSplash() }
    }

    func presentSplash() {
        guard let w = splash, !w.isVisible, !revealed else { return }
        w.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        splashShownAt = Date()
    }

    // Muestra el editor y desvanece la pantalla de carga (se ve al menos 1.8 s, como en las apps de Adobe).
    func reveal() {
        guard !revealed else { return }
        revealed = true
        status("Listo")
        let wait = max(0, 1.8 - Date().timeIntervalSince(splashShownAt))
        DispatchQueue.main.asyncAfter(deadline: .now() + wait) {
            self.window.alphaValue = 0
            self.window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            NSAnimationContext.runAnimationGroup({ ctx in
                ctx.duration = 0.35
                self.window.animator().alphaValue = 1
                self.splash?.animator().alphaValue = 0
            }, completionHandler: {
                self.splash?.orderOut(nil); self.splash = nil; self.splashWeb = nil
                self.checkGyroflow()
            })
        }
    }

    // Gyroflow no va dentro de Kanu: si falta, avisa una vez (sin él todo funciona menos la estabilización).
    func checkGyroflow() {
        let key = "noAvisarGyroflow"
        guard !fm.fileExists(atPath: gyroflowApp), !UserDefaults.standard.bool(forKey: key) else { return }
        let a = NSAlert()
        a.messageText = "Falta Gyroflow"
        a.informativeText = "Kanu usa Gyroflow (gratis) para estabilizar los videos. Todo lo demás funciona sin él.\n\n"
            + "Descárgalo, arrástralo a Aplicaciones y vuelve a abrir Kanu."
        a.addButton(withTitle: "Descargar Gyroflow")
        a.addButton(withTitle: "Ahora no")
        a.showsSuppressionButton = true
        a.suppressionButton?.title = "No volver a avisar"
        a.beginSheetModal(for: window) { r in
            if a.suppressionButton?.state == .on { UserDefaults.standard.set(true, forKey: key) }
            if r == .alertFirstButtonReturn { NSWorkspace.shared.open(gyroflowURL) }
        }
    }

    @objc func showData() {
        try? fm.createDirectory(at: dataDir, withIntermediateDirectories: true)
        NSWorkspace.shared.open(dataDir)
    }

    func status(_ text: String) {
        DispatchQueue.main.async {
            guard let sw = self.splashWeb else { return }
            if sw.isLoading { self.pendingStatus = text; return }
            let js = "setStatus(\"\(text.replacingOccurrences(of: "\"", with: "'"))\")"
            sw.evaluateJavaScript(js, completionHandler: nil)
        }
    }

    func fail(_ text: String) {
        splash?.orderOut(nil); splash = nil; splashWeb = nil
        let a = NSAlert(); a.messageText = "Kanu no pudo arrancar"
        a.informativeText = text + "\n\nDetalles en ~/Library/Logs/Kanu.log"
        a.addButton(withTitle: "Salir")
        a.runModal()
        NSApp.terminate(nil)
    }

    // Primera vez: crea backend/.venv e instala el motor. Devuelve un error legible o nil.
    func prepare() -> String? {
        if !fm.fileExists(atPath: backendDir.path) {
            return "No encuentro la carpeta del proyecto (\(kanuDir.path)). Deja Kanu.app en la raíz del repositorio."
        }
        if installed || fm.isExecutableFile(atPath: venvPython.path) { return nil }
        guard let py = findPython() else {
            return "Hace falta Python 3.11 o más nuevo. Instálalo con: brew install python"
        }
        status("Preparando Kanu por primera vez (1–2 min)")
        if run(py, ["-m", "venv", ".venv"], cwd: backendDir) != 0 { return "No se pudo crear el entorno de Python." }
        if run(venvPython.path, ["-m", "pip", "install", "-q", "-e", "."], cwd: backendDir) != 0 {
            try? fm.removeItem(at: backendDir.appendingPathComponent(".venv"))
            return "No se pudieron instalar las dependencias (¿hay internet?)."
        }
        return nil
    }

    func startServer() {
        status("Arrancando el motor")
        let p = Process()
        p.executableURL = venvPython
        p.arguments = ["-m", "kanu", "--no-browser"]
        p.currentDirectoryURL = backendDir
        if installed {
            var env = ProcessInfo.processInfo.environment
            let bin = resources.appendingPathComponent("bin")
            env["KANU_DATA"] = dataDir.path
            env["KANU_FFMPEG"] = bin.appendingPathComponent("ffmpeg").path
            env["KANU_FFPROBE"] = bin.appendingPathComponent("ffprobe").path
            env["PYTHONPATH"] = backendDir.path
            env["PYTHONDONTWRITEBYTECODE"] = "1"   // no escribir dentro de la app firmada
            env["PATH"] = bin.path + ":/usr/bin:/bin:/usr/sbin:/sbin"
            p.environment = env
            try? fm.createDirectory(at: dataDir, withIntermediateDirectories: true)
        }
        let h = logHandle(); p.standardOutput = h; p.standardError = h
        try? p.run()
        server = p
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ s: NSApplication) -> Bool { true }
    func applicationWillTerminate(_ n: Notification) { server?.terminate() }

    // Si el motor aún no responde, reintenta.
    func webView(_ w: WKWebView, didFinish n: WKNavigation!) {
        if w === splashWeb {                            // estado que llegó antes de que cargara el HTML
            if let s = pendingStatus { pendingStatus = nil; status(s) }
            presentSplash()
        } else if w === web, w.url?.host == "localhost" {
            reveal()
        }
    }

    func webView(_ w: WKWebView, didFailProvisionalNavigation n: WKNavigation!, withError e: Error) {
        if w === splashWeb { return }
        guard (e as NSError).code != NSURLErrorCancelled else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { w.load(URLRequest(url: url)) }
    }

    // Enlaces a otros sitios: navegador del sistema.
    func webView(_ w: WKWebView, decidePolicyFor a: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if let u = a.request.url, u.host != "localhost", u.host != "127.0.0.1", u.scheme?.hasPrefix("http") == true {
            NSWorkspace.shared.open(u); decisionHandler(.cancel); return
        }
        decisionHandler(.allow)
    }

    // <input type="file">
    func webView(_ w: WKWebView, runOpenPanelWith p: WKOpenPanelParameters, initiatedByFrame f: WKFrameInfo,
                 completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = p.allowsMultipleSelection
        panel.canChooseDirectories = p.allowsDirectories
        panel.canChooseFiles = true
        panel.beginSheetModal(for: window) { r in completionHandler(r == .OK ? panel.urls : nil) }
    }

    // alert / confirm / prompt
    func webView(_ w: WKWebView, runJavaScriptAlertPanelWithMessage m: String, initiatedByFrame f: WKFrameInfo,
                 completionHandler: @escaping () -> Void) {
        let a = NSAlert(); a.messageText = m; a.addButton(withTitle: "OK")
        a.beginSheetModal(for: window) { _ in completionHandler() }
    }

    func webView(_ w: WKWebView, runJavaScriptConfirmPanelWithMessage m: String, initiatedByFrame f: WKFrameInfo,
                 completionHandler: @escaping (Bool) -> Void) {
        let a = NSAlert(); a.messageText = m
        a.addButton(withTitle: "Aceptar"); a.addButton(withTitle: "Cancelar")
        a.beginSheetModal(for: window) { r in completionHandler(r == .alertFirstButtonReturn) }
    }

    func webView(_ w: WKWebView, runJavaScriptTextInputPanelWithPrompt m: String, defaultText d: String?,
                 initiatedByFrame f: WKFrameInfo, completionHandler: @escaping (String?) -> Void) {
        let a = NSAlert(); a.messageText = m
        a.addButton(withTitle: "Aceptar"); a.addButton(withTitle: "Cancelar")
        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 240, height: 24))
        field.stringValue = d ?? ""
        a.accessoryView = field
        a.window.initialFirstResponder = field
        a.beginSheetModal(for: window) { r in completionHandler(r == .alertFirstButtonReturn ? field.stringValue : nil) }
    }

    @objc func reload() { web.reload() }

    // Menú mínimo para que funcionen Cmd+Q, Cmd+C/V, Cmd+R, etc.
    func buildMenu() {
        let main = NSMenu()
        let app = NSMenuItem(); main.addItem(app)
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "Ocultar Kanu", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Salir de Kanu", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        app.submenu = appMenu

        let file = NSMenuItem(); main.addItem(file)
        let fileMenu = NSMenu(title: "Archivo")
        fileMenu.addItem(withTitle: "Mostrar carpeta de Kanu", action: #selector(showData), keyEquivalent: "o")
        file.submenu = fileMenu

        let edit = NSMenuItem(); main.addItem(edit)
        let editMenu = NSMenu(title: "Edición")
        editMenu.addItem(withTitle: "Deshacer", action: Selector(("undo:")), keyEquivalent: "z")
        editMenu.addItem(withTitle: "Rehacer", action: Selector(("redo:")), keyEquivalent: "Z")
        editMenu.addItem(.separator())
        editMenu.addItem(withTitle: "Cortar", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: "Copiar", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "Pegar", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "Seleccionar todo", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        edit.submenu = editMenu

        let view = NSMenuItem(); main.addItem(view)
        let viewMenu = NSMenu(title: "Ver")
        viewMenu.addItem(withTitle: "Recargar", action: #selector(reload), keyEquivalent: "r")
        viewMenu.addItem(withTitle: "Pantalla completa", action: #selector(NSWindow.toggleFullScreen(_:)), keyEquivalent: "f")
        view.submenu = viewMenu

        let win = NSMenuItem(); main.addItem(win)
        let winMenu = NSMenu(title: "Ventana")
        winMenu.addItem(withTitle: "Minimizar", action: #selector(NSWindow.miniaturize(_:)), keyEquivalent: "m")
        winMenu.addItem(withTitle: "Cerrar", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        win.submenu = winMenu
        NSApp.mainMenu = main
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
