// Kanu.app: ventana nativa (WKWebView) para el editor web de Kanu.
// Vive en la raíz del repositorio. La primera vez crea el entorno de Python (backend/.venv);
// arranca el motor si no está corriendo y lo apaga al cerrar si lo arrancó ella.
// Compilar: tools/app/build.sh
import Cocoa
import WebKit

let fm = FileManager.default
let url = URL(string: "http://localhost:8765")!
let logURL = fm.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/Kanu.log")

// Raíz del repo: la carpeta que contiene Kanu.app (si tiene backend/); si no, ~/Kanu.
let kanuDir: URL = {
    let beside = Bundle.main.bundleURL.deletingLastPathComponent()
    if fm.fileExists(atPath: beside.appendingPathComponent("backend/pyproject.toml").path) { return beside }
    return fm.homeDirectoryForCurrentUser.appendingPathComponent("Kanu")
}()
let backendDir = kanuDir.appendingPathComponent("backend")
let venvPython = backendDir.appendingPathComponent(".venv/bin/python")

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

let loadingHTML = """
<html><body style="margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
background:#111316;color:#cfd3da;font:15px -apple-system,sans-serif"><div style="text-align:center">
<div style="font-size:22px;color:#fff;margin-bottom:8px">Kanu</div><div>%@</div></div></body></html>
"""

func serverUp() -> Bool {
    var req = URLRequest(url: url, timeoutInterval: 0.5)
    req.httpMethod = "HEAD"
    let sem = DispatchSemaphore(value: 0)
    var ok = false
    URLSession.shared.dataTask(with: req) { _, resp, _ in ok = resp != nil; sem.signal() }.resume()
    _ = sem.wait(timeout: .now() + 1)
    return ok
}

final class AppDelegate: NSObject, NSApplicationDelegate, WKUIDelegate, WKNavigationDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var server: Process?

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
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        status("Abriendo…")
        DispatchQueue.global().async {
            if !serverUp() {
                if let err = self.prepare() { DispatchQueue.main.async { self.fail(err) }; return }
                self.startServer()
            }
            for _ in 0..<120 { if serverUp() { break }; usleep(250_000) }
            DispatchQueue.main.async { self.web.load(URLRequest(url: url)) }
        }
    }

    func status(_ text: String) {
        DispatchQueue.main.async { self.web.loadHTMLString(String(format: loadingHTML, text), baseURL: nil) }
    }

    func fail(_ text: String) {
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
        if fm.isExecutableFile(atPath: venvPython.path) { return nil }
        guard let py = findPython() else {
            return "Hace falta Python 3.11 o más nuevo. Instálalo con: brew install python"
        }
        status("Preparando Kanu por primera vez (1–2 min)…")
        if run(py, ["-m", "venv", ".venv"], cwd: backendDir) != 0 { return "No se pudo crear el entorno de Python." }
        if run(venvPython.path, ["-m", "pip", "install", "-q", "-e", "."], cwd: backendDir) != 0 {
            try? fm.removeItem(at: backendDir.appendingPathComponent(".venv"))
            return "No se pudieron instalar las dependencias (¿hay internet?)."
        }
        return nil
    }

    func startServer() {
        status("Arrancando el motor…")
        let p = Process()
        p.executableURL = venvPython
        p.arguments = ["-m", "kanu", "--no-browser"]
        p.currentDirectoryURL = backendDir
        let h = logHandle(); p.standardOutput = h; p.standardError = h
        try? p.run()
        server = p
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ s: NSApplication) -> Bool { true }
    func applicationWillTerminate(_ n: Notification) { server?.terminate() }

    // Si el motor aún no responde, reintenta.
    func webView(_ w: WKWebView, didFailProvisionalNavigation n: WKNavigation!, withError e: Error) {
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
