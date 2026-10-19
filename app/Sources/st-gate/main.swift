// Stage 0 gate: a simulated user types real sentences through the Decoder while every
// token passes a noisy recognizer (correct with probability p; otherwise missed or confused).
// The user hears each recognized token (earcon) and the current candidate (speech), so
// they react to the decoder's real state: undo wrong groups, delete wrong words, re-wake.
// Usage: st-gate [--lang en|es] [--llm] [--seconds-per-token 1.5] [--sentences N]
import Foundation
import TypingCore

struct RNG: RandomNumberGenerator {
    var s: UInt64
    mutating func next() -> UInt64 {
        s &+= 0x9E3779B97F4A7C15
        var z = s
        z = (z ^ (z >> 30)) &* 0xBF58476D1CE4E5B9
        z = (z ^ (z >> 27)) &* 0x94D049BB133111EB
        return z ^ (z >> 31)
    }
}

let sentencesEN = [
    "i will be there in ten minutes", "can you call me when you are free", "the meeting is moved to friday",
    "please send me the report", "i am running a little late", "thank you so much for your help",
    "what time does the train leave", "let me know if you need anything", "i think we should talk tomorrow",
    "are you coming to dinner tonight", "the weather is nice today", "i need to buy some milk",
    "do not forget to bring your keys", "where did you park the car", "i love you",
    "we are out of coffee again", "the kids are already asleep", "my phone battery is almost dead",
    "can we meet after work", "i just finished the first draft", "send me the address please",
    "how was your day", "the doctor said everything is fine", "i will pick you up at the station",
    "turn off the lights before you leave", "happy birthday to my best friend", "i cannot hear you very well",
    "this is taking longer than expected", "we should go for a walk", "remind me to water the plants",
    "the package arrived this morning", "i agree with your plan", "is the store still open",
    "my head hurts a little", "see you next week", "the food was really good",
    "please be quiet for a moment", "i have a question about the bill", "we won the game",
    "good night and sleep well",
]
let sentencesES = [
    "llego en diez minutos", "puedes llamarme cuando puedas", "la reunión es el viernes",
    "envíame el informe por favor", "voy un poco tarde", "muchas gracias por tu ayuda",
    "a qué hora sale el tren", "avísame si necesitas algo", "creo que debemos hablar mañana",
    "vienes a cenar esta noche", "hoy hace buen tiempo", "tengo que comprar leche",
    "no olvides las llaves", "dónde has aparcado el coche", "te quiero mucho",
    "los niños ya están dormidos", "me queda poca batería", "nos vemos después del trabajo",
    "cómo ha ido tu día", "te recojo en la estación",
]

var lang = "en", useLLM = false, secPerToken = 1.5, nSent = 40, seed: UInt64 = 1
var it = CommandLine.arguments.dropFirst().makeIterator()
while let a = it.next() {
    switch a {
    case "--lang": lang = it.next() ?? "en"
    case "--llm": useLLM = true
    case "--seconds-per-token": secPerToken = Double(it.next() ?? "1.5") ?? 1.5
    case "--sentences": nSent = Int(it.next() ?? "40") ?? 40
    case "--seed": seed = UInt64(it.next() ?? "1") ?? 1
    default: print("unknown arg \(a)"); exit(2)
    }
}
let sentences = Array((lang == "es" ? sentencesES : sentencesEN).prefix(nSent))
let lexicon = Lexicon(language: lang)
let predictor: Predictor
if useLLM {
    guard OllamaPredictor.available() else { print("Ollama not running (ollama serve)"); exit(2) }
    predictor = OllamaPredictor(language: lang)
} else {
    predictor = NoPredictor()
}

/// What the user does next, given what they hear.
func intent(_ d: Decoder, target: String) -> Action? {
    if !d.armed { return .wake }
    let typed = d.text
    if typed == target + " " { return nil }
    if !(target + " ").hasPrefix(typed) { return .back }  // a wrong word got typed: delete it
    let rest = String((target + " ").dropFirst(typed.count))
    guard let word = rest.split(separator: " ").first.map(String.init) else { return nil }
    let want = LetterGroups.code(word)
    if d.code.count > want.count || Array(want.prefix(d.code.count)) != d.code { return .back }
    if d.current == word { return .accept }
    if d.code.count < want.count { return LetterGroups.action(for: want[d.code.count]) }
    return d.candidates.contains(word) ? .next : nil  // nil: unreachable word
}

func corrupt(_ a: Action, p: Double, rng: inout RNG) -> Action? {
    if Double.random(in: 0..<1, using: &rng) < p { return a }
    if Double.random(in: 0..<1, using: &rng) < 0.25 { return nil }
    return Action.allCases.filter { $0 != a }.randomElement(using: &rng)
}

struct Result { var done = 0, tokens = 0, words = 0, chars = 0, unreachable = 0 }

func run(p: Double) -> Result {
    var rng = RNG(s: seed)
    var r = Result()
    for s in sentences {
        let d = Decoder(lexicon: lexicon, predictor: predictor)
        var ideal = 0
        do {  // ideal token count for the budget
            let probe = Decoder(lexicon: lexicon, predictor: predictor)
            while let a = intent(probe, target: s), ideal < 500 { probe.handle(a); ideal += 1 }
        }
        let budget = ideal * 6 + 20
        var n = 0, ok = false
        while n < budget {
            guard let a = intent(d, target: s) else { ok = d.text == s + " "; break }
            n += 1
            if let got = corrupt(a, p: p, rng: &rng) { d.handle(got) }
        }
        if !ok && intent(d, target: s) == nil && d.text != s + " " {
            r.unreachable += 1
            if p == 1.0 { print("  unreachable after \"\(d.text)\" code=\(d.code) candidates=\(d.candidates.prefix(8))") }
        }
        if ok { r.done += 1; r.tokens += n; r.words += s.split(separator: " ").count; r.chars += s.count + 1 }
    }
    return r
}

print("Stage 0 gate: lang=\(lang) llm=\(useLLM) sentences=\(sentences.count) lexicon=\(lexicon.entries.count) words")
print("p(correct)  completed  tokens/word  tokens/char  est. wpm @\(secPerToken)s/token")
var gate = false
for p in [1.0, 0.9, 0.8, 0.7, 0.6] {
    let r = run(p: p)
    let tpw = Double(r.tokens) / Double(max(1, r.words))
    let wpm = 60.0 / (tpw * secPerToken)
    print(String(format: "  %.0f%%        %3d/%-3d    %6.2f       %5.2f        %4.1f%@", p * 100, r.done, sentences.count,
                 tpw, Double(r.tokens) / Double(max(1, r.chars)), wpm, r.unreachable > 0 ? "  (\(r.unreachable) unreachable)" : ""))
    if p == 0.8 { gate = Double(r.done) >= 0.95 * Double(sentences.count) }
}
print(gate ? "GATE PASS: >=95% of sentences typed correctly at 80% token accuracy"
           : "GATE FAIL: <95% of sentences typed at 80% token accuracy")
exit(gate ? 0 : 1)
