// Stage 0 gate: a simulated user types real sentences through the Decoder while every
// token passes a noisy recognizer (correct with probability p; otherwise missed or confused).
// The user hears each recognized token (earcon) and the current candidate (speech), so
// they react to the decoder's real state: undo wrong groups, delete wrong words, re-wake.
// Usage: st-gate [--lang en|es] [--llm] [--seconds-per-token 1.5] [--sentences N]
//                [--corpus chat|agent] [--context] [--phrases] [--browse N] [--quick-pick]
//   --corpus agent  replies to a coding agent; --context gives the LLM the agent's message,
//   --phrases offers whole replies, --browse N lets the user step N suggestions ahead before
//   spelling, --quick-pick enables NEXT + G1..G4 = candidates 3..6.
//   --confusions F [--set adabn|online] [--map w1,..,w8] [--p-min 0.7] replays real recognizer outputs
//   (ml: utter.crossday --dump F) instead of the synthetic p, rejecting tokens below p-min confidence.
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

/// Written independently of every training set (2026-10-20): care needs, everyday messages, coding chat.
let sentencesFresh = [
    "please raise the head of the bed a little", "my left arm is getting cold", "can you move my hand back to the armrest",
    "i would like some water with a straw", "turn me on my side in an hour", "the mask is leaking near my nose",
    "please wipe my eyes", "i am tired of watching this show", "could you open the window for some fresh air",
    "my back hurts after lunch", "ask the nurse to check the tube", "i want to sit outside for a while",
    "put my glasses on please", "scratch my right ear", "it is too bright in here", "i slept badly last night",
    "tell grandma i miss her", "send the photos from the beach to my brother", "the plumber comes at noon on tuesday",
    "remind me to renew my passport", "did anyone feed the dog", "we should paint the hallway green",
    "the package was left at the neighbor's door", "book a table for four on saturday", "my sister is moving to madrid",
    "can we watch the match together", "the heating is broken again", "pick up some bread on your way home",
    "happy birthday i hope you have a great day", "the bus was full so i walked", "save me a seat near the front",
    "i lost the receipt for the jacket",
    "rename the folder to utils", "the build fails on the second step", "split this function into two smaller ones",
    "show me the full error message", "revert the last commit", "use a dictionary instead of a list here",
    "check the logs from yesterday", "the button should be blue not red", "merge it after the review",
    "write a short readme for this script", "why is the cache always empty", "move the constants to the top of the file",
    "skip that test on windows", "the api key is in the environment", "add a retry when the request times out",
    "stop and wait for my answer",
]

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
// --memory with --reword: later passes ask the same things in other words (written blind to the matcher),
// so a remembered reply must be found from a differently worded agent message.
let reworded: [String: String] = [
    "I found the bug in the session check. Should I fix it?": "Found the cause: the session check skips expired tokens. Want me to patch it?",
    "The tests are failing in the login module.": "Two login tests broke after the merge.",
    "I updated three files. Do you want me to run the tests?": "Changes are in. Shall I run the test suite?",
    "All 24 tests pass.": "Everything is green, 31 of 31 passing.",
    "Committed. Anything else?": "The commit is done. What next?",
    "I can refactor this function or add a cache. Which one do you prefer?": "Two options: cache the results or rewrite the loop. Which way?",
    "The build failed with a type error in the user model.": "Compilation stopped: type mismatch in models/user.ts.",
    "Here is the plan: add a new endpoint, write tests, then update the docs.": "My plan is to write the migration first, then the API. Sound good?",
    "Should I also update the documentation?": "Do you want the README changed as well?",
    "I added logging to the payment service.": "I put print statements in the checkout flow to trace it.",
    "The query is slow because the email column has no index.": "The users lookup does a full table scan on email.",
    "Done. The page loads in 200 ms now.": "Fixed, the dashboard renders twice as fast.",
    "I am not sure what the expected behavior is for an empty list.": "What should happen when the list is empty?",
    "Do you want me to delete the old migration files?": "Can I remove the unused migrations?",
    "I renamed the variable in all files.": "The variable now has the new name everywhere.",
    "What should I work on next?": "I'm done with that task. What's next?",
    "I wrote a summary of the changes. It is about two pages long.": "Here's a detailed write-up of everything I changed.",
    "This function has no comments and the logic is hard to follow.": "I don't understand what parse_rows is doing.",
    "There are two warnings in the console about deprecated options.": "The linter shows some deprecation warnings.",
    "I created a new branch for the login feature.": "The feature branch is pushed.",
    "The server returns an error when the input is empty.": "Empty requests crash the handler with a 500.",
    "Should I add type hints to the whole file?": "Want me to annotate every function with types?",
    "I can't find the config file.": "Where is the settings file?",
    "The tests pass but the code coverage dropped to sixty percent.": "Coverage went down after this change.",
    "Should I continue with the next step of the plan?": "Step two is finished. Move on to step three?",
]
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

var lang = "en", useLLM = false, corpus = "chat", useContext = false, usePhrases = false, browse = 0, quick = false, secPerToken = 1.5, nSent = 40, seed: UInt64 = 1, ngramDir = "", keep = 100, learn = false, neuralDir = "", probe: String?, confPath = "", confSet = "adabn", mapping: [String] = [], pMin = 0.0, pAccept = 0.0, memPasses = 0, reword = false, pass = 0, noOffers = false, embedOn = false
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
    case "--ngram": ngramDir = it.next() ?? ""
    case "--learn": learn = true
    case "--neural": neuralDir = it.next() ?? ""
    case "--reword": reword = true
    case "--no-offers": noOffers = true
    case "--embed": embedOn = true
    case "--memory": memPasses = Int(it.next() ?? "2") ?? 2
    case "--probe": probe = it.next() ?? ""  // print the predictor's top words for this context and exit
    case "--keep": keep = Int(it.next() ?? "100") ?? 100
    case "--confusions": confPath = it.next() ?? ""  // real recognizer outputs (ml: utter.crossday --dump)
    case "--set": confSet = it.next() ?? "adabn"
    case "--map": mapping = (it.next() ?? "").split(separator: ",").map(String.init)  // 8 classes in action order
    case "--p-min": pMin = Double(it.next() ?? "0") ?? 0  // reject tokens below this confidence (engine.py p_min)
    case "--p-accept": pAccept = Double(it.next() ?? "0") ?? 0  // stricter threshold for ACCEPT
    default: print("unknown arg \(a)"); exit(2)
    }
}
let items: [(said: String, reply: String)] = corpus == "agent" ? agentPairs.map { ($0.0, $0.1) }
    : (corpus == "fresh" ? sentencesFresh : lang == "es" ? sentencesES : sentencesEN).map { ("", $0) }
let sentences = Array(items.prefix(nSent))
let lexicon = Lexicon(language: lang)
var predictor: Predictor
var ollama: OllamaPredictor?
var ngram: NgramPredictor?
if useLLM {
    guard OllamaPredictor.available() else { print("Ollama not running (ollama serve)"); exit(2) }
    ollama = OllamaPredictor(language: lang)
    ollama!.suggestPhrases = usePhrases
    guard ollama!.warmUp() else { print("Ollama could not load the model"); exit(2) }
    predictor = ollama!
} else if !neuralDir.isEmpty {
    guard let nn = NeuralPredictor(dir: neuralDir) else { print("no lm.bin / vocab.txt in \(neuralDir)"); exit(2) }
    print("  neural: V=\(nn.V) E=\(nn.E) H=\(nn.H)")
    predictor = nn
} else if !ngramDir.isEmpty {
    guard let ng = NgramPredictor(bigrams: ngramDir + "/count_2w.txt", unigrams: ngramDir + "/count_1w.txt",
                                  lexicon: lexicon, keep: keep) else { print("no count_2w.txt / count_1w.txt in \(ngramDir)"); exit(2) }
    print("  ngram: \(ng.pairs) bigrams kept (\(keep) per word)")
    predictor = ng
    ngram = ng
} else {
    predictor = NoPredictor()
}

// --memory N: wrap the predictor in a reply memory and type the corpus N times; pass 1 measures the cost of
// wrong offers (only earlier, different replies are remembered), later passes the gain when situations recur.
var memory: ReplyMemory?
if memPasses > 0 { memory = ReplyMemory(base: predictor); if noOffers { memory!.maxOffers = 0 }; if embedOn { memory!.embed = { OllamaPredictor.embed($0) } }; predictor = memory! }

if let ctx = probe {
    for (w, lp) in predictor.predict(context: ctx).prefix(5) { print(String(format: "%@ %.4f", w, lp)) }
    exit(0)
}

/// Real recognizer outputs: per true class, softmax vectors from SpeechNet on SilentWear's held-out days.
/// The 8 commands map to the 8 actions in alphabetical order (or --map); "rest" means the token was missed.
struct Confusions {
    var classes: [String] = [], byClass: [String: [[Double]]] = [:], accuracy = 0.0
    init?(path: String, set: String) {
        guard let d = FileManager.default.contents(atPath: path),
              let j = try? JSONSerialization.jsonObject(with: d) as? [String: Any],
              let cls = j["classes"] as? [String], let rows = j[set] as? [[String: Any]] else { return nil }
        classes = cls
        var hit = 0
        for r in rows {
            let l = r["label"] as! String, p = r["p"] as! [Double]
            byClass[l, default: []].append(p)
            if cls[p.indices.max { p[$0] < p[$1] }!] == l { hit += 1 }
        }
        accuracy = Double(hit) / Double(rows.count)
    }
    var words: [String] { mapping.isEmpty ? classes.filter { $0 != "rest" } : mapping }
}
var conf: Confusions?
if !confPath.isEmpty {
    guard let c = Confusions(path: confPath, set: confSet) else { print("cannot read \(confPath) set \(confSet)"); exit(2) }
    conf = c
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
    if let s = d.spelling {  // letter mode
        let w = Array(word), n = s.count
        if n > w.count || !word.hasPrefix(String(s.dropLast())) { return .back }
        if !word.hasPrefix(s) { return LetterGroups.group(of: s.last!) == LetterGroups.group(of: w[n - 1]) ? .next : .back }
        return n == w.count ? .accept : LetterGroups.action(for: want[n])
    }
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
    if c.contains(word) { return .next }
    // Not in the list: go to the spell marker and type it letter by letter.
    if d.code == want && c.contains(Decoder.spellMarker) { return d.current == Decoder.spellMarker ? .accept : .next }
    return nil  // unreachable word
}

func corrupt(_ a: Action, p: Double, rng: inout RNG) -> Action? {
    if Double.random(in: 0..<1, using: &rng) < p { return a }
    if Double.random(in: 0..<1, using: &rng) < 0.25 { return nil }
    return Action.allCases.filter { $0 != a }.randomElement(using: &rng)
}

/// One recognized token: sample a real output for the intended action's class.
func recognize(_ a: Action, rng: inout RNG, d: Decoder) {
    let c = conf!, w = c.words
    let p = c.byClass[w[Action.allCases.firstIndex(of: a)!]]!.randomElement(using: &rng)!
    let top = c.classes[p.indices.max { p[$0] < p[$1] }!]
    guard top != "rest", let got = w.firstIndex(of: top).map({ Action.allCases[$0] }),
          p.max()! >= (got == .accept ? max(pMin, pAccept) : pMin) else { return }
    d.handle(got)
}

struct Result { var done = 0, tokens = 0, words = 0, chars = 0, unreachable = 0 }

func run(p: Double) -> Result {
    var rng = RNG(s: seed)
    var r = Result()
    ngram?.forget()
    for (said0, s) in sentences {
        let said = reword && pass > 0 ? reworded[said0] ?? said0 : said0
        ollama?.history = useContext && !said.isEmpty ? "Assistant: \(said)\nUser:" : ""
        memory?.context = said
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
            if conf != nil { recognize(a, rng: &rng, d: d) } else if let got = corrupt(a, p: p, rng: &rng) { d.handle(got) }
        }
        if !ok && intent(d, target: s) == nil && d.text != s + " " {
            r.unreachable += 1
            if p == 1.0 { print("  unreachable after \"\(d.text)\" code=\(d.code) candidates=\(d.candidates.prefix(8))") }
        }
        if !ok && p == 0.8 { print("  failed at \(conf != nil ? "real" : "80%") (\(n >= budget ? "budget \(budget)" : "stuck")): \(s) | typed \"\(d.text)\" spelling=\(d.spelling ?? "-")") }
        if learn { ngram?.learn(s) }  // the device learns each sentence after it is typed
        if ok { memory?.remember(s, to: said) }
        if ok { r.done += 1; r.tokens += n; r.words += s.split(separator: " ").count; r.chars += s.count + 1 }
    }
    return r
}

print("Stage 0 gate: corpus=\(corpus) context=\(useContext) phrases=\(usePhrases) browse=\(browse) quick=\(quick)")
print("  lang=\(lang) llm=\(useLLM) sentences=\(sentences.count) lexicon=\(lexicon.entries.count) words")
print("p(correct)  completed  tokens/word  tokens/char  est. wpm @\(secPerToken)s/token")
var gate = false
if let c = conf {
    print(String(format: "  real recognizer (%@, %@ set): %.1f%% token accuracy", confPath, confSet, c.accuracy * 100))
}
for (passIndex, p) in (memPasses > 0 ? Array(repeating: 0.8, count: memPasses) : conf != nil ? [0.8] : [1.0, 0.9, 0.8, 0.7, 0.6]).enumerated() {
    pass = passIndex
    if memPasses > 0 { print("  memory pass \(passIndex + 1) (\(memory!.count) replies remembered)") }
    let r = run(p: p)
    let tpw = Double(r.tokens) / Double(max(1, r.words))
    let wpm = 60.0 / (tpw * secPerToken)
    print(String(format: "  %@        %3d/%-3d    %6.2f       %5.2f        %4.1f%@", conf != nil ? "real" : String(format: "%.0f%%", p * 100), r.done, sentences.count,
                 tpw, Double(r.tokens) / Double(max(1, r.chars)), wpm, r.unreachable > 0 ? "  (\(r.unreachable) unreachable)" : ""))
    if p == 0.8 { gate = Double(r.done) >= 0.95 * Double(sentences.count) }
}
let at = conf != nil ? "with the real recognizer" : "at 80% token accuracy"
print(gate ? "GATE PASS: >=95% of sentences typed correctly \(at)" : "GATE FAIL: <95% of sentences typed \(at)")
exit(gate ? 0 : 1)
