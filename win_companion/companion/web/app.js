import { classifyGesture, clamp01, volumeDelta } from "./gestures.mjs";

const POLL_MS = 750;
const ART_WIDTH = 640;
const VOLUME_STEP = 0.05;

const stage = document.getElementById("stage");
const artFrame = document.getElementById("art-frame");
const art = document.getElementById("art");
const artPlaceholder = document.getElementById("art-placeholder");
const titleEl = document.getElementById("title");
const artistEl = document.getElementById("artist");
const albumEl = document.getElementById("album");
const sourceEl = document.getElementById("source");
const elapsedEl = document.getElementById("elapsed");
const durationEl = document.getElementById("duration");
const progressBlock = document.getElementById("progress-block");
const progressFill = document.getElementById("progress-fill");
const volumeLabel = document.getElementById("volume-label");
const volumeFill = document.getElementById("volume-fill");
const connectionDot = document.getElementById("connection-dot");
const connectionLabel = document.getElementById("connection-label");
const osd = document.getElementById("osd");

let currentState = null;
let stateReceivedAt = performance.now();
let pollInFlight = false;
let connected = false;
let pollTimer = 0;
let osdTimer = 0;
let artRequested = null;
let artFailed = null;
let gesture = null;
let actionChain = Promise.resolve();
const activePointers = new Set();

const STATUS_LABELS = {
  playing: "Playing",
  paused: "Paused",
  stopped: "Stopped",
  changing: "Changing",
};

const ERROR_LABELS = {
  no_session: "No media session",
  not_supported: "Not supported",
  volume_unavailable: "Volume unavailable",
  timeout: "Controller timed out",
  busy: "Controller busy",
  unavailable: "Controller unavailable",
  internal: "Something went wrong",
};

const APP_NAMES = [
  [/spotify/i, "Spotify"],
  [/msedge/i, "Edge"],
  [/chrome/i, "Chrome"],
  [/firefox/i, "Firefox"],
  [/wmplayer|windowsmedia/i, "Media Player"],
  [/foobar/i, "foobar2000"],
];

function setText(element, text) {
  element.textContent = text || "";
}

function setOptionalText(element, text) {
  const value = text || "";
  element.textContent = value;
  element.hidden = !value;
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 5000) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    window.clearTimeout(timer);
  }
}

function prettyApp(appId) {
  if (!appId) return "";
  for (const [pattern, name] of APP_NAMES) {
    if (pattern.test(appId)) return name;
  }
  let name = String(appId).split("!")[0].split("\\").pop();
  name = name.replace(/\.exe$/i, "").replace(/[._]+/g, " ").trim();
  return name.length > 28 ? `${name.slice(0, 27)}…` : name;
}

function statusLabel(status) {
  return STATUS_LABELS[status] || "";
}

function formatTime(milliseconds) {
  const total = Math.max(0, Math.floor(Number(milliseconds) / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function setConnected(value) {
  const next = Boolean(value);
  if (next === connected) return;
  connected = next;
  connectionDot.classList.toggle("connected", next);
  connectionDot.classList.toggle("disconnected", !next);
  connectionLabel.textContent = next ? "Connected" : "Offline";
}

function showOsd(text, isError = false) {
  if (!text) return;
  osd.textContent = text;
  osd.classList.toggle("error", Boolean(isError));
  osd.classList.add("show");
  osd.setAttribute("aria-hidden", "false");
  window.clearTimeout(osdTimer);
  osdTimer = window.setTimeout(
    () => {
      osd.classList.remove("show");
      osd.setAttribute("aria-hidden", "true");
    },
    isError ? 1900 : 900,
  );
}

function renderArt(artId) {
  if (!artId) {
    artRequested = null;
    art.hidden = true;
    artPlaceholder.hidden = false;
    return;
  }

  if (artId === artFailed) {
    art.hidden = true;
    artPlaceholder.hidden = false;
    return;
  }

  if (artId !== artRequested) {
    artRequested = artId;
    art.hidden = true;
    artPlaceholder.hidden = false;
    art.dataset.artId = artId;
    art.src = `/api/art/${encodeURIComponent(artId)}?w=${ART_WIDTH}`;
  }
}

art.addEventListener("load", () => {
  if (art.dataset.artId !== artRequested) return;
  art.hidden = false;
  artPlaceholder.hidden = true;
});

art.addEventListener("error", () => {
  if (art.dataset.artId !== artRequested) return;
  artFailed = artRequested;
  art.hidden = true;
  artPlaceholder.hidden = false;
});

function renderVolume(volume) {
  if (!volume || !volume.available || typeof volume.level !== "number") {
    volumeLabel.textContent = "Unavailable";
    volumeFill.style.width = "0%";
    return;
  }
  const percent = Math.round(clamp01(volume.level) * 100);
  volumeLabel.textContent = volume.muted ? "Muted" : `${percent}%`;
  volumeFill.style.width = `${percent}%`;
}

function render(state) {
  const media = state.media || {};
  const volume = state.volume || {};
  const health = state.health || {};
  const active = Boolean(media.active);
  const unavailable = health.media === "error";

  if (active) {
    setText(titleEl, media.title || "Unknown title");
    setOptionalText(artistEl, media.artist);
    setOptionalText(albumEl, media.album);
    const pieces = [prettyApp(media.app_id), statusLabel(media.playback_status)].filter(Boolean);
    setText(sourceEl, pieces.join(" · "));
  } else {
    setText(titleEl, unavailable ? "Media unavailable" : "Nothing playing");
    setOptionalText(artistEl, "");
    setOptionalText(albumEl, "");
    setText(
      sourceEl,
      unavailable ? "Cannot read the media session" : "No active media session",
    );
  }

  progressBlock.hidden = !active;
  renderArt(active ? media.art_id : null);
  renderVolume(volume);
  updateProgress();
}

function updateProgress() {
  const media = currentState ? currentState.media : null;
  if (!media || !media.active) {
    progressFill.style.width = "0%";
    elapsedEl.textContent = "0:00";
    durationEl.textContent = "--:--";
    return;
  }

  const duration = Math.max(0, Number(media.duration_ms) || 0);
  let position = Math.max(0, Number(media.position_ms) || 0);
  if (media.playback_status === "playing") {
    position += performance.now() - stateReceivedAt;
  }
  if (duration > 0) {
    position = Math.min(position, duration);
  }

  const percent = duration > 0 ? clamp01(position / duration) * 100 : 0;
  progressFill.style.width = `${percent}%`;
  elapsedEl.textContent = formatTime(position);
  durationEl.textContent = duration > 0 ? formatTime(duration) : "--:--";
}

function applyState(state) {
  if (!state || typeof state !== "object") return;
  currentState = state;
  stateReceivedAt = performance.now();
  render(state);
}

async function fetchState() {
  if (pollInFlight) return;
  pollInFlight = true;
  try {
    const response = await fetchWithTimeout("/api/state", { cache: "no-store" }, 3500);
    if (!response.ok) throw new Error(`state request failed: ${response.status}`);
    const state = await response.json();
    applyState(state);
    setConnected(true);
  } catch (error) {
    setConnected(false);
  } finally {
    pollInFlight = false;
  }
}

function errorLabel(code) {
  return ERROR_LABELS[code] || "Action failed";
}

async function sendAction(payload, options = {}) {
  try {
    const response = await fetchWithTimeout("/api/action", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }, 5000);
    const body = await response.json().catch(() => ({}));
    if (body && body.state) applyState(body.state);
    setConnected(true);
    if (!response.ok || body.ok === false) {
      showOsd(errorLabel(body.error), true);
      return false;
    }
    if (options.volume) {
      const volume = body.state ? body.state.volume : null;
      if (volume && volume.available && typeof volume.level === "number") {
        const percent = Math.round(clamp01(volume.level) * 100);
        showOsd(volume.muted ? "Muted" : `Volume ${percent}%`);
      }
    }
    return true;
  } catch (error) {
    setConnected(false);
    showOsd("Connection lost", true);
    return false;
  }
}

function queueAction(payload, options = {}) {
  actionChain = actionChain.then(() => sendAction(payload, options));
  return actionChain;
}

function handleGesture(result) {
  switch (result.type) {
    case "tap":
      showOsd("Play/Pause");
      void queueAction({ action: "play_pause" });
      break;
    case "swipe_left":
      showOsd("Next");
      void queueAction({ action: "next" });
      break;
    case "swipe_right":
      showOsd("Previous");
      void queueAction({ action: "previous" });
      break;
    case "swipe_up":
      void queueAction(
        { action: "volume_step", delta: volumeDelta("up", VOLUME_STEP) },
        { volume: true },
      );
      break;
    case "swipe_down":
      void queueAction(
        { action: "volume_step", delta: volumeDelta("down", VOLUME_STEP) },
        { volume: true },
      );
      break;
    default:
      break;
  }
}

function resetArtTransform() {
  artFrame.style.transform = "";
}

function onPointerDown(event) {
  if (event.pointerType === "mouse" && event.button !== 0) return;
  activePointers.add(event.pointerId);
  if (activePointers.size > 1) {
    gesture = null;
    resetArtTransform();
    return;
  }
  gesture = {
    id: event.pointerId,
    x: event.clientX,
    y: event.clientY,
    t: performance.now(),
  };
  try {
    stage.setPointerCapture(event.pointerId);
  } catch (error) {
    // Pointer capture is an enhancement; gestures still work without it.
  }
}

function onPointerMove(event) {
  if (!gesture || event.pointerId !== gesture.id) return;
  const dx = event.clientX - gesture.x;
  const dy = event.clientY - gesture.y;
  const limit = 16;
  const offsetX = Math.max(-limit, Math.min(limit, dx * 0.18));
  const offsetY = Math.max(-limit, Math.min(limit, dy * 0.18));
  artFrame.style.transform = `translate(${offsetX}px, ${offsetY}px)`;
}

function onPointerUp(event) {
  activePointers.delete(event.pointerId);
  if (!gesture || event.pointerId !== gesture.id) {
    resetArtTransform();
    return;
  }
  const start = gesture;
  gesture = null;
  resetArtTransform();
  const end = { x: event.clientX, y: event.clientY, t: performance.now() };
  handleGesture(classifyGesture([{ x: start.x, y: start.y, t: start.t }, end]));
}

function onPointerCancel(event) {
  activePointers.delete(event.pointerId);
  if (gesture && event.pointerId === gesture.id) {
    gesture = null;
  }
  resetArtTransform();
}

function start() {
  fetchState();
  pollTimer = window.setInterval(() => {
    if (!document.hidden) fetchState();
  }, POLL_MS);
  window.setInterval(updateProgress, 250);

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) fetchState();
  });
  window.addEventListener("focus", fetchState);

  stage.addEventListener("pointerdown", onPointerDown);
  stage.addEventListener("pointermove", onPointerMove);
  stage.addEventListener("pointerup", onPointerUp);
  stage.addEventListener("pointercancel", onPointerCancel);
  stage.addEventListener("contextmenu", (event) => event.preventDefault());
  stage.addEventListener("dragstart", (event) => event.preventDefault());
  window.addEventListener("blur", resetArtTransform);
}

start();
