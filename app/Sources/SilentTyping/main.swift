// SilentTyping menu-bar app: receives silent-token events (UDP 127.0.0.1:47800, from
// `sb engine` or `sb keysim`), decodes them to words, types into the focused app via
// Accessibility (CGEvent), and speaks the current candidate in the earbuds.
import AppKit
import AVFoundation
import Network
import TypingCore

final class Typer {
    static func trusted(prompt: Bool) -> Bool {
        let key = "AXTrustedCheckOptionPrompt" as CFString
        return AXIsProcessTrustedWithOptions([key: prompt] as CFDictionary)
    }

    static func type(_ s: String) {
        let src = CGEventSource(stateID: .combinedSessionState)
        for ch in s {
            if ch == "\n" { key(36, src); continue }
            let utf16 = Array(String(ch).utf16)
            for down in [true, false] {
                let e = CGEvent(keyboardEventSource: src, virtualKey: 0, keyDown: down)
                e?.keyboardSetUnicodeString(stringLength: utf16.count, unicodeString: utf16)
                e?.post(tap: .cghidEventTap)
            }
        }
    }

    static func backspace(_ n: Int) {
        let src = CGEventSource(stateID: .combinedSessionState)
        for _ in 0..<n { key(51, src) }
    }

    static func key(_ code: CGKeyCode, _ src: CGEventSource?) {
        CGEvent(keyboardEventSource: src, virtualKey: code, keyDown: true)?.post(tap: .cghidEventTap)
        CGEvent(keyboardEventSource: src, virtualKey: code, keyDown: false)?.post(tap: .cghidEventTap)
    }
}

final class Voice {
    let synth = AVSpeechSynthesizer()
    var language: String
    var rate: Float = 0.55
    init(language: String) { self.language = language }

    func say(_ text: String) {
        synth.stopSpeaking(at: .immediate)  // newest candidate wins
        let u = AVSpeechUtterance(string: text)
        u.voice = AVSpeechSynthesisVoice(language: language == "es" ? "es-ES" : "en-US")
        u.rate = rate
        synth.speak(u)
    }

    /// Distinct short sound per token, so the user hears what was recognized.
    static let earcons: [Action: String] = [.g1: "Tink", .g2: "Pop", .g3: "Morse", .g4: "Bottle",
                                            .next: "Frog", .accept: "Glass", .back: "Basso", .wake: "Hero"]
    func earcon(_ a: Action) {
        guard let name = Self.earcons[a] else { return }
        NSSound(named: NSSound.Name(name))?.play()
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    var status: NSStatusItem!
    var decoder: Decoder!
    var voice: Voice!
    var listener: NWListener?
    var lastStatus = "waiting for tokens (sb keysim / sb engine)"
    var language = UserDefaults.standard.string(forKey: "language") ?? "en"
    var dryRun = CommandLine.arguments.contains("--dry-run")  // print instead of typing
    let work = DispatchQueue(label: "decoder")

    func applicationDidFinishLaunching(_ n: Notification) {
        status = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if !dryRun && !Typer.trusted(prompt: true) {
            lastStatus = "grant Accessibility: System Settings > Privacy > Accessibility"
        }
        rebuild()
        startListener()
    }

    func rebuild() {
        let predictor: Predictor = OllamaPredictor.available() ? OllamaPredictor(language: language) : NoPredictor()
        let lex = Lexicon(language: language)
        decoder = Decoder(lexicon: lex, predictor: predictor)
        voice = Voice(language: language)
        if predictor is NoPredictor { lastStatus = "LLM off (start Ollama for better suggestions)" }
        refreshUI()
    }

    func refreshUI() {
        guard let d = decoder else { return }
        let codeStr = d.code.map { String($0 + 1) }.joined()
        status.button?.title = d.armed ? "◉ \(codeStr.isEmpty ? "" : codeStr + " ")\(d.current ?? "")" : "○"
        let menu = NSMenu()
        menu.addItem(withTitle: d.armed ? "Armed: say WAKE to pause" : "Paused: say WAKE to start", action: nil, keyEquivalent: "")
        menu.addItem(withTitle: lastStatus, action: nil, keyEquivalent: "")
        if !d.candidates.isEmpty {
            menu.addItem(.separator())
            for (i, c) in d.candidates.prefix(6).enumerated() {
                let item = menu.addItem(withTitle: c, action: nil, keyEquivalent: "")
                item.state = i == d.index ? .on : .off
            }
        }
        menu.addItem(.separator())
        let lang = menu.addItem(withTitle: "Language: \(language == "es" ? "Español" : "English")",
                                action: #selector(toggleLanguage), keyEquivalent: "l")
        lang.target = self
        let arm = menu.addItem(withTitle: d.armed ? "Pause" : "Arm", action: #selector(toggleArm), keyEquivalent: "a")
        arm.target = self
        menu.addItem(withTitle: "Quit", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        status.menu = menu
    }

    @objc func toggleLanguage() {
        language = language == "es" ? "en" : "es"
        UserDefaults.standard.set(language, forKey: "language")
        rebuild()
    }

    @objc func toggleArm() { handle(.wake) }

    func startListener() {
        do {
            let params = NWParameters.udp
            params.requiredLocalEndpoint = NWEndpoint.hostPort(host: "127.0.0.1", port: 47800)
            let l = try NWListener(using: params)
            l.newConnectionHandler = { [weak self] conn in
                conn.start(queue: .main)
                self?.receive(conn)
            }
            l.start(queue: .main)
            listener = l
        } catch {
            lastStatus = "cannot listen on udp/47800: \(error)"
        }
    }

    func receive(_ conn: NWConnection) {
        conn.receiveMessage { [weak self] data, _, _, err in
            if let data, let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                if obj["type"] as? String == "token", let a = (obj["action"] as? String).flatMap(Action.init(rawValue:)) {
                    self?.handle(a)
                } else if obj["type"] as? String == "status", let t = obj["text"] as? String {
                    self?.lastStatus = t
                    self?.refreshUI()
                }
            }
            if err == nil { self?.receive(conn) }
        }
    }

    func handle(_ a: Action) {
        work.async { [self] in
            let outs = decoder.handle(a)  // LM call happens off the main thread
            DispatchQueue.main.async { [self] in
                for o in outs {
                    switch o {
                    case .type(let s): dryRun ? print("TYPE \(s.debugDescription)") : Typer.type(s)
                    case .backspace(let n): dryRun ? print("BACKSPACE \(n)") : Typer.backspace(n)
                    case .speak(let s): voice.say(s)
                    case .earcon(let a): voice.earcon(a)
                    }
                }
                refreshUI()
            }
        }
    }
}

setvbuf(stdout, nil, _IOLBF, 0)
let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
