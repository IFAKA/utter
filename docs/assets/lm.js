/* The app's offline next-word model (app/Sources/TypingCore/NeuralPredictor.swift), ported: a tiny int8 LSTM
   trained on chat + coding text (ml/utter/lm.py, ml/data/lm-code). 1.4 MB, runs on the page, no download step. */
window.UtterLM = async function (base) {
  const [bin, vt] = await Promise.all([fetch(base + "lm.bin").then(r => r.arrayBuffer()), fetch(base + "vocab.txt").then(r => r.text())]);
  const dv = new DataView(bin); let off = 4;
  if (new TextDecoder().decode(bin.slice(0, 4)) !== "ULM1") throw new Error("bad lm.bin");
  const i32 = () => { const v = dv.getInt32(off, true); off += 4; return v; };
  const f32s = n => { const a = new Float32Array(n); for (let i = 0; i < n; i++) a[i] = dv.getFloat32(off + 4 * i, true); off += 4 * n; return a; };
  const q8 = () => {
    const rows = i32(), cols = i32(), s = f32s(rows), q = new Int8Array(bin, off, rows * cols), w = new Float32Array(rows * cols);
    for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) w[r * cols + c] = q[r * cols + c] * s[r];
    off += rows * cols; return w;
  };
  const V = i32(), E = i32(), H = i32();
  const emb = q8(), wih = q8(), whh = q8(), b = f32s(i32()), proj = q8(), bias = f32s(i32());
  const vocab = vt.split("\n").slice(0, V), ids = new Map();
  vocab.forEach((w, i) => { if (!ids.has(w)) ids.set(w, i); });
  const gemv = (w, rows, cols, x, x0 = 0) => {
    const y = new Float32Array(rows);
    for (let r = 0; r < rows; r++) { let s = 0; const o = r * cols; for (let c = 0; c < cols; c++) s += w[o + c] * x[x0 + c]; y[r] = s; }
    return y;
  };
  const sig = v => 1 / (1 + Math.exp(-v));
  function step(id, s) {   // gate order i, f, g, o
    const g = gemv(wih, 4 * H, E, emb, id * E), r = gemv(whh, 4 * H, H, s.h), h = new Float32Array(H), c = new Float32Array(H);
    for (let k = 0; k < 4 * H; k++) g[k] += r[k] + b[k];
    for (let k = 0; k < H; k++) { c[k] = sig(g[H + k]) * s.c[k] + sig(g[k]) * Math.tanh(g[2 * H + k]); h[k] = sig(g[3 * H + k]) * Math.tanh(c[k]); }
    return {h, c};
  }
  const states = new Map(), cache = new Map();
  function state(words) {   // state after "<s> w1 .. wn", reusing the longest cached prefix
    const key = words.join(" ");
    if (states.has(key)) return states.get(key);
    const s = words.length ? step(ids.get(words[words.length - 1]) ?? 2, state(words.slice(0, -1)))
      : step(1, {h: new Float32Array(H), c: new Float32Array(H)});
    states.set(key, s); return s;
  }
  return {
    predict(context, top = 300) {
      const words = context.toLowerCase().split(/[^\p{L}']+/u).filter(Boolean), key = words.join(" ");
      if (cache.has(key)) return cache.get(key);
      const logits = gemv(emb, V, E, gemv(proj, E, H, state(words).h));
      let mx = -Infinity; for (let i = 0; i < V; i++) { logits[i] += bias[i]; if (logits[i] > mx) mx = logits[i]; }
      let s = 0; for (let i = 0; i < V; i++) s += Math.exp(logits[i] - mx);
      const lse = mx + Math.log(s), idx = [];
      for (let i = 3; i < V; i++) idx.push(i);   // skip <pad> <s> <unk>
      idx.sort((a, b2) => logits[b2] - logits[a]);
      const out = idx.slice(0, top).map(i => ({word: vocab[i], logp: logits[i] - lse}));
      cache.set(key, out); return out;
    }
  };
};
