// Gli occhi di Jarvis: leggono lo schermo senza stimare distanze.
// Si compila una volta: swiftc -O strumenti/occhi.swift -o strumenti/bin/occhi
//
//   occhi ocr <file.png> <larghezza_punti> <altezza_punti>
//       testo sullo schermo con il riquadro in punti (Vision, italiano e inglese)
//   occhi ax <nome app>
//       elementi dell'app dall'albero di Accessibilità: ruolo, titolo, riquadro in punti
//   occhi premi <nome app> <testo>
//       AXPress sul primo elemento che contiene il testo
//   occhi schermi
//       ogni schermo: riquadro in punti e fattore di scala (Retina = 2)
//   occhi finestra <nome app>
//       riquadro in punti della prima finestra dell'app
//   occhi attiva <nome app>
//       porta l'app davanti (nome italiano o inglese) e dice chi è davanti dopo
//   occhi clic <x> <y> [pid]
//       clic con CGEvent (movimento, pausa, giù, su); con pid va dritto all'app
//
// Esce sempre JSON su stdout.
import AppKit
import ApplicationServices
import Foundation
import Vision

func stampa(_ v: Any) {
    let d = try! JSONSerialization.data(withJSONObject: v, options: [.sortedKeys])
    print(String(data: d, encoding: .utf8)!)
}

func muori(_ msg: String) -> Never {
    FileHandle.standardError.write((msg + "\n").data(using: .utf8)!)
    exit(1)
}

// ---------- OCR ----------
func ocr(_ file: String, _ lp: Double, _ hp: Double) {
    guard let img = NSImage(contentsOfFile: file),
          let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else { muori("immagine illeggibile: \(file)") }
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.recognitionLanguages = ["it-IT", "en-US"]
    req.usesLanguageCorrection = false
    try? VNImageRequestHandler(cgImage: cg).perform([req])
    var out: [[String: Any]] = []
    for o in req.results ?? [] {
        guard let c = o.topCandidates(1).first else { continue }
        let b = o.boundingBox  // normalizzato, origine in basso a sinistra
        let x = b.minX * lp, y = (1 - b.maxY) * hp, w = b.width * lp, h = b.height * hp
        out.append(["testo": c.string, "fiducia": (Double(c.confidence) * 100).rounded() / 100,
                    "x": Int(x.rounded()), "y": Int(y.rounded()), "l": Int(w.rounded()), "h": Int(h.rounded()),
                    "cx": Int((x + w / 2).rounded()), "cy": Int((y + h / 2).rounded())])
    }
    stampa(out)
}

// ---------- Accessibilità ----------
func pidDi(_ nome: String) -> pid_t {
    let apps = NSWorkspace.shared.runningApplications
    if let a = apps.first(where: { $0.localizedName?.lowercased() == nome.lowercased() }) { return a.processIdentifier }
    if let a = apps.first(where: { ($0.localizedName ?? "").lowercased().contains(nome.lowercased()) }) { return a.processIdentifier }
    muori("app non aperta: \(nome)")
}

func attr(_ e: AXUIElement, _ a: String) -> AnyObject? {
    var v: AnyObject?
    return AXUIElementCopyAttributeValue(e, a as CFString, &v) == .success ? v : nil
}

func riquadro(_ e: AXUIElement) -> CGRect? {
    guard let p = attr(e, kAXPositionAttribute), let s = attr(e, kAXSizeAttribute) else { return nil }
    var pt = CGPoint.zero, sz = CGSize.zero
    AXValueGetValue(p as! AXValue, .cgPoint, &pt)
    AXValueGetValue(s as! AXValue, .cgSize, &sz)
    return CGRect(origin: pt, size: sz)
}

func testoDi(_ e: AXUIElement) -> String {
    for a in [kAXTitleAttribute, kAXDescriptionAttribute, kAXValueAttribute, kAXHelpAttribute, "AXIdentifier"] {
        if let s = attr(e, a) as? String, !s.isEmpty { return s }
    }
    return ""
}

func visita(_ e: AXUIElement, _ prof: Int, _ fuori: inout [(AXUIElement, [String: Any])]) {
    if prof > 25 || fuori.count > 3000 { return }
    let ruolo = attr(e, kAXRoleAttribute) as? String ?? ""
    let t = testoDi(e)
    if let r = riquadro(e), r.width > 0, r.height > 0, !t.isEmpty || ruolo.contains("Button") {
        fuori.append((e, ["ruolo": ruolo, "testo": String(t.prefix(80)),
                          "x": Int(r.minX), "y": Int(r.minY), "l": Int(r.width), "h": Int(r.height),
                          "cx": Int(r.midX), "cy": Int(r.midY)]))
    }
    for c in (attr(e, kAXChildrenAttribute) as? [AXUIElement]) ?? [] { visita(c, prof + 1, &fuori) }
}

func elementi(_ app: String) -> [(AXUIElement, [String: Any])] {
    guard AXIsProcessTrusted() else { muori("manca il permesso di Accessibilità a questo programma") }
    let radice = AXUIElementCreateApplication(pidDi(app))
    var fuori: [(AXUIElement, [String: Any])] = []
    for w in (attr(radice, kAXWindowsAttribute) as? [AXUIElement]) ?? [] { visita(w, 0, &fuori) }
    return fuori
}

// ---------- clic ----------
func clic(_ x: Double, _ y: Double, _ pid: pid_t?) {
    let p = CGPoint(x: x, y: y)
    let src = CGEventSource(stateID: .hidSystemState)
    func manda(_ tipo: CGEventType) {
        let e = CGEvent(mouseEventSource: src, mouseType: tipo, mouseCursorPosition: p, mouseButton: .left)!
        e.setIntegerValueField(.mouseEventClickState, value: 1)
        if let pid = pid { e.postToPid(pid) } else { e.post(tap: .cghidEventTap) }
    }
    manda(.mouseMoved); usleep(120_000)
    manda(.leftMouseDown); usleep(60_000)
    manda(.leftMouseUp)
    stampa(["clic": [Int(x), Int(y)], "via": pid == nil ? "hid" : "pid \(pid!)"])
}

let a = CommandLine.arguments
guard a.count >= 2 else { muori("uso: occhi ocr|ax|premi|clic …") }
switch a[1] {
case "ocr" where a.count >= 5: ocr(a[2], Double(a[3])!, Double(a[4])!)
case "ax" where a.count >= 3: stampa(elementi(a[2]).map { $0.1 })
case "premi" where a.count >= 4:
    let cerca = a[3].lowercased()
    guard let (e, info) = elementi(a[2]).first(where: { (($0.1["testo"] as? String) ?? "").lowercased().contains(cerca) })
    else { muori("nessun elemento con «\(a[3])» in \(a[2])") }
    let r = AXUIElementPerformAction(e, kAXPressAction as CFString)
    var out = info; out["premuto"] = r == .success; out["esito_ax"] = r.rawValue
    stampa(out)
case "schermi":
    let alto = NSScreen.screens.first?.frame.maxY ?? 0
    stampa(NSScreen.screens.enumerated().map { (i, sc) -> [String: Any] in
        let f = sc.frame  // coordinate Cocoa: origine in basso; si converte in quelle dei clic (origine in alto)
        return ["n": i, "principale": i == 0, "x": Int(f.minX), "y": Int(alto - f.maxY),
                "l": Int(f.width), "h": Int(f.height), "scala": Double(sc.backingScaleFactor)]
    })
case "finestra" where a.count >= 3:
    guard AXIsProcessTrusted() else { muori("manca il permesso di Accessibilità a questo programma") }
    let radice = AXUIElementCreateApplication(pidDi(a[2]))
    guard let w = ((attr(radice, kAXFocusedWindowAttribute) as! AXUIElement?)
                   ?? (attr(radice, kAXWindowsAttribute) as? [AXUIElement])?.first),
          let r = riquadro(w) else { muori("nessuna finestra per \(a[2])") }
    stampa(["app": a[2], "pid": Int(pidDi(a[2])), "titolo": testoDi(w),
            "x": Int(r.minX), "y": Int(r.minY), "l": Int(r.width), "h": Int(r.height)])
case "attiva" where a.count >= 3:
    let pid = pidDi(a[2])
    let app = NSRunningApplication(processIdentifier: pid)!
    app.unhide()
    app.activate(options: [.activateAllWindows])
    // alza anche la finestra: senza, l'app è davanti ma la finestra può restare sotto
    let radice = AXUIElementCreateApplication(pid)
    if let w = (attr(radice, kAXWindowsAttribute) as? [AXUIElement])?.first {
        AXUIElementPerformAction(w, kAXRaiseAction as CFString)
        AXUIElementSetAttributeValue(w, kAXMainAttribute as CFString, kCFBooleanTrue)
    }
    var davanti = ""
    for _ in 0..<20 {
        davanti = NSWorkspace.shared.frontmostApplication?.localizedName ?? ""
        if NSWorkspace.shared.frontmostApplication?.processIdentifier == pid { break }
        usleep(50_000)
    }
    stampa(["richiesta": a[2], "pid": Int(pid), "davanti": davanti,
            "ok": NSWorkspace.shared.frontmostApplication?.processIdentifier == pid])
case "davanti":
    let f = NSWorkspace.shared.frontmostApplication
    stampa(["davanti": f?.localizedName ?? "", "pid": Int(f?.processIdentifier ?? 0)])
case "clic" where a.count >= 4: clic(Double(a[2])!, Double(a[3])!, a.count >= 5 ? pid_t(a[4]) : nil)
default: muori("comando sconosciuto o argomenti mancanti")
}
