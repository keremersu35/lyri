// Lyri Studio — talks to the local API in lts/server.py (no build step).

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const state = { file: null, lyricsMode: "auto", slug: null, song: null, tab: "prep", phase: "home", busy: false,
  video: { aspect: "9:16", quality: 1080, fps: 30, bg: "#8ace00", fg: "#000000", mode: "reveal", blur: true, offset: 0 } };

/* ---------- mascot, toast, sound, confetti ---------- */
function say(text, mood = "idle") {
  const b = $("bubble");
  if (b.textContent !== text) { b.textContent = text; b.style.animation = "none"; b.offsetWidth; b.style.animation = ""; }
  $("mascot").setAttribute("class", `mascot mood-${mood}`);
}
function toast(msg) {
  const t = $("toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("show"), 4500);
}
function chime(notes = [523, 659, 784, 1047]) {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    notes.forEach((f, i) => {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.type = "triangle"; o.frequency.value = f;
      const t = ctx.currentTime + i * 0.09;
      g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.18, t + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.35);
      o.connect(g).connect(ctx.destination); o.start(t); o.stop(t + 0.4);
    });
  } catch {}
}
function confetti() {
  const c = $("confetti"), ctx = c.getContext("2d");
  c.width = innerWidth * devicePixelRatio; c.height = innerHeight * devicePixelRatio;
  const colors = ["#8ace00", "#2fb6f5", "#ff72b6", "#ffc934", "#ff5757"];
  const bits = Array.from({ length: 160 }, () => ({
    x: c.width * .6 + (Math.random() - .5) * c.width * .3, y: c.height * .35,
    vx: (Math.random() - .5) * 26, vy: -Math.random() * 26 - 8, r: Math.random() * 6 + 4,
    rot: Math.random() * 6, vr: (Math.random() - .5) * .4, c: colors[Math.random() * colors.length | 0],
  }));
  let frames = 0;
  (function step() {
    ctx.clearRect(0, 0, c.width, c.height);
    bits.forEach((b) => {
      b.vy += .7; b.vx *= .99; b.x += b.vx; b.y += b.vy; b.rot += b.vr;
      ctx.save(); ctx.translate(b.x, b.y); ctx.rotate(b.rot); ctx.fillStyle = b.c;
      ctx.fillRect(-b.r, -b.r * .6, b.r * 2, b.r * 1.2); ctx.restore();
    });
    if (++frames < 160) requestAnimationFrame(step); else ctx.clearRect(0, 0, c.width, c.height);
  })();
}
function busy(text) {
  state.busy = !!text;
  $("statusPill").classList.toggle("hidden", !text);
  if (text) $("statusText").textContent = text;
}

/* ---------- tabs + stage views ---------- */
function setTab(tab) {
  state.tab = tab;
  $("tabPrep").classList.toggle("on", tab === "prep"); $("tabPrep").setAttribute("aria-selected", tab === "prep");
  $("tabVideo").classList.toggle("on", tab === "video"); $("tabVideo").setAttribute("aria-selected", tab === "video");
  $("panePrep").classList.toggle("hidden", tab !== "prep");
  $("paneVideo").classList.toggle("hidden", tab !== "video");
  $("startBtn").classList.toggle("hidden", tab !== "prep");
  $("videoBtn").classList.toggle("hidden", tab !== "video");
  renderStage();
  if (state.slug) history.replaceState(null, "", `?song=${encodeURIComponent(state.slug)}${tab === "video" ? "&tab=video" : ""}`);
  if (tab === "video") { syncFromPlayer(); say("Pick a format and colors — you'll see it live on the right 👀", "idle"); }
}
function unlockVideo(on) {
  $("tabVideo").disabled = !on;
  $("lockIcon").classList.toggle("hidden", on);
  $("tabVideo").title = on ? "" : "Prepare a song first";
}
function renderStage() {
  const view = state.tab === "video" ? "video" : state.phase;
  ["home", "progress", "result", "video"].forEach((v) =>
    $("view" + v[0].toUpperCase() + v.slice(1)).classList.toggle("hidden", v !== view));
  if (view === "video") requestAnimationFrame(updatePreview);
}
$("tabPrep").onclick = () => setTab("prep");
$("tabVideo").onclick = () => !$("tabVideo").disabled && setTab("video");
$("toVideoBtn").onclick = () => setTab("video");

/* ---------- file pick ---------- */
function wireDrop(el) {
  ["dragenter", "dragover"].forEach((e) => el.addEventListener(e, (ev) => { ev.preventDefault(); el.classList.add("over"); }));
  ["dragleave", "drop"].forEach((e) => el.addEventListener(e, (ev) => { ev.preventDefault(); el.classList.remove("over"); }));
  el.addEventListener("drop", (e) => e.dataTransfer.files[0] && pickFile(e.dataTransfer.files[0]));
}
wireDrop($("drop")); wireDrop($("homeDrop"));
$("homeDrop").addEventListener("click", () => $("fileInput").click());
$("fileInput").addEventListener("change", (e) => e.target.files[0] && pickFile(e.target.files[0]));
$("changeBtn").onclick = () => $("fileInput").click();

function pickFile(f) {
  if (!/\.(mp3|m4a|wav|flac|ogg|aac|opus)$/i.test(f.name)) { toast("That doesn't look like an audio file 🤔"); return; }
  state.file = f;
  const a = $("previewAudio");
  a.pause(); a.src = URL.createObjectURL(f);
  $("fileName").textContent = f.name;
  $("fileSub").textContent = `${(f.size / 1e6).toFixed(1)} MB`;
  a.onloadedmetadata = () => { $("fileSub").textContent = `${fmt(a.duration)} · ${(f.size / 1e6).toFixed(1)} MB`; };
  $("drop").classList.add("hidden"); $("fileBox").classList.remove("hidden");
  const m = f.name.replace(/\.[^.]+$/, "").replace(/_/g, " ").replace(/\s*[\[(](official|lyrics?|audio|video)[^\])]*[\])]/ig, "");
  if (m.includes(" - ")) { const [ar, ti] = m.split(" - "); $("artist").placeholder = ar.trim(); $("title").placeholder = ti.trim(); }
  else { $("artist").placeholder = "Artist (defaults to file name)"; $("title").placeholder = m.trim(); }
  $("startBtn").disabled = state.busy;
  setTab("prep");
  say("Ooh, nice track! 🎶 Paste the lyrics if you have them, otherwise I'll find them. Then hit the green button!", "happy");
}
$("previewBtn").onclick = () => { const a = $("previewAudio"); a.paused ? a.play() : a.pause(); };
$("previewAudio").onplay = () => { $("disc").classList.remove("paused"); $("previewBtn").textContent = "❚❚"; };
$("previewAudio").onpause = () => { $("disc").classList.add("paused"); $("previewBtn").textContent = "▶︎"; };
const fmt = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

/* ---------- segmented controls ---------- */
function seg(id, onChange) {
  $(id).querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    $(id).querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
    onChange(b.dataset.v);
  }));
}
seg("lyricsSeg", (v) => {
  state.lyricsMode = v;
  $("autoBox").classList.toggle("hidden", v !== "auto");
  $("pasteBox").classList.toggle("hidden", v !== "paste");
  if (v === "paste") setTimeout(() => $("lyricsText").focus(), 50);
});
$("lyricsText").addEventListener("input", () => {
  const n = $("lyricsText").value.split("\n").filter((l) => l.trim()).length;
  $("lyricsCount").textContent = `${n} line${n === 1 ? "" : "s"}`;
});

/* ---------- process ---------- */
const STAGES = ["separate", "transcribe", "lyrics", "align"];
const WEIGHT = { separate: [0, .5], transcribe: [.5, .8], lyrics: [.8, .83], align: [.83, 1] };
const TIPS = {
  queued: ["In the queue, starting soon…"],
  separate: ["Politely showing the drums out of the room 🥁", "Hushing the bass so only the voice is left 🎸", "Picking the vocals out of the mix ✂️"],
  transcribe: ["All ears 👂", "Listening closely to what they're singing…"],
  lyrics: ["Looking up the lyrics 🔎", "Double-checking it's the right song…"],
  align: ["Placing every word to the millisecond 🎯", "Matching it letter by letter…"],
};
let fake = 0;
function overall(stage, frac) {
  if (!WEIGHT[stage]) return stage === "done" ? 1 : 0;
  const [a, b] = WEIGHT[stage];
  if (frac != null) return a + (b - a) * frac;
  fake = Math.min(fake + 0.012, 0.9);  // stages without real progress creep forward
  return a + (b - a) * fake;
}
$("startBtn").onclick = async () => {
  if (!state.file || state.busy) return;
  const fd = new FormData();
  fd.append("audio", state.file);
  if (state.lyricsMode === "paste") fd.append("lyrics", $("lyricsText").value);
  fd.append("artist", $("artist").value.trim());
  fd.append("title", $("title").value.trim());
  $("startBtn").disabled = true;
  $("previewAudio").pause();
  unlockVideo(false);
  busy("Uploading");
  say("Uploading… 📦", "work");
  try {
    const res = await fetch("/api/process", { method: "POST", body: fd });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    const { job, slug } = await res.json();
    state.slug = slug;
    state.phase = "progress"; setTab("prep");
    document.querySelectorAll(".node").forEach((n) => n.classList.remove("active", "done"));
    $("pfill").style.width = "0%"; $("plog").textContent = "";
    await pollProcess(job);
  } catch (e) {
    state.phase = state.song ? "result" : "home"; renderStage();
    unlockVideo(!!state.song && !state.song.meta.instrumental);
    say("Oh no, something went wrong 😢", "sad");
    toast(`Error: ${e.message}`);
  } finally {
    busy(null);
    $("startBtn").disabled = !state.file;
  }
};
async function pollProcess(jobId) {
  let lastStage = null, tipIdx = 0, tipAt = 0;
  while (true) {
    const j = await (await fetch(`/api/jobs/${jobId}`)).json();
    if (j.stage !== lastStage) { fake = 0; lastStage = j.stage; tipIdx = 0; tipAt = 0; }
    const idx = STAGES.indexOf(j.stage);
    document.querySelectorAll(".node").forEach((n, i) => {
      n.classList.toggle("done", j.status === "done" || i < idx);
      n.classList.toggle("active", j.status !== "done" && i === idx);
    });
    const p = j.status === "done" ? 1 : overall(j.stage, j.frac);
    $("pfill").style.width = `${Math.round(p * 100)}%`;
    $("ppct").textContent = `${Math.round(p * 100)}%`;
    busy(`Preparing · ${Math.round(p * 100)}%`);
    if (Date.now() - tipAt > 3500) {
      const tips = TIPS[j.stage] || TIPS.queued;
      $("ptip").textContent = j.status === "queued" && j.queue_position ? `Waiting in line (#${j.queue_position})…` : tips[tipIdx++ % tips.length];
      say($("ptip").textContent, "work");
      tipAt = Date.now();
    }
    $("plog").textContent = j.logs.join("\n");
    if (j.status === "done") break;
    if (j.status === "error") throw new Error(j.error);
    await new Promise((r) => setTimeout(r, 600));
  }
  await loadSong(state.slug, true);
}

/* ---------- result ---------- */
async function loadSong(slug, celebrate = false) {
  const res = await fetch(`/api/songs/${slug}`);
  if (!res.ok) throw new Error("not found");
  const s = await res.json();
  state.slug = slug; state.song = s; state.phase = "result";
  const m = s.meta;
  $("resTitle").textContent = [m.artist, m.title].filter(Boolean).join(" – ") || "Ready!";
  const src = { "user-text": "your lyrics", "user-lrc": "your LRC", "lrclib-synced": "LRCLIB · synced", "lrclib-plain": "LRCLIB", transcription: "by ear" }[m.lyrics_source] || "—";
  const low = s.words ? s.low_confidence / s.words : 0;
  $("stats").innerHTML = m.instrumental ? "" : `
    <div class="stat g"><span class="v">${s.lines}</span><span class="k">lines</span></div>
    <div class="stat s"><span class="v">${s.words}</span><span class="k">words</span></div>
    <div class="stat y"><span class="v">${Math.round(low * 100)}%</span><span class="k">unsure</span></div>
    <div class="stat p"><span class="k">lyrics</span><span class="v">${esc(src)}</span></div>`;
  const note = $("resNote");
  note.classList.toggle("hidden", !(m.instrumental || low > 0.15));
  note.textContent = m.instrumental
    ? "I can't hear any vocals — this looks like an instrumental 🎻"
    : "I'm unsure in a few places. Give it a look in the player and tell me if anything drifts 🙏";
  $("toVideoBtn").classList.toggle("hidden", !!m.instrumental);
  $("playerFrame").src = `/out/${slug}/index.html`;
  const files = [["lyrics.json", "JSON"], ["lyrics.lrc", "LRC"], ["lyrics.srt", "SRT"], ["lyrics.ass", "ASS"]];
  $("downloads").innerHTML = files.map(([f, l]) => `<a class="btn ghost small" href="/out/${slug}/${f}" download>⬇ ${l}</a>`).join("");
  unlockVideo(!m.instrumental);
  renderVideos();
  startPreview();
  if (state.tab === "video" && m.instrumental) setTab("prep"); else renderStage();
  history.replaceState(null, "", `?song=${encodeURIComponent(slug)}`);
  if (celebrate) {
    if (m.instrumental) say("Hmm, nobody's singing in this one 🎻", "sad");
    else { say("Done! 🎉 Every word is in place. Like it? Let's make a video!", "happy"); confetti(); chime(); }
  }
  refreshLibrary();
}

/* ---------- video settings ---------- */
const FORMATS = [
  { k: "9:16", label: "TikTok · Reels", w: 9, h: 16 },
  { k: "4:5", label: "Instagram", w: 4, h: 5 },
  { k: "1:1", label: "Square", w: 1, h: 1 },
  { k: "16:9", label: "YouTube", w: 16, h: 9 },
  // iPod classic: 320x240 screen; H.264 Baseline L3.0, 30 fps max (Apple spec sheet)
  { k: "iPod", label: "iPod classic", w: 4, h: 3, fixed: [320, 240], profile: "ipod" },
];
const PRESETS = [
  ["#8ace00", "#000000", "brat"], ["#ffffff", "#000000", "white"], ["#ff9ad5", "#000000", "pink"],
  ["#000000", "#8ace00", "night"], ["#8fd3ff", "#0b2a4a", "sky"], ["#ffe45c", "#000000", "sun"], ["#1b1b1b", "#ffffff", "mono"],
];
$("formatTiles").innerHTML = FORMATS.map((f) => {
  const s = 26 / Math.max(f.w, f.h);
  return `<button class="tile ${f.k === state.video.aspect ? "on" : ""}" data-k="${f.k}">
    <div class="shape" style="width:${f.w * s}px;height:${f.h * s}px"></div><b>${f.k}</b><small>${f.label}</small></button>`;
}).join("");
$("formatTiles").querySelectorAll(".tile").forEach((t) => t.onclick = () => {
  $("formatTiles").querySelectorAll(".tile").forEach((x) => x.classList.toggle("on", x === t));
  state.video.aspect = t.dataset.k; applyFormatLimits(); updatePreview();
});
function applyFormatLimits() {
  const f = FORMATS.find((x) => x.k === state.video.aspect);
  const locked = !!f.fixed;
  $("qualitySeg").querySelectorAll("button").forEach((b) => b.disabled = locked);
  const fps60 = $("fpsSeg").querySelector('[data-v="60"]');
  fps60.disabled = locked;
  if (locked && state.video.fps === 60) $("fpsSeg").querySelector('[data-v="30"]').click();
  $("ipodHint").classList.toggle("hidden", f.profile !== "ipod");
}
$("swatches").innerHTML = PRESETS.map(([bg, fg, n], i) =>
  `<button class="sw ${i ? "" : "on"}" title="${n}" aria-label="${n}" data-bg="${bg}" data-fg="${fg}" style="background:${bg};color:${fg}">aa</button>`).join("");
$("swatches").querySelectorAll(".sw").forEach((b) => b.onclick = () => {
  state.video.bg = b.dataset.bg; state.video.fg = b.dataset.fg;
  $("bgColor").value = b.dataset.bg; $("fgColor").value = b.dataset.fg;
  $("swatches").querySelectorAll(".sw").forEach((x) => x.classList.toggle("on", x === b));
  updatePreview();
});
$("bgColor").oninput = (e) => { state.video.bg = e.target.value; clearSwatch(); updatePreview(); };
$("fgColor").oninput = (e) => { state.video.fg = e.target.value; clearSwatch(); updatePreview(); };
const clearSwatch = () => $("swatches").querySelectorAll(".sw").forEach((x) => x.classList.remove("on"));
seg("qualitySeg", (v) => { state.video.quality = +v; updatePreview(); });
seg("fpsSeg", (v) => { state.video.fps = +v; });
seg("modeSeg", (v) => { state.video.mode = v; renderPreview(); });
$("blur").onchange = (e) => { state.video.blur = e.target.checked; updatePreview(); };
function setOffset(ms) {
  state.video.offset = Math.max(-300, Math.min(300, Math.round(ms / 10) * 10));
  $("offset").value = state.video.offset;
  $("offsetVal").textContent = `${state.video.offset > 0 ? "+" : ""}${state.video.offset} ms`;
}
$("offset").oninput = (e) => setOffset(+e.target.value);
// The player (same origin) remembers the sync you dial in with [ and ]; videos start from it.
function syncFromPlayer() {
  try { setOffset(+localStorage.getItem("brat-offset") || 0); } catch {}
}
addEventListener("storage", (e) => e.key === "brat-offset" && syncFromPlayer());
syncFromPlayer();

function dims() {
  const f = FORMATS.find((x) => x.k === state.video.aspect);
  if (f.fixed) return f.fixed;
  const short = state.video.quality;
  const [w, h] = f.w <= f.h ? [short, Math.round(short * f.h / f.w)] : [Math.round(short * f.w / f.h), short];
  return [w - (w % 2), h - (h % 2)];
}
function updatePreview() {
  const [w, h] = dims();
  const box = $("previewBox"), p = $("preview");
  // largest box with the video's aspect ratio that fits the stage
  const bw = Math.max(box.clientWidth, 120), bh = Math.max(box.clientHeight, 200);
  const scale = Math.min(bw / w, bh / h);
  p.style.width = `${Math.floor(w * scale)}px`;
  p.style.height = `${Math.floor(h * scale)}px`;
  p.style.background = state.video.bg;
  p.style.color = state.video.fg;
  $("previewCap").textContent = `${w} × ${h}`;
  fitPreview();
}
addEventListener("resize", () => state.tab === "video" && updatePreview());

// the preview cycles through the song's first lines, word by word
const SAMPLE = [["your", "song", "goes", "here"], ["word", "by", "word"]];
let pv = { line: 0, word: 0, timer: null };
function startPreview() { clearInterval(pv.timer); pv = { line: 0, word: 0, timer: setInterval(stepPreview, 380) }; stepPreview(); }
function previewLines() { return state.song?.preview?.length ? state.song.preview : SAMPLE; }
function stepPreview() {
  const lines = previewLines(), line = lines[pv.line % lines.length];
  pv.word++;
  if (pv.word > line.length + 3) { pv.word = 0; pv.line++; }
  renderPreview();
}
function renderPreview() {
  const lines = previewLines(), line = lines[pv.line % lines.length], shown = Math.min(pv.word, line.length);
  $("previewTxt").innerHTML = line.map((w, i) => {
    const sung = i < shown;
    if (state.video.mode === "reveal" && !sung) return "";
    return `<span style="opacity:${sung ? 1 : .2}">${esc(w)}${i < line.length - 1 ? " " : ""}</span>`;
  }).join("");
  fitPreview();
}
function fitPreview() {
  const p = $("preview"), t = $("previewTxt");
  if (!p.clientWidth) return;
  const lines = previewLines(), words = lines[pv.line % lines.length];
  // size from the full line so the text doesn't jump as words appear
  const probe = t.cloneNode(); probe.style.cssText = `position:absolute;visibility:hidden;width:${p.clientWidth * .86}px`;
  probe.innerHTML = words.map((w) => `<span>${esc(w)} </span>`).join("");
  p.appendChild(probe);
  let lo = 6, hi = 220;
  for (let i = 0; i < 14; i++) {
    const mid = (lo + hi) / 2; probe.style.fontSize = mid + "px";
    const wide = [...probe.children].some((c) => c.offsetWidth > p.clientWidth * .86);
    (probe.scrollHeight > p.clientHeight * .62 || wide) ? (hi = mid) : (lo = mid);
  }
  probe.remove();
  t.style.fontSize = lo + "px";
  t.style.filter = state.video.blur ? `blur(${Math.max(.3, lo * .011)}px)` : "none";
}
startPreview();

$("videoBtn").onclick = async () => {
  if (!state.slug || state.busy) return;
  const [width, height] = dims();
  const body = { slug: state.slug, width, height, fps: state.video.fps, bg: state.video.bg, fg: state.video.fg, mode: state.video.mode, blur: state.video.blur, offset_ms: state.video.offset,
    profile: FORMATS.find((x) => x.k === state.video.aspect).profile || "default" };
  $("videoBtn").disabled = true;
  $("videoProg").classList.remove("hidden");
  $("vfill").style.width = "0%";
  say("Lights, camera, 🎬 action!", "work");
  busy("Video · 0%");
  try {
    const res = await fetch("/api/video", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!res.ok) throw new Error((await res.json()).detail?.[0]?.msg || res.statusText);
    const { job } = await res.json();
    while (true) {
      const j = await (await fetch(`/api/jobs/${job}`)).json();
      const p = j.frac || 0;
      $("vfill").style.width = `${Math.round(p * 100)}%`;
      $("vpct").textContent = `${Math.round(p * 100)}%`;
      busy(`Video · ${Math.round(p * 100)}%`);
      $("vtip").textContent = j.status === "queued" ? "Waiting in line…" : p < .05 ? "Getting ready…" : p < .9 ? "Drawing frames… 🖌️" : "Adding the audio, wrapping up 📦";
      if (j.status === "done") break;
      if (j.status === "error") throw new Error(j.error);
      await new Promise((r) => setTimeout(r, 700));
    }
    state.song = await (await fetch(`/api/songs/${state.slug}`)).json();
    renderVideos();
    say("Video ready! 🍿 Watch it on the right and download if you like it.", "happy"); confetti(); chime([659, 784, 988, 1319]);
    refreshLibrary();
  } catch (e) {
    say("The video didn't work out 😢", "sad"); toast(`Error: ${e.message}`);
  } finally {
    busy(null);
    $("videoBtn").disabled = false;
    $("videoProg").classList.add("hidden");
  }
};
function renderVideos() {
  const v = state.song?.videos || [];
  $("outPane").classList.toggle("hidden", !v.length);
  $("videoView").classList.toggle("has-output", !!v.length);
  if (!v.length) { $("outVideo").removeAttribute("src"); $("outLinks").innerHTML = ""; return; }
  const latest = v[0];
  if (!$("outVideo").src.endsWith(latest)) $("outVideo").src = `/out/${state.slug}/${latest}`;
  $("outLinks").innerHTML = `<a class="btn sky small" href="/out/${state.slug}/${latest}" download>⬇ Download</a>` +
    v.slice(1, 4).map((f) => `<a class="btn ghost small" href="/out/${state.slug}/${f}" download>${esc(f.replace(/^video-|\.(mp4|m4v)$/g, ""))}</a>`).join("");
  if (state.tab === "video") requestAnimationFrame(updatePreview);
}

/* ---------- library ---------- */
function openLib(open) { $("sidebar").classList.toggle("open", open); $("scrim").classList.toggle("open", open); }
$("libBtn").onclick = () => { refreshLibrary(); openLib(true); };
$("scrim").onclick = () => openLib(false);
addEventListener("keydown", (e) => e.key === "Escape" && openLib(false));
$("newBtn").onclick = () => {
  openLib(false);
  if (state.busy) { toast("Something's still running — start a new song once it's done 🙏"); return; }
  state.file = null; state.slug = null; state.song = null; state.phase = "home";
  $("previewAudio").pause(); $("fileInput").value = "";
  $("drop").classList.remove("hidden"); $("fileBox").classList.add("hidden");
  $("lyricsText").value = ""; $("artist").value = ""; $("title").value = "";
  $("startBtn").disabled = true;
  unlockVideo(false); renderVideos(); setTab("prep");
  history.replaceState(null, "", location.pathname);
  refreshLibrary(); startPreview();
  say("New song? Let's do it 🎧", "idle");
};
async function refreshLibrary() {
  const list = await (await fetch("/api/songs")).json();
  $("libList").innerHTML = list.length ? list.map((s) => `
    <div class="lib-item ${s.slug === state.slug ? "on" : ""}" data-slug="${esc(s.slug)}" tabindex="0" role="button">
      <div class="cov">${esc((s.meta.title || s.slug).slice(0, 14))}</div>
      <div style="min-width:0"><div class="t">${esc([s.meta.artist, s.meta.title].filter(Boolean).join(" – ") || s.slug)}</div>
      <div class="s">${s.meta.instrumental ? "instrumental" : `${s.words} words`} · ${s.videos.length} video${s.videos.length === 1 ? "" : "s"}</div></div>
    </div>`).join("") : `<div class="lib-empty">Nothing here yet.</div>`;
  $("libList").querySelectorAll(".lib-item").forEach((el) => {
    const open = async () => {
      if (state.busy) { toast("Something's still running — I'll open it once it's done 🙏"); return; }
      openLib(false);
      await loadSong(el.dataset.slug);
      say("Oh, I remember this one! 😄", "happy");
    };
    el.onclick = open;
    el.onkeydown = (e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), open());
  });
}
refreshLibrary();
const params = new URLSearchParams(location.search), deepLink = params.get("song"), deepTab = params.get("tab");
if (deepLink) loadSong(deepLink)
  .then(() => deepTab === "video" && !$("tabVideo").disabled && setTab("video"))
  .catch(() => toast("Couldn't find that song"));
