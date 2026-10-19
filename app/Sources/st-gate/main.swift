// Stage 0 gate: a simulated user types real sentences through the Decoder while every
// token passes a noisy recognizer (correct with probability p; otherwise missed or confused).
// The user hears each recognized token (earcon) and the current candidate (speech), so
// they react to the decoder's real state: undo wrong groups, delete wrong words, re-wake.
// Usage: st-gate [--lang en|es] [--llm] [--seconds-per-token 1.5] [--sentences N]
//                [--corpus chat|agent] [--context] [--phrases] [--browse N] [--quick-pick]
//   --corpus agent  replies to a coding agent; --context gives the LLM the agent's message,
//   --phrases offers whole replies, --browse N lets the user step N suggestions ahead before
//   spelling, --quick-pick enables NEXT + G1..G4 = candidates 3..6.
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

// (what the agent said, what the user replies)
let agentPairs: [(String, String)] = [
    ("I found the bug in the session check. Should I fix it?", "yes fix it"),
    ("The tests are failing in the login module.", "fix the login test"),
    ("I updated three files. Do you want me to run the tests?", "yes run the tests"),
    ("All 24 tests pass.", "commit the changes"),
    ("Committed. Anything else?", "push it to the main branch"),
    ("I can refactor this function or add a cache. Which one do you prefer?", "add the cache"),
    ("The build failed with a type error in the user model.", "show me the error"),
    ("Here is the plan: add a new endpoint, write tests, then update the docs.", "go ahead"),
    ("Should I also update the documentation?", "yes update the docs too"),
    ("I added logging to the payment service.", "remove the debug logs"),
    ("The query is slow because the email column has no index.", "add an index on the email column"),
    ("Done. The page loads in 200 ms now.", "great now write a test for it"),
    ("I am not sure what the expected behavior is for an empty list.", "it should return an empty list"),
    ("Do you want me to delete the old migration files?", "no keep them"),
    ("I renamed the variable in all files.", "undo that change"),
    ("What should I work on next?", "fix the failing tests first"),
    ("I wrote a summary of the changes. It is about two pages long.", "make it shorter"),
    ("This function has no comments and the logic is hard to follow.", "explain what this function does"),
    ("There are two warnings in the console about deprecated options.", "ignore the warnings for now"),
    ("I created a new branch for the login feature.", "open a pull request"),
    ("The server returns an error when the input is empty.", "handle the empty input case"),
    ("Should I add type hints to the whole file?", "only to the public functions"),
    ("I can't find the config file.", "it is in the root folder"),
    ("The tests pass but the code coverage dropped to sixty percent.", "add tests for the new code"),
    ("Should I continue with the next step of the plan?", "yes continue"),
]

var lang = "en", useLLM = false, corpus = "chat", useContext = false, usePhrases = false, browse = 0, quick = false, secPerToken = 1.5, nSent = 40, seed: UInt64 = 1
var it = CommandLine.arguments.dropFirst().makeIterator()
while let a = it.next() {
    switch a {
    case "--lang": lang = it.next() ?? "en"
    case "--llm": useLLM = true
    case "--seconds-per-token": secPerToken = Double(it.next() ?? "1.5") ?? 1.5
    case "--sentences": nSent = Int(it.next() ?? "40") ?? 40
    case "--corpus": corpus = it.next() ?? "chat"
    case "--context": useContext = true
    case "--phrases": usePhrases = true; useContext = true
    case "--browse": browse = Int(it.next() ?? "0") ?? 0
    case "--quick-pick": quick = true
    case "--seed": seed = UInt64(it.next() ?? "1") ?? 1
    default: print("unknown arg \(a)"); exit(2)
    }
}
let items: [(said: String, reply: String)] = corpus == "agent" ? agentPairs.map { ($0.0, $0.1) }
    : (lang == "es" ? sentencesES : sentencesEN).map { ("", $0) }
let sentences = Array(items.prefix(nSent))
let lexicon = Lexicon(language: lang)
let predictor: Predictor
var ollama: OllamaPredictor?
if useLLM {
    guard OllamaPredictor.available() else { print("Ollama not running (ollama serve)"); exit(2) }
    ollama = OllamaPredictor(language: lang)
    ollama!.suggestPhrases = usePhrases
    predictor = ollama!
} else {
    predictor = NoPredictor()
}

/// What the user does next, given what they hear.
func intent(_ d: Decoder, target: String) -> Action? {
    if !d.armed { return .wake }
    let typed = d.text, goal = target + " "
    if typed == goal { return nil }
    if !goal.hasPrefix(typed) { return .back }  // a wrong word got typed: delete it
    let rest = String(goal.dropFirst(typed.count))
    guard let word = rest.split(separator: " ").first.map(String.init) else { return nil }
    let want = LetterGroups.code(word)
    if d.code.count > want.count || Array(want.prefix(d.code.count)) != d.code { return .back }
    // A candidate is usable if it is a whole-word prefix of what is left (phrases cover several words).
    // Among those reachable within the browse budget, take the one covering most words, then the cheapest.
    let c = d.candidates, n = c.count
    var best: (words: Int, cost: Int, act: Action)?
    func consider(_ i: Int, _ cost: Int, _ act: Action) {
        guard i < n, rest.hasPrefix(c[i] + " ") else { return }
        let w = c[i].split(separator: " ").count
        if best == nil || w > best!.words || (w == best!.words && cost < best!.cost) { best = (w, cost, act) }
    }
    if quick && d.code.isEmpty && d.index == 0 {
        consider(0, 1, .accept)
        for i in 1...5 { consider(i, 2, .next) }
    } else if quick && d.code.isEmpty && d.index == 1 {
        consider(1, 1, .accept)
        for i in 2...5 { consider(i, 1, LetterGroups.action(for: i - 2)) }
    } else if n > 0 {
        for off in 0...min(browse, n - 1) { consider((d.index + off) % n, off + 1, off == 0 ? .accept : .next) }
    }
    if let b = best { return b.act }
    if d.code.count < want.count { return LetterGroups.action(for: want[d.code.count]) }
    return c.contains(word) ? .next : nil  // nil: unreachable word
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
    for (said, s) in sentences {
        ollama?.history = useContext && !said.isEmpty ? "Assistant: \(said)\nUser:" : ""
        let d = Decoder(lexicon: lexicon, predictor: predictor)
        d.quickPick = quick
        var ideal = 0
        do {  // ideal token count for the budget
            let probe = Decoder(lexicon: lexicon, predictor: predictor)
            probe.quickPick = quick
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

print("Stage 0 gate: corpus=\(corpus) context=\(useContext) phrases=\(usePhrases) browse=\(browse) quick=\(quick)")
print("  lang=\(lang) llm=\(useLLM) sentences=\(sentences.count) lexicon=\(lexicon.entries.count) words")
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
