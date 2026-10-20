import Foundation

/// Next-word log-probabilities (natural log) for a context, most likely first.
public protocol Predictor: AnyObject {
    func predict(context: String) -> [(word: String, logp: Double)]
    /// Whole replies to offer before the first word (e.g. answers to an agent's question).
    func phrases() -> [String]
    /// Rest-of-reply completions for the words typed so far in this sentence (e.g. "yes" -> "run the tests").
    func completions(of typed: String) -> [String]
}

public extension Predictor {
    func phrases() -> [String] { [] }
    func completions(of typed: String) -> [String] { [] }
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

    /// Keep the model in memory all session: Ollama unloads it after 5 idle minutes, and reloading
    /// (~6 s) outlasts every 1 s request, which cancels the load, so the LLM silently never answered.
    let keepAlive = "2h"

    /// Load the model before the first prediction (blocking; the app calls it off the main thread).
    @discardableResult
    public func warmUp(timeout: TimeInterval = 60) -> Bool {
        let body: [String: Any] = ["model": model, "prompt": "", "keep_alive": keepAlive]
        guard let url = URL(string: "http://127.0.0.1:11434/api/generate"),
              let data = try? JSONSerialization.data(withJSONObject: body) else { return false }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.httpBody = data
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.timeoutInterval = timeout
        return Self.syncRequest(req, timeout: timeout) != nil
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
                                   "keep_alive": keepAlive, "options": ["temperature": 0, "num_predict": 1]]
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
        // A 1B model asked for "short replies" answers "yes / okay / sure"; one worked example makes it
        // write multi-word replies (~0.2 s). The example is not from the st-gate benchmark.
        let ask = "Suggest 4 short replies a user might send to their coding assistant.\n\n" +
                  "Assistant: I added the cache. Want me to benchmark it?\nReplies:\nyes run the benchmark\n" +
                  "no ship it as is\nshow me the diff first\nbenchmark it against main\n\n" +
                  history.replacingOccurrences(of: "\nUser:", with: "") + "\nReplies:\n"
        let body: [String: Any] = ["model": model, "prompt": ask, "raw": true, "stream": false, "keep_alive": keepAlive,
                                   "options": ["temperature": 0, "num_predict": 40, "stop": ["\n\n"]]]
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

    /// Sentence embeddings from a small Ollama embedding model (all-minilm, 46 MB); nil if it is not pulled.
    public static func embed(_ texts: [String], model: String = "all-minilm", timeout: TimeInterval = 2) -> [[Float]]? {
        let body: [String: Any] = ["model": model, "input": texts, "keep_alive": "2h"]
        guard let url = URL(string: "http://127.0.0.1:11434/api/embed"),
              let data = try? JSONSerialization.data(withJSONObject: body) else { return nil }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.httpBody = data
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.timeoutInterval = timeout
        guard let out = syncRequest(req, timeout: timeout),
              let obj = try? JSONSerialization.jsonObject(with: out) as? [String: Any],
              let e = obj["embeddings"] as? [[Double]], e.count == texts.count else { return nil }
        return e.map { $0.map(Float.init) }
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
