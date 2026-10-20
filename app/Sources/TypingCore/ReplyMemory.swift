import Foundation

/// Remembers the replies the user sent and offers them again as whole-reply phrases when the agent's
/// message resembles the one they answered (retrieval from the user's own text, Tanaka-Ishii 2002 /
/// Smart Reply). Word predictions pass through to `base`. Stored locally, one JSON line per reply.
public final class ReplyMemory: Predictor {
    struct Item: Codable { var agent: String; var reply: String }
    let base: Predictor
    let path: String?
    private var items: [Item] = []
    /// The agent message being answered; empty for a plain message.
    public var context = ""
    /// At most this many remembered replies lead the phrase list.
    public var maxOffers = 2
    /// Sentence embeddings (OllamaPredictor.embed). With them a reworded agent message still finds the
    /// replies to the message it means the same as (Smart Reply's retrieval); without, shared words only.
    public var embed: (([String]) -> [[Float]]?)?
    private var vectors: [String: [Float]] = [:]
    private var embedRetry = Date.distantPast

    public init(base: Predictor, path: String? = nil) {
        self.base = base
        self.path = path
        if let path, let s = try? String(contentsOfFile: path, encoding: .utf8) {
            items = s.split(separator: "\n").compactMap { try? JSONDecoder().decode(Item.self, from: Data($0.utf8)) }
        }
    }

    /// ~/Library/Application Support/Utter/replies.jsonl
    public static var defaultPath: String {
        let dir = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("Utter")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir.appendingPathComponent("replies.jsonl").path
    }

    public var count: Int { items.count }

    public func remember(_ reply: String, to agent: String) {
        let r = reply.lowercased().split(whereSeparator: \.isWhitespace).joined(separator: " ")
        guard r.contains(" ") else { return }  // single words are already the top word predictions
        let it = Item(agent: agent, reply: r)
        items.append(it)
        if let path, let d = try? JSONEncoder().encode(it), let h = FileHandle(forWritingAtPath: path) ?? {
            FileManager.default.createFile(atPath: path, contents: nil); return FileHandle(forWritingAtPath: path) }() {
            h.seekToEndOfFile(); h.write(d + Data("\n".utf8)); try? h.close()
        }
    }

    public func predict(context: String) -> [(word: String, logp: Double)] { base.predict(context: context) }

    public func phrases() -> [String] {
        var out = offers()
        for p in base.phrases() where !out.contains(p) { out.append(p) }
        return Array(out.prefix(4))
    }

    /// Remembered replies that begin with the typed words, as the words still to type, best first.
    public func completions(of typed: String) -> [String] {
        let t = typed.lowercased().split(whereSeparator: \.isWhitespace).joined(separator: " ")
        guard !t.isEmpty, maxOffers > 0 else { return [] }
        let sims = similarities()
        var score: [String: Double] = [:]
        for (it, sim) in zip(items, sims) where it.reply.hasPrefix(t + " ") {
            score[String(it.reply.dropFirst(t.count + 1)), default: 0] += 0.2 + sim  // frequency and similarity
        }
        return score.sorted { $0.value != $1.value ? $0.value > $1.value : $0.key < $1.key }.prefix(maxOffers).map(\.key)
    }

    static let stop: Set<String> = ["the", "a", "an", "to", "of", "and", "or", "i", "you", "it", "is", "in", "on", "for",
                                    "this", "that", "with", "be", "me", "do", "should", "want", "can", "will", "would", "now"]
    static func words(_ s: String) -> Set<String> {
        Set(s.lowercased().split(whereSeparator: { !$0.isLetter && !$0.isNumber }).map(String.init).filter { !stop.contains($0) })
    }

    /// How alike the current agent message is to each remembered one: content-word overlap (Jaccard), or
    /// embedding cosine minus 0.2 when larger, so one threshold (0.25) serves both. On the st-gate rewordings
    /// cosine ≥ 0.45 found the right message 20 of 25 times with 1 wrong offer; Jaccard found almost none.
    private func similarities() -> [Double] {
        let now = Self.words(context)
        var cos: [String: Double] = [:]
        if let embed, !context.isEmpty, Date() > embedRetry {
            let need = Array(Set([context] + items.map(\.agent)).filter { !$0.isEmpty && vectors[$0] == nil })
            if !need.isEmpty {
                if let e = embed(need) { for (t, v) in zip(need, e) { vectors[t] = v } }
                else { embedRetry = Date().addingTimeInterval(60) }  // Ollama down: don't stall every refresh
            }
            if let a = vectors[context] { for it in items { if let b = vectors[it.agent] { cos[it.agent] = Self.cosine(a, b) } } }
        }
        return items.map { it in
            let then = Self.words(it.agent)
            let jac = now.isEmpty || then.isEmpty ? 0 : Double(now.intersection(then).count) / Double(now.union(then).count)
            return max(jac, (cos[it.agent] ?? 0) - 0.2)
        }
    }

    static func cosine(_ a: [Float], _ b: [Float]) -> Double {
        var d: Float = 0, na: Float = 0, nb: Float = 0
        for i in 0..<min(a.count, b.count) { d += a[i] * b[i]; na += a[i] * a[i]; nb += b[i] * b[i] }
        return na > 0 && nb > 0 ? Double(d / (na * nb).squareRoot()) : 0
    }

    /// Score each distinct past reply by the best similarity between the current agent
    /// message and an agent message it answered, plus how often it was sent. Without a close enough match,
    /// a wrong offer costs a gesture, so only replies above the threshold are offered.
    func offers() -> [String] {
        var score: [String: (sim: Double, n: Int)] = [:]
        for (it, sim) in zip(items, similarities()) {
            let s = score[it.reply] ?? (0, 0)
            score[it.reply] = (max(s.sim, sim), s.n + 1)
        }
        var ranked: [(reply: String, s: Double)] = []
        for (reply, v) in score where v.sim >= 0.25 { ranked.append((reply, v.sim + 0.05 * log(Double(v.n)))) }
        ranked.sort { $0.s != $1.s ? $0.s > $1.s : $0.reply < $1.reply }
        return ranked.prefix(maxOffers).map(\.reply)
    }
}
