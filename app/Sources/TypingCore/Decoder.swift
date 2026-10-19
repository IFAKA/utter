import Foundation

/// Side effects the app performs for the decoder.
public enum Output: Equatable {
    case type(String)       // insert text at the cursor
    case backspace(Int)     // delete n characters
    case speak(String)      // short earbud feedback
    case earcon(Action)     // token acknowledged (distinct sound per token)
}

/// Turns 8 silent-token actions into text.
///   G1..G4  add a letter group to the current word code (T9-style, 4 groups)
///   NEXT    cycle to the next candidate
///   ACCEPT  type the current candidate + space
///   BACK    remove the last group, or delete the last typed word if the code is empty
///   WAKE    arm / pause (paused ignores everything except WAKE)
/// With an empty code, candidates are the language model's next-word predictions, plus "." and newline.
public final class Decoder {
    public private(set) var armed = false
    public private(set) var code: [Int] = []
    public private(set) var candidates: [String] = []
    public private(set) var index = 0
    public private(set) var text = ""            // everything typed this session
    private var typedWords: [(s: String, attached: Bool)] = []  // as typed, for BACK
    let lexicon: Lexicon
    let predictor: Predictor
    public static let newline = "⏎"

    public init(lexicon: Lexicon, predictor: Predictor = NoPredictor(), armed: Bool = false) {
        self.lexicon = lexicon
        self.predictor = predictor
        self.armed = armed
        refresh()
    }

    public var current: String? { candidates.isEmpty ? nil : candidates[index % candidates.count] }

    /// Current sentence (text after the last sentence end), the LLM context.
    var context: String {
        let t = text
        if let r = t.lastIndex(where: { ".?!\n".contains($0) }) { return String(t[t.index(after: r)...]) }
        return t
    }

    /// Candidate score in natural-log units: LM log-probability when the LM proposed the word,
    /// otherwise a unigram backoff (zipf = log10 frequency per billion words).
    func refresh() {
        index = 0
        let preds = predictor.predict(context: context)
        let lm = Dictionary(preds.map { ($0.word, $0.logp) }, uniquingKeysWith: max)
        func backoff(_ zipf: Double) -> Double { (zipf - 9) * 2.302585 - 1.5 }
        if code.isEmpty {
            var c = preds.map(\.word).filter { lexicon.contains($0) }
            if !context.trimmingCharacters(in: .whitespaces).isEmpty { c += [".", Self.newline] }
            candidates = Array(c.prefix(14))
            return
        }
        var score: [String: Double] = [:]
        for e in lexicon.matches(code) {
            score[e.word] = (lm[e.word] ?? backoff(e.zipf)) + (e.code.count == code.count ? 1.5 : 0)
        }
        for (w, lp) in preds where score[w] == nil {
            let c = LetterGroups.code(w)
            if c.count >= code.count, Array(c.prefix(code.count)) == code {
                score[w] = lp + (c.count == code.count ? 1.5 : 0)
            }
        }
        candidates = score.sorted { $0.value != $1.value ? $0.value > $1.value : $0.key < $1.key }.prefix(20).map(\.key)
    }

    @discardableResult
    public func handle(_ a: Action) -> [Output] {
        if a == .wake {
            armed.toggle()
            if armed { refresh() }
            return [.earcon(a), .speak(armed ? "ready" : "paused")]
        }
        guard armed else { return [] }
        var out: [Output] = [.earcon(a)]
        switch a {
        case .g1, .g2, .g3, .g4:
            code.append(a.group!)
            refresh()
        case .next:
            if !candidates.isEmpty { index = (index + 1) % candidates.count }
        case .accept:
            guard let w = current else { break }
            let s = w == Self.newline ? "\n" : (w == "." ? ". " : w + " ")
            let attach = w == "." && text.hasSuffix(" ")  // attach the period to the previous word
            if attach {
                text.removeLast()
                out.append(.backspace(1))
            }
            text += s
            typedWords.append((s, attach))
            out.append(.type(s))
            code = []
            refresh()
        case .back:
            if !code.isEmpty {
                code.removeLast()
                refresh()
            } else if let last = typedWords.popLast() {
                text.removeLast(min(last.s.count, text.count))
                out.append(.backspace(last.s.count))
                if last.attached {
                    text += " "
                    out.append(.type(" "))
                }
                refresh()
            }
        case .wake:
            break
        }
        if let c = current { out.append(.speak(c == Self.newline ? "new line" : (c == "." ? "period" : c))) }
        return out
    }
}
