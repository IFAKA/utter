// Utter menu-bar app: receives silent-token events (UDP 127.0.0.1:47800, from
// `utter engine` or `utter keysim`), decodes them to words, types into the focused app via
// Accessibility (CGEvent), and speaks the current candidate in the earbuds.
// Agent integration (app/hooks/utter_hook.py, a Claude Code hook) sends two more events:
//   {"type":"agent","text":...}       the agent's last reply: spoken briefly, and used as LLM context
//   {"type":"permission","text":...,"id":...,"reply_port":...}  a permission prompt. With reply_port
//       (PermissionRequest hook) ACCEPT/BACK send {"id","decision":"allow"|"deny"} back to the hook;
//       without it (Notification fallback) ACCEPT presses Return and BACK Escape.
//   {"type":"permission_expired","id":...}  the hook gave up waiting; drop that prompt.
// `utter voice` (speak mode) sends {"type":"text","text":...}: a draft that ACCEPT sends (types it
// + Return) and BACK undoes piece by piece. While the earbud speaks, the app tells the voice engine
// ({"type":"tts","on":bool} to udp/47802) so it doesn't hear itself.
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

/// Fire-and-forget UDP to a localhost port (hook replies, voice-engine TTS state).
func sendLocal(_ obj: [String: Any], port: UInt16) {
    guard let data = try? JSONSerialization.data(withJSONObject: obj),
          let p = NWEndpoint.Port(rawValue: port) else { return }
    let c = NWConnection(host: "127.0.0.1", port: p, using: .udp)
    c.start(queue: .global())
    c.send(content: data, completion: .contentProcessed { _ in c.cancel() })
}

final class Voice: NSObject, AVSpeechSynthesizerDelegate {
    let synth = AVSpeechSynthesizer()
    var language: String
    var rate: Float = 0.55
    init(language: String) {
        self.language = language
        super.init()
        synth.delegate = self
    }

    // Half-duplex: the voice engine ignores the mic while the earbud speaks.
    func speechSynthesizer(_ s: AVSpeechSynthesizer, didStart u: AVSpeechUtterance) { sendLocal(["type": "tts", "on": true], port: 47802) }
    func speechSynthesizer(_ s: AVSpeechSynthesizer, didFinish u: AVSpeechUtterance) { sendLocal(["type": "tts", "on": false], port: 47802) }
    func speechSynthesizer(_ s: AVSpeechSynthesizer, didCancel u: AVSpeechUtterance) { sendLocal(["type": "tts", "on": false], port: 47802) }

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
    var llm: OllamaPredictor?
    var memory: ReplyMemory!
    var agentMessage = ""  // what the user is replying to, for the reply memory
    var permission: (text: String, id: String?, port: UInt16?)?  // pending agent permission prompt
    var draft: [String] = []  // dictated pieces (utter voice --mode speak), sent on ACCEPT
    var voice: Voice!
    var listener: NWListener?
    var lastStatus = "waiting for tokens (utter keysim / utter engine)"
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
        llm = OllamaPredictor.available() ? OllamaPredictor(language: language) : nil
        if let llm { DispatchQueue.global().async { llm.warmUp() } }
        // Without Ollama, the bundled chat + coding word model (English) still predicts words, offline.
        let offline: Predictor? = language == "en" ? NeuralPredictor.bundled() : nil
        let base: Predictor = llm ?? offline ?? NoPredictor()
        memory = ReplyMemory(base: base, path: ReplyMemory.defaultPath)
        // Reworded agent messages still find past replies by meaning (`ollama pull all-minilm`, English).
        if llm != nil, language == "en" { memory.embed = { OllamaPredictor.embed($0) } }
        let lex = Lexicon(language: language)
        decoder = Decoder(lexicon: lex, predictor: memory)
        voice = Voice(language: language)
        if llm == nil { lastStatus = offline != nil ? "LLM off: offline word model (start Ollama for better suggestions)" : "LLM off (start Ollama for better suggestions)" }
        refreshUI()
    }

    func refreshUI() {
        guard let d = decoder else { return }
        let codeStr = d.code.map { String($0 + 1) }.joined()
        status.button?.title = permission != nil ? "◉ allow? ya / sha"
            : !draft.isEmpty ? "✎ \(draft.joined(separator: " ").suffix(30)) · ya / sha"
            : d.armed ? "◉ \(codeStr.isEmpty ? "" : codeStr + " ")\(d.current ?? "")" : "○"
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
                } else if obj["type"] as? String == "agent", let t = obj["text"] as? String {
                    self?.agentSaid(t)
                } else if obj["type"] as? String == "permission", let t = obj["text"] as? String {
                    self?.permissionAsked(t, id: obj["id"] as? String, port: (obj["reply_port"] as? Int).map { UInt16($0) })
                } else if obj["type"] as? String == "permission_expired", let id = obj["id"] as? String {
                    if self?.permission?.id == id { self?.permission = nil; self?.refreshUI() }
                } else if obj["type"] as? String == "text", let t = obj["text"] as? String {
                    self?.dictated(t)
                } else if obj["type"] as? String == "status", let t = obj["text"] as? String {
                    self?.lastStatus = t
                    self?.refreshUI()
                }
            }
            if err == nil { self?.receive(conn) }
        }
    }

    func say(_ s: String) {
        if dryRun { print("SAY \(s.debugDescription)") }
        voice.say(s)
    }

    func press(_ code: CGKeyCode, _ name: String) {
        dryRun ? print("KEY \(name)") : Typer.key(code, CGEventSource(stateID: .combinedSessionState))
    }

    /// The agent finished a reply: read its first sentence aloud, and predict the user's answer from it.
    func agentSaid(_ text: String) {
        permission = nil
        let flat = text.replacingOccurrences(of: "\n", with: " ")
        let first = flat.split(whereSeparator: { ".?!".contains($0) }).first.map(String.init) ?? flat
        let brief = first.split(separator: " ").prefix(25).joined(separator: " ")
        work.async { [self] in
            remember(decoder.text)  // the reply typed since the last agent message
            agentMessage = String(flat.suffix(800))
            llm?.history = "Assistant: \(agentMessage)\nUser:"
            memory.context = agentMessage
            decoder.newMessage()
            DispatchQueue.main.async { [self] in
                lastStatus = "agent: \(brief.prefix(60))"
                if decoder.armed, !brief.isEmpty { say(brief + (decoder.current.map { ". Suggest: \($0)" } ?? "")) }
                refreshUI()
            }
        }
    }

    /// Save a sent reply (off the main thread, on `work`) so it is offered again for similar agent messages.
    func remember(_ reply: String) {
        let r = reply.replacingOccurrences(of: "\n", with: " ").trimmingCharacters(in: .whitespaces)
        if !r.isEmpty { memory.remember(r, to: agentMessage) }
    }

    func permissionAsked(_ text: String, id: String? = nil, port: UInt16? = nil) {
        permission = (text, id, port)
        lastStatus = "permission: \(text.prefix(60))"
        say("\(text). Ya to allow, sha to deny.")
        refreshUI()
    }

    /// A dictated piece: added to the draft and read back, so you hear what was recognized.
    func dictated(_ text: String) {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty, decoder.armed else { return }
        draft.append(t)
        lastStatus = "draft: \(draft.joined(separator: " ").prefix(60))"
        say(t)
        refreshUI()
    }

    func answer(_ p: (text: String, id: String?, port: UInt16?), allow: Bool) {
        if let id = p.id, let port = p.port {
            sendLocal(["id": id, "decision": allow ? "allow" : "deny"], port: port)
        } else {
            allow ? press(36, "return") : press(53, "escape")
        }
    }

    func handle(_ a: Action) {
        if let p = permission, a != .wake, decoder.armed {
            switch a {
            case .accept: permission = nil; voice.earcon(a); answer(p, allow: true); say("allowed")
            case .back: permission = nil; voice.earcon(a); answer(p, allow: false); say("denied")
            default: say("\(p.text). Ya to allow, sha to deny.")
            }
            refreshUI()
            return
        }
        if !draft.isEmpty, a == .accept || a == .back, decoder.armed {
            voice.earcon(a)
            if a == .accept {
                let text = draft.joined(separator: " ")
                draft = []
                work.async { [self] in remember(text) }
                dryRun ? print("TYPE \((text + "\n").debugDescription)") : Typer.type(text + "\n")
                say("sent")
            } else {
                draft.removeLast()
                say(draft.last.map { "undone. \($0)" } ?? "draft cleared")
            }
            lastStatus = draft.isEmpty ? "draft empty" : "draft: \(draft.joined(separator: " ").prefix(60))"
            refreshUI()
            return
        }
        work.async { [self] in
            let outs = decoder.handle(a)  // LM call happens off the main thread
            DispatchQueue.main.async { [self] in
                for o in outs {
                    switch o {
                    case .type(let s): dryRun ? print("TYPE \(s.debugDescription)") : Typer.type(s)
                    case .backspace(let n): dryRun ? print("BACKSPACE \(n)") : Typer.backspace(n)
                    case .speak(let s): say(s)
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
