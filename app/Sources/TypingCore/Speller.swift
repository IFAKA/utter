import Foundation

/// Fallback for words the lexicon lacks (names, identifiers like "utils"): a character 4-gram model
/// trained on the lexicon's spellings (Witten-Bell backoff). Letter mode uses it to order each group's
/// letters, so a group token types the likeliest letter and NEXT steps to the next one.
public final class Speller: @unchecked Sendable {
    static let order = 4
    private struct Counts { var total = 0.0; var next: [Character: Double] = [:] }
    private var table: [String: Counts] = [:]  // context of 0..3 chars ("^" pads the start) -> next-char counts
    private let alphabet = 27.0                // 26 letters + end of word

    public init(lexicon: Lexicon) {
        for e in lexicon.entries where e.word.allSatisfy({ LetterGroups.group(of: $0) != nil }) {
            let chars = Array(String(repeating: "^", count: Self.order - 1) + e.word) + ["$"]
            for i in (Self.order - 1)..<chars.count {
                for n in 0..<Self.order {
                    let ctx = String(chars[(i - n)..<i])
                    table[ctx, default: Counts()].total += 1
                    table[ctx, default: Counts()].next[chars[i], default: 0] += 1
                }
            }
        }
    }

    /// log P(c | the last 3 chars of `history`), interpolating down to uniform.
    func logp(_ c: Character, after history: String) -> Double {
        let h = Array(String(repeating: "^", count: Self.order - 1) + history).suffix(Self.order - 1)
        var p = 1 / alphabet
        for n in 0..<Self.order {
            guard let t = table[String(h.suffix(n))] else { break }
            let distinct = Double(t.next.count)
            p = ((t.next[c] ?? 0) + distinct * p) / (t.total + distinct)
        }
        return log(p)
    }

    /// Letters of group `g`, most likely first after `prefix` (letter mode: NEXT walks this list).
    public func letters(_ g: Int, after prefix: String) -> [Character] {
        LetterGroups.groups[g].map { ($0, logp($0, after: prefix)) }.sorted { $0.1 > $1.1 }.map(\.0)
    }
}
