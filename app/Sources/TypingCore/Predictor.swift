import Foundation

/// Next-word log-probabilities (natural log) for a context, most likely first.
public protocol Predictor: AnyObject {
    func predict(context: String) -> [(word: String, logp: Double)]
    /// Whole replies to offer before the first word (e.g. answers to an agent's question).
    func phrases() -> [String]
}

public extension Predictor {
    func phrases() -> [String] { [] }
}

/// No language model: the lexicon frequency alone ranks candidates.
public final class NoPredictor: Predictor {
    public init() {}
    public func predict(context: String) -> [(word: String, logp: Double)] { [] }
}

/// Local LLM via Ollama (http://127.0.0.1:11434): raw continuation, top-20 next-token
/// log-probabilities; whole-word tokens (leading space) become word predictions. ~40 ms.
public final class OllamaPredictor: Predictor {
    let model: String
    let timeout: TimeInterval
    private var cache: [String: [(word: String, logp: Double)]] = [:]
    private var phraseCache: [String: [String]] = [:]
    /// What the user is replying to, e.g. "Assistant: Should I run the tests?\nUser:". Empty: a plain message.
    public var history = ""
    /// Offer whole-reply suggestions (needs a non-empty history).
    public var suggestPhrases = false
    private let lock = NSLock()

    public init(model: String = "gemma3:1b", language: String = "en", timeout: TimeInterval = 1.0) {
        self.model = model
        self.timeout = timeout
    }

    public static func available() -> Bool {
        guard let url = URL(string: "http://127.0.0.1:11434/api/tags") else { return false }
        var req = URLRequest(url: url)
        req.timeoutInterval = 0.5
        return syncRequest(req, timeout: 0.7) != nil
    }

    public func predict(context: String) -> [(word: String, logp: Double)] {
        let ctx = context.trimmingCharacters(in: .whitespaces)
        let key = history + "|" + ctx
        lock.lock(); if let c = cache[key] { lock.unlock(); return c }; lock.unlock()
        let prompt = history.isEmpty ? "Message: " + ctx : history + (ctx.isEmpty ? "" : " " + ctx)
        let body: [String: Any] = ["model": model, "prompt": prompt, "raw": true, "stream": false,
                                   "logprobs": true, "top_logprobs": 20,
                                   "options": ["temperature": 0, "num_predict": 1]]
        guard let url = URL(string: "http://127.0.0.1:11434/api/generate"),
              let data = try? JSONSerialization.data(withJSONObject: body) else { return [] }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.httpBody = data
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.timeoutInterval = timeout
        guard let out = Self.syncRequest(req, timeout: timeout),
              let obj = try? JSONSerialization.jsonObject(with: out) as? [String: Any],
              let lps = obj["logprobs"] as? [[String: Any]], let top = lps.first?["top_logprobs"] as? [[String: Any]]
        else { return [] }
        var words: [(word: String, logp: Double)] = []
        for t in top {
            guard let tok = t["token"] as? String, let lp = t["logprob"] as? Double else { continue }
            let first = ctx.isEmpty && history.isEmpty  // the first word of a message may come without a leading space
            guard tok.hasPrefix(" ") || first else { continue }
            let w = tok.trimmingCharacters(in: .whitespaces).lowercased()
            if !w.isEmpty, w.allSatisfy({ $0.isLetter || $0 == "'" }), !words.contains(where: { $0.word == w }) {
                words.append((w, lp))
            }
        }
        lock.lock(); cache[key] = words; lock.unlock()
        return words
    }

    public func phrases() -> [String] {
        guard suggestPhrases, !history.isEmpty else { return [] }
        lock.lock(); if let c = phraseCache[history] { lock.unlock(); return c }; lock.unlock()
        let ask = "Conversation so far:\n\(history)\n\nWrite 4 different short replies the user is likely to send next " +
                  "(2 to 7 words each, lowercase, no punctuation), one per line, nothing else."
        let body: [String: Any] = ["model": model, "prompt": ask, "stream": false, "options": ["temperature": 0, "num_predict": 60]]
        guard let url = URL(string: "http://127.0.0.1:11434/api/generate"),
              let data = try? JSONSerialization.data(withJSONObject: body) else { return [] }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.httpBody = data
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.timeoutInterval = 4
        guard let out = Self.syncRequest(req, timeout: 4),
              let obj = try? JSONSerialization.jsonObject(with: out) as? [String: Any], let text = obj["response"] as? String
        else { return [] }
        var list: [String] = []
        for line in text.split(separator: "\n") {
            let s = line.replacingOccurrences(of: #"^\s*([A-Da-d]|\d)[.):]\s*"#, with: "", options: .regularExpression)
                .lowercased().filter { $0.isLetter || $0 == " " || $0 == "'" }
                .split(separator: " ").joined(separator: " ")
            if s.contains(" "), !list.contains(s) { list.append(s) }
        }
        list = Array(list.prefix(4))
        lock.lock(); phraseCache[history] = list; lock.unlock()
        return list
    }

    static func syncRequest(_ req: URLRequest, timeout: TimeInterval) -> Data? {
        let sem = DispatchSemaphore(value: 0)
        nonisolated(unsafe) var result: Data?
        URLSession.shared.dataTask(with: req) { data, resp, _ in
            if (resp as? HTTPURLResponse)?.statusCode == 200 { result = data }
            sem.signal()
        }.resume()
        _ = sem.wait(timeout: .now() + timeout)
        return result
    }
}
