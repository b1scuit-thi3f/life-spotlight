const stage = document.querySelector(".stage");
const empty = document.querySelector(".empty");
const overlay = document.querySelector(".overlay");
const controls = document.querySelector(".controls");
const transport = document.querySelector(".transport");
const settings = document.querySelector(".settings");
const recentIds = [];
let current = null;
let timer = null;
let hideControlsTimer = null;
let audioEnabled = false;
let startedAt = 0;
let display = {
  photoDurationSeconds: 12,
  showOverlay: true,
  transition: "fade",
  videosEnabled: true,
};

async function boot() {
  bindControls();
  await advance(false);
}

function bindControls() {
  let gesture = null;
  stage.addEventListener("pointerdown", (event) => {
    if (!event.isPrimary) return;
    if (event.pointerType === "mouse" && event.button !== 0) return;
    gesture = {
      id: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      target: event.target,
    };
  });
  stage.addEventListener("pointerup", (event) => {
    if (!gesture || event.pointerId !== gesture.id) return;
    const start = gesture;
    gesture = null;
    const moved = Math.hypot(event.clientX - start.x, event.clientY - start.y);
    if (moved > 28) return;
    handleTap(start.target, start.x);
  });
  stage.addEventListener("pointercancel", () => {
    gesture = null;
  });
  // A finger tap also synthesises a click. The pointer handler already acted.
  stage.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "ArrowRight") advance(true);
    if (event.key === " ") {
      if (current && current.mediaType === "video") {
        event.preventDefault();
        togglePlay();
      } else {
        advance(true);
      }
    }
    if (event.key === "a") toggleAudio();
  });
}

function handleTap(target, x) {
  const link = target.closest("a[href]");
  const settingsLink = link && link.classList.contains("settings");
  if (link && (!settingsLink || controls.classList.contains("visible"))) {
    window.location.assign(link.href);
    return;
  }
  const button = target.closest("button");
  if (button && button.id === "next") {
    advance(true);
    return;
  }
  if (button && transport.contains(button)) {
    revealControls();
    if (button.id === "audio") toggleAudio();
    else if (button.id === "play") togglePlay();
    else if (button.id === "restart") restartVideo();
    return;
  }
  const bounds = stage.getBoundingClientRect();
  const onRight = x > bounds.left + bounds.width * 0.75;
  if (onRight) {
    advance(true);
    return;
  }
  revealControls();
}

function revealControls() {
  controls.classList.add("visible");
  settings.classList.add("visible");
  if (!transport.hidden) transport.classList.add("visible");
  clearTimeout(hideControlsTimer);
  hideControlsTimer = setTimeout(() => {
    controls.classList.remove("visible");
    settings.classList.remove("visible");
    transport.classList.remove("visible");
  }, 7000);
}

async function advance(reportPrevious) {
  clearTimeout(timer);
  if (reportPrevious && current) {
    const elapsed = (Date.now() - startedAt) / 1000;
    const completed = current.mediaType === "photo" || elapsed > 1;
    navigator.sendBeacon(
      "/api/presentation/played",
      new Blob(
        [JSON.stringify({
          mediaId: current.id,
          durationSeconds: Math.max(0, elapsed),
          completed,
          audioEnabled: audioEnabled,
        })],
        { type: "application/json" },
      ),
    );
  }
  const exclude = recentIds.slice(-8).join(",");
  let payload;
  try {
    const response = await fetch(`/api/presentation/next?exclude=${encodeURIComponent(exclude)}`);
    payload = await response.json();
    if (!response.ok) {
      showEmpty("The frame hit an error.", "Retrying shortly.");
      timer = setTimeout(() => advance(false), 5000);
      return;
    }
  } catch (error) {
    showEmpty("The frame is still starting.", "Retrying shortly.");
    timer = setTimeout(() => advance(false), 5000);
    return;
  }
  display = payload.display || display;
  if (!payload.media) {
    showEmpty("Nothing to show yet.", "Add photos to the Immich album, or open admin to sync.");
    timer = setTimeout(() => advance(false), 15000);
    return;
  }
  if (current && payload.media.id === current.id && recentIds.length > 1) {
    const retry = recentIds.filter((id) => id !== current.id).slice(-8).join(",");
    const again = await fetch(`/api/presentation/next?exclude=${encodeURIComponent(retry)}`);
    const second = await again.json();
    if (second.media && second.media.id !== current.id) {
      payload.media = second.media;
    }
  }
  empty.style.display = "none";
  await showMedia(payload.media);
}

function showEmpty(title, detail) {
  empty.style.display = "flex";
  empty.querySelector("h1").textContent = title;
  empty.querySelector("p").textContent = detail;
  document.querySelectorAll(".slide").forEach((node) => node.remove());
  overlay.classList.remove("visible");
  current = null;
  updateTransport();
}

const FADE_MS = 1400;
let showGeneration = 0;

function currentVideo() {
  return stage.querySelector(".slide.active video");
}

function updateTransport() {
  const video = currentVideo();
  const showingVideo = Boolean(current && current.mediaType === "video" && video);
  transport.hidden = !showingVideo;
  if (!showingVideo) transport.classList.remove("visible");
  const audio = document.getElementById("audio");
  audio.classList.toggle("sound-on", audioEnabled);
  audio.setAttribute("aria-label", audioEnabled ? "Mute" : "Turn sound on");
  const play = document.getElementById("play");
  const playing = Boolean(video && !video.paused && !video.ended);
  play.classList.toggle("is-playing", playing);
  play.setAttribute("aria-label", playing ? "Pause" : "Play");
}

async function whenReady(element) {
  try {
    if (element.tagName === "IMG") {
      if (element.decode) await element.decode();
      else {
        await new Promise((resolve, reject) => {
          element.addEventListener("load", resolve, { once: true });
          element.addEventListener("error", reject, { once: true });
        });
      }
      return;
    }
    if (element.tagName === "VIDEO" && element.readyState < 2) {
      await new Promise((resolve, reject) => {
        element.addEventListener("canplay", resolve, { once: true });
        element.addEventListener("error", reject, { once: true });
      });
    }
  } catch {
    // A failed load should not freeze the frame on the previous item.
  }
}

async function showMedia(media) {
  audioEnabled = false;
  const generation = ++showGeneration;
  const slide = document.createElement("div");
  slide.className = "slide";
  let element;
  if (media.mediaType === "video") {
    element = document.createElement("video");
    element.src = media.url;
    element.autoplay = true;
    element.loop = false;
    element.preload = "auto";
    element.muted = true;
    element.playsInline = true;
    element.controls = false;
    element.addEventListener("play", updateTransport);
    element.addEventListener("pause", updateTransport);
    element.addEventListener("ended", () => advance(true));
    element.addEventListener("error", () => advance(true));
  } else {
    element = document.createElement("img");
    element.alt = "";
    element.src = media.url;
  }
  slide.appendChild(element);
  const outgoing = [...stage.querySelectorAll(".slide")];
  stage.appendChild(slide);
  await whenReady(element);
  if (generation !== showGeneration) {
    slide.remove();
    return;
  }
  const fade = display.transition !== "none";
  if (fade) {
    // Keep the current photo in place and dissolve the next one over it.
    await new Promise((resolve) => requestAnimationFrame(resolve));
    await new Promise((resolve) => requestAnimationFrame(resolve));
    slide.classList.add("active");
    if (outgoing.length) {
      setTimeout(() => {
        for (const node of outgoing) node.remove();
      }, FADE_MS + 80);
    }
  } else {
    for (const node of outgoing) node.remove();
    slide.classList.add("active");
  }
  current = media;
  startedAt = Date.now();
  recentIds.push(media.id);
  if (recentIds.length > 24) recentIds.shift();
  renderOverlay(media);
  updateTransport();
  if (media.mediaType === "photo") {
    timer = setTimeout(() => advance(true), (display.photoDurationSeconds || 12) * 1000);
  }
}

function paintOverlay(media) {
  overlay.querySelector(".added").textContent = media.isNew ? media.addedLabel : "";
  overlay.querySelector(".captured").textContent = media.capturedLabel || "";
  if (display.showOverlay) overlay.classList.add("visible");
  else overlay.classList.remove("visible");
}

function renderOverlay(media) {
  if (!display.showOverlay) {
    overlay.classList.remove("visible");
    return;
  }
  if (display.transition === "none" || !overlay.classList.contains("visible")) {
    paintOverlay(media);
    return;
  }
  overlay.classList.remove("visible");
  setTimeout(() => paintOverlay(media), 320);
}

function toggleAudio() {
  audioEnabled = !audioEnabled;
  const video = currentVideo();
  if (video) video.muted = !audioEnabled;
  updateTransport();
  revealControls();
}

function togglePlay() {
  const video = currentVideo();
  if (!video) return;
  if (video.paused || video.ended) video.play().catch(() => {});
  else video.pause();
  updateTransport();
  revealControls();
}

function restartVideo() {
  const video = currentVideo();
  if (!video) return;
  video.currentTime = 0;
  video.play().catch(() => {});
  updateTransport();
  revealControls();
}

boot();
