const stage = document.querySelector(".stage");
const empty = document.querySelector(".empty");
const overlay = document.querySelector(".overlay");
const controls = document.querySelector(".controls");
const recentIds = [];
let current = null;
let timer = null;
let hideControlsTimer = null;
let audioEnabled = false;
let startedAt = 0;
let display = {
  photo_duration_seconds: 12,
  show_overlay: true,
  transition: "fade",
  videos_enabled: true,
};

async function boot() {
  bindControls();
  await advance(false);
}

function bindControls() {
  document.getElementById("next").addEventListener("click", (event) => {
    event.stopPropagation();
    advance(true);
  });
  document.getElementById("audio").addEventListener("click", (event) => {
    event.stopPropagation();
    toggleAudio();
  });
  stage.addEventListener("pointerdown", () => revealControls());
  document.addEventListener("keydown", (event) => {
    if (event.key === "ArrowRight" || event.key === " ") advance(true);
    if (event.key === "a") toggleAudio();
  });
}

function revealControls() {
  controls.classList.add("visible");
  clearTimeout(hideControlsTimer);
  hideControlsTimer = setTimeout(() => controls.classList.remove("visible"), 4000);
}

async function advance(reportPrevious) {
  clearTimeout(timer);
  if (reportPrevious && current) {
    const elapsed = (Date.now() - startedAt) / 1000;
    const completed = current.media_type === "photo" || elapsed > 1;
    navigator.sendBeacon(
      "/api/presentation/played",
      new Blob(
        [JSON.stringify({
          media_id: current.id,
          duration_seconds: Math.max(0, elapsed),
          completed,
          audio_enabled: audioEnabled,
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
}

async function showMedia(media) {
  const slide = document.createElement("div");
  slide.className = "slide";
  let element;
  if (media.media_type === "video") {
    element = document.createElement("video");
    element.src = media.url;
    element.autoplay = true;
    element.muted = !audioEnabled;
    element.playsInline = true;
    element.controls = false;
    element.addEventListener("ended", () => advance(true));
    element.addEventListener("error", () => advance(true));
  } else {
    element = document.createElement("img");
    element.alt = "";
    element.src = media.url;
  }
  slide.appendChild(element);
  stage.appendChild(slide);
  const previous = stage.querySelector(".slide.active");
  requestAnimationFrame(() => slide.classList.add("active"));
  if (previous && display.transition === "fade") {
    previous.classList.remove("active");
    setTimeout(() => previous.remove(), 800);
  } else if (previous) {
    previous.remove();
  }
  current = media;
  startedAt = Date.now();
  recentIds.push(media.id);
  if (recentIds.length > 24) recentIds.shift();
  renderOverlay(media);
  const audioButton = document.getElementById("audio");
  audioButton.hidden = media.media_type !== "video";
  audioButton.textContent = audioEnabled ? "Mute" : "Sound";
  if (media.media_type === "photo") {
    timer = setTimeout(() => advance(true), (display.photo_duration_seconds || 12) * 1000);
  }
}

function renderOverlay(media) {
  if (!display.show_overlay) {
    overlay.classList.remove("visible");
    return;
  }
  overlay.querySelector(".added").textContent = media.is_new ? media.added_label : "";
  overlay.querySelector(".captured").textContent = media.captured_label || "";
  overlay.classList.add("visible");
}

function toggleAudio() {
  audioEnabled = !audioEnabled;
  const video = stage.querySelector("video");
  if (video) {
    video.muted = !audioEnabled;
    if (audioEnabled) video.play().catch(() => {});
  }
  document.getElementById("audio").textContent = audioEnabled ? "Mute" : "Sound";
  revealControls();
}

boot();
