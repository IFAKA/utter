import Accelerate
import Foundation

/// Tiny next-word LSTM (ml/utter/lm.py, Gboard-class ~1.4M params, int8 `lm.bin` + `vocab.txt`).
/// This is the host-side reference of what the wearable runs; the device only needs the logits of the
/// candidates matching the token code, here we compute the whole vocabulary for the benchmark.
public final class NeuralPredictor: Predictor {
    public let V: Int, E: Int, H: Int
    let vocab: [String]
    let ids: [String: Int]
    let emb: [Float], wih: [Float], whh: [Float], b: [Float], proj: [Float], bias: [Float]
    public var top = 300
    private var states: [String: (h: [Float], c: [Float])] = [:]
    private var cache: [String: [(word: String, logp: Double)]] = [:]

    /// The chat + coding model shipped with the app (ml/data/lm-code, English only).
    public static func bundled() -> NeuralPredictor? {
        Bundle.module.url(forResource: "Resources/lm", withExtension: nil).flatMap { NeuralPredictor(dir: $0.path) }
    }

    public init?(dir: String) {
        guard let d = FileManager.default.contents(atPath: dir + "/lm.bin"),
              let vt = try? String(contentsOfFile: dir + "/vocab.txt", encoding: .utf8),
              d.count > 16, d.prefix(4) == Data("ULM1".utf8) else { return nil }
        var off = 4
        func i32() -> Int { defer { off += 4 }; return Int(d.subdata(in: off..<off + 4).withUnsafeBytes { $0.loadUnaligned(as: Int32.self) }) }
        func f32s(_ n: Int) -> [Float] {
            defer { off += 4 * n }
            return d.subdata(in: off..<off + 4 * n).withUnsafeBytes { Array($0.bindMemory(to: Float.self)) }
        }
        func q8() -> [Float] {
            let rows = i32(), cols = i32()
            let s = f32s(rows)
            var w = [Float](repeating: 0, count: rows * cols)
            d.subdata(in: off..<off + rows * cols).withUnsafeBytes { raw in
                let q = raw.bindMemory(to: Int8.self)
                for r in 0..<rows { for c in 0..<cols { w[r * cols + c] = Float(q[r * cols + c]) * s[r] } }
            }
            off += rows * cols
            return w
        }
        V = i32(); E = i32(); H = i32()
        emb = q8(); wih = q8(); whh = q8()
        b = f32s(i32())
        proj = q8()
        bias = f32s(i32())
        vocab = vt.split(separator: "\n", omittingEmptySubsequences: false).prefix(V).map(String.init)
        ids = Dictionary(vocab.enumerated().map { ($1, $0) }, uniquingKeysWith: { a, _ in a })
        guard vocab.count == V, emb.count == V * E, bias.count == V else { return nil }
    }

    /// y = W x for a row-major rows x cols matrix.
    private func gemv(_ w: [Float], _ rows: Int, _ cols: Int, _ x: [Float]) -> [Float] {
        var y = [Float](repeating: 0, count: rows)
        cblas_sgemv(CblasRowMajor, CblasNoTrans, Int32(rows), Int32(cols), 1, w, Int32(cols), x, 1, 0, &y, 1)
        return y
    }

    private func step(_ id: Int, _ s: (h: [Float], c: [Float])) -> (h: [Float], c: [Float]) {
        let x = Array(emb[id * E..<(id + 1) * E])
        var g = gemv(wih, 4 * H, E, x)
        let r = gemv(whh, 4 * H, H, s.h)
        for k in 0..<4 * H { g[k] += r[k] + b[k] }
        func sig(_ v: Float) -> Float { 1 / (1 + exp(-v)) }
        var h = [Float](repeating: 0, count: H), c = h
        for k in 0..<H {  // gate order i, f, g, o
            c[k] = sig(g[H + k]) * s.c[k] + sig(g[k]) * tanh(g[2 * H + k])
            h[k] = sig(g[3 * H + k]) * tanh(c[k])
        }
        return (h, c)
    }

    /// LSTM state after "<s> w1 .. wn", reusing the state of the longest cached prefix.
    private func state(_ words: [String]) -> (h: [Float], c: [Float]) {
        let key = words.joined(separator: " ")
        if let s = states[key] { return s }
        let prev = words.isEmpty ? step(1, ([Float](repeating: 0, count: H), [Float](repeating: 0, count: H)))
            : step(ids[words.last!] ?? 2, state(Array(words.dropLast())))
        states[key] = prev
        return prev
    }

    public func predict(context: String) -> [(word: String, logp: Double)] {
        let words = NgramPredictor.words(context)
        let key = words.joined(separator: " ")
        if let c = cache[key] { return c }
        let p = gemv(proj, E, H, state(words).h)
        var logits = gemv(emb, V, E, p)
        vDSP_vadd(logits, 1, bias, 1, &logits, 1, vDSP_Length(V))
        let mx = logits.max() ?? 0
        let lse = log(logits.reduce(0) { $0 + exp($1 - mx) }) + mx
        let best = (3..<V).sorted { logits[$0] > logits[$1] }.prefix(top)  // skip <pad> <s> <unk>
        let out = best.map { (vocab[$0], Double(logits[$0] - lse)) }
        cache[key] = out
        return out
    }
}
