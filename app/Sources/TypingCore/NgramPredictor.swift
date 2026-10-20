import Foundation

/// Bigram next-word model, small enough for the wearable (no host, no LLM).
/// Input: Norvig's Google-web counts (https://norvig.com/ngrams/): `count_2w.txt` ("w1 w2\tcount",
/// with "<S>" = sentence start) and `count_1w.txt` ("w\tcount") for the denominators.
/// log P(w2 | w1) = ln(c(w1 w2) / c(w1)); words without a bigram fall back to the decoder's unigram score.
public final class NgramPredictor: Predictor {
    private var next: [String: [(word: String, logp: Double)]] = [:]
    public private(set) var pairs = 0

    /// keep: followers kept per previous word (pruning for the device's flash budget).
    public init?(bigrams: String, unigrams: String, lexicon: Lexicon, keep: Int = 100) {
        guard let b = try? String(contentsOfFile: bigrams, encoding: .utf8),
              let u = try? String(contentsOfFile: unigrams, encoding: .utf8) else { return nil }
        var uni: [String: Double] = [:]
        for line in u.split(separator: "\n") {
            let f = line.split(separator: "\t")
            if f.count == 2, let c = Double(f[1]) { uni[f[0].lowercased(), default: 0] += c }
        }
        let vocab = Set(lexicon.entries.map(\.word))
        var raw: [String: [String: Double]] = [:]
        for line in b.split(separator: "\n") {
            let f = line.split(separator: "\t")
            guard f.count == 2, let c = Double(f[1]) else { continue }
            let w = f[0].split(separator: " ")
            guard w.count == 2 else { continue }
            let w1 = w[0] == "<S>" ? "<S>" : w[0].lowercased(), w2 = w[1].lowercased()
            guard w1 == "<S>" || vocab.contains(w1), vocab.contains(w2) else { continue }
            raw[w1, default: [:]][w2, default: 0] += c
        }
        for (w1, f) in raw {
            // "<S>" has no unigram count: use the listed total (overestimates these probabilities a little).
            let total = max(uni[w1] ?? 0, f.values.reduce(0, +))
            let top = f.sorted { $0.value > $1.value }.prefix(keep)
            next[w1] = top.map { ($0.key, log($0.value / total)) }
            pairs += top.count
        }
    }

    /// Personal bigrams from what the user typed (Gboard-style adaptation), mixed with the web model.
    private var mine: [String: [String: Double]] = [:]
    public var personalWeight = 0.5

    public func forget() { mine = [:] }

    public func learn(_ sentence: String) {
        var prev = "<S>"
        for w in Self.words(sentence) {
            mine[prev, default: [:]][w, default: 0] += 1
            prev = w
        }
    }

    public func predict(context: String) -> [(word: String, logp: Double)] {
        let prev = Self.words(context).last ?? "<S>"
        let web = next[prev] ?? []
        guard let p = mine[prev] else { return web }
        let n = p.values.reduce(0, +), lam = personalWeight
        var prob = Dictionary(web.map { ($0.word, (1 - lam) * exp($0.logp)) }, uniquingKeysWith: +)
        for (w, c) in p { prob[w, default: 0] += lam * c / n }
        return prob.sorted { $0.value > $1.value }.map { ($0.key, log($0.value)) }
    }

    static func words(_ s: String) -> [String] {
        s.lowercased().split(whereSeparator: { !($0.isLetter || $0 == "'") }).map(String.init)
    }
}
