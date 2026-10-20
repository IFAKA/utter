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
/// With an empty code, candidates are the language model's next-word predictions, plus "." and newline;
/// before the first word, whole-reply phrases from the predictor come first.
/// quickPick: right after one NEXT from the predictions, G1..G4 accept candidates 3..6 directly.
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
    public var quickPick = false
    /// Words typed through the speller, offered like lexicon words from then on (personal vocabulary).
    public private(set) var learned: [String: [Int]] = [:]
    lazy var speller = Speller(lexicon: lexicon)
    /// Letter mode, entered by accepting `spellMarker` (the last candidate): the word so far, one letter per
    /// group token; NEXT swaps the last letter for the next likeliest in its group, BACK deletes a letter
    /// (or leaves the mode), ACCEPT types the word and learns it.
    public private(set) var spelling: String?
    private var letterRank = 0
    public static let spellMarker = "✎"

    public init(lexicon: Lexicon, predictor: Predictor = NoPredictor(), armed: Bool = false) {
        self.lexicon = lexicon
        self.predictor = predictor
        self.armed = armed
        refresh()
    }

    /// Start a fresh message (e.g. the agent replied): forget the typed text so predictions restart.
    public func newMessage() {
        text = ""
        typedWords = []
        code = []
        refresh()
    }

    public var current: String? { spelling ?? (candidates.isEmpty ? nil : candidates[index % candidates.count]) }

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
            if text.isEmpty {
                let ph = predictor.phrases()
                if !ph.isEmpty {
                    let head: [String] = Array(ph.prefix(1)) + Array(c.prefix(1))
                    c = head + Array(ph.dropFirst()) + Array(c.dropFirst())
                }
            }
            if !context.trimmingCharacters(in: .whitespaces).isEmpty {
                // Remembered replies that start with what was typed: second, so a wrong one costs at most one NEXT.
                let comp = predictor.completions(of: context).filter { !c.contains($0) }
                c = Array(c.prefix(1)) + comp + Array(c.dropFirst()) + [".", Self.newline]
            }
            candidates = Array(c.prefix(14))
            return
        }
        var score: [String: Double] = [:]
        for e in lexicon.matches(code) {
            score[e.word] = (lm[e.word] ?? backoff(e.zipf)) + (e.code.count == code.count ? 1.5 : 0)
        }
        for (w, c) in learned where score[w] == nil && c.count >= code.count && Array(c.prefix(code.count)) == code {
            score[w] = (lm[w] ?? backoff(4)) + (c.count == code.count ? 1.5 : 0)
        }
        for (w, lp) in preds where score[w] == nil {
            let c = LetterGroups.code(w)
            if c.count >= code.count, Array(c.prefix(code.count)) == code {
                score[w] = lp + (c.count == code.count ? 1.5 : 0)
            }
        }
        let ranked = score.sorted { $0.value != $1.value ? $0.value > $1.value : $0.key < $1.key }.map(\.key)
        // Top 20, then every remaining exact-length match, so no lexicon word is unreachable.
        let top = ranked.prefix(20)
        candidates = Array(top) + ranked.dropFirst(20).filter { LetterGroups.code($0).count == code.count } + [Self.spellMarker]
    }

    @discardableResult
    public func handle(_ a: Action) -> [Output] {
        if a == .wake {
            armed.toggle()
            if armed { refresh() }
            return [.earcon(a), .speak(armed ? "ready" : "paused")]
        }
        guard armed else { return [] }
        if spelling != nil { return [.earcon(a)] + letter(a) }
        var out: [Output] = [.earcon(a)]
        switch a {
        case .g1, .g2, .g3, .g4:
            if quickPick && code.isEmpty && index == 1 && candidates.count > 2 + a.group! {
                index = 2 + a.group!
                out += accept()
            } else {
                code.append(a.group!)
                refresh()
            }
        case .next:
            if !candidates.isEmpty { index = (index + 1) % candidates.count }
        case .accept:
            out += accept()
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
        if let c = current, spelling == nil { out.append(.speak(c == Self.newline ? "new line" : (c == "." ? "period" : (c == Self.spellMarker ? "spell" : c)))) }
        return out
    }

    private func letter(_ a: Action) -> [Output] {
        guard var s = spelling else { return [] }
        switch a {
        case .g1, .g2, .g3, .g4:
            s.append(speller.letters(a.group!, after: s)[0])
            letterRank = 0
        case .next:
            if let l = s.last, let g = LetterGroups.group(of: l) {
                s.removeLast()
                let ls = speller.letters(g, after: s)
                letterRank = (letterRank + 1) % ls.count
                s.append(ls[letterRank])
            }
        case .back:
            if s.isEmpty {
                spelling = nil
                refresh()
                return [.speak("words")]
            }
            s.removeLast()
            if let l = s.last, let g = LetterGroups.group(of: l) {
                letterRank = speller.letters(g, after: String(s.dropLast())).firstIndex(of: l) ?? 0
            }
        case .accept:
            spelling = nil
            if s.isEmpty {
                refresh()
                return [.speak("words")]
            }
            candidates = [s]
            index = 0
            return accept()
        case .wake:
            break
        }
        spelling = s
        return [.speak(s.last.map(String.init) ?? "spell")]
    }

    private func accept() -> [Output] {
        guard let w = current else { return [] }
        if w == Self.spellMarker {
            spelling = ""
            code = []
            candidates = []
            return [.speak("spell")]
        }
        var out: [Output] = []
        let s = w == Self.newline ? "\n" : (w == "." ? ". " : w + " ")
        let attach = w == "." && text.hasSuffix(" ")  // attach the period to the previous word
        if attach {
            text.removeLast()
            out.append(.backspace(1))
        }
        text += s
        typedWords.append((s, attach))
        if !w.contains(" ") && w != "." && w != Self.newline && !lexicon.contains(w) && learned[w] == nil { learned[w] = LetterGroups.code(w) }
        out.append(.type(s))
        code = []
        refresh()
        return out
    }
}
