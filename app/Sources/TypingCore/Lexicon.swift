import Foundation

/// The 8 silent-token actions (config/tokens.json "actions").
public enum Action: String, CaseIterable, Sendable {
    case g1 = "G1", g2 = "G2", g3 = "G3", g4 = "G4", next = "NEXT", accept = "ACCEPT", back = "BACK", wake = "WAKE"

    public var group: Int? {
        switch self {
        case .g1: return 0
        case .g2: return 1
        case .g3: return 2
        case .g4: return 3
        default: return nil
        }
    }
}

/// Four letter groups, T9-style. Accented letters use their base letter's group.
public enum LetterGroups {
    public static let groups = ["abcdef", "ghijklm", "nopqrs", "tuvwxyz"]
    static let fold: [Character: Character] = ["á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ü": "u", "ñ": "n"]

    public static func group(of c: Character) -> Int? {
        let b = fold[c] ?? c
        return groups.firstIndex { $0.contains(b) }
    }

    /// Group code of a word (apostrophes are skipped).
    public static func code(_ word: String) -> [Int] {
        word.lowercased().compactMap { group(of: $0) }
    }

    public static func action(for group: Int) -> Action { [Action.g1, .g2, .g3, .g4][group] }
}

/// Frequency-ranked word list, indexed by group code for prefix lookups.
public final class Lexicon: @unchecked Sendable {
    public struct Entry { public let word: String; public let code: [Int]; public let zipf: Double }
    public let entries: [Entry]
    private var byPrefix: [[Int]: [Int]] = [:]  // code prefix (len <= 3) -> entry indices, freq-sorted
    public let language: String

    public init(language: String = "en", extra: [String] = []) {
        self.language = language
        var list: [Entry] = []
        var seen = Set<String>()
        if let url = Bundle.module.url(forResource: "Resources/words_\(language)", withExtension: "txt"),
           let text = try? String(contentsOf: url, encoding: .utf8) {
            for line in text.split(separator: "\n") {
                let parts = line.split(separator: "\t")
                guard parts.count == 2, let z = Double(parts[1]) else { continue }
                let w = String(parts[0])
                if seen.insert(w).inserted { list.append(Entry(word: w, code: LetterGroups.code(w), zipf: z)) }
            }
        }
        for w in extra where seen.insert(w.lowercased()).inserted {
            list.append(Entry(word: w.lowercased(), code: LetterGroups.code(w), zipf: 3.0))
        }
        entries = list.sorted { $0.zipf > $1.zipf }
        for (i, e) in entries.enumerated() {
            for n in 1...min(3, e.code.count) { byPrefix[Array(e.code.prefix(n)), default: []].append(i) }
        }
    }

    private lazy var words = Set(entries.map(\.word))
    public func contains(_ word: String) -> Bool { words.contains(word) }

    public func zipf(_ word: String) -> Double? { entries.first { $0.word == word }?.zipf }

    /// Words whose code starts with `code`. Exact-length matches first, then completions.
    public func matches(_ code: [Int], limit: Int = 40) -> [Entry] {
        guard !code.isEmpty else { return [] }
        let pool = byPrefix[Array(code.prefix(3))] ?? []
        var exact: [Entry] = [], longer: [Entry] = []
        for i in pool {
            let e = entries[i]
            guard e.code.count >= code.count, Array(e.code.prefix(code.count)) == code else { continue }
            if e.code.count == code.count { if exact.count < limit { exact.append(e) } }
            else if longer.count < limit { longer.append(e) }
            if exact.count >= limit && longer.count >= limit { break }
        }
        return exact + longer
    }
}
