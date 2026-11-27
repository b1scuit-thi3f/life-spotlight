const statusNode = document.getElementById("status");
const formNote = document.getElementById("form-note");
const dirty = new Set();

function watchForm(formId) {
  document.getElementById(formId).addEventListener("input", (event) => {
    if (event.target && event.target.id) dirty.add(event.target.id);
  });
  document.getElementById(formId).addEventListener("change", (event) => {
    if (event.target && event.target.id) dirty.add(event.target.id);
  });
}

function setControl(id, value) {
  const el = document.getElementById(id);
  if (!el || dirty.has(id) || document.activeElement === el) return;
  if (el.type === "checkbox") el.checked = Boolean(value);
  else el.value = value ?? "";
}

function clearDirty(ids) {
  ids.forEach((id) => dirty.delete(id));
}

watchForm("immich-form");
watchForm("display-form");
watchForm("system-form");

function bytes(value) {
  if (value == null) return "unknown";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = Number(value);
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function line(label, value) {
  return `<dt>${label}</dt><dd>${value ?? "—"}</dd>`;
}

async function refresh() {
  const response = await fetch("/api/status");
  const data = await response.json();
  const sync = data.sync;
  const cache = data.cache;
  statusNode.innerHTML = [
    line("Network", data.network.connected ? (data.network.ssid || data.network.addresses.join(", ") || "connected") : "offline"),
    line("Addresses", (data.network.addresses || []).join(", ")),
    line("Immich", data.immich.url || "not configured"),
    line("Album", data.immich.albumName || data.immich.albumId || "not selected"),
    line("API key", data.immich.apiKeyConfigured ? "stored" : "missing"),
    line("Last attempt", sync.lastAttemptedAt),
    line("Last success", sync.lastSuccessAt),
    line("Last full sync", sync.lastFullReconciliationAt),
    line("Remote count", sync.lastRemoteCount),
    line("Local assets", `${cache.photos} photos, ${cache.videos} videos`),
    line("Cache", `${bytes(cache.bytes)} of ${bytes(cache.ceilingBytes)}`),
    line("Free space", bytes(cache.freeBytes)),
    line("Last result", sync.lastResultMessage),
    line("Last error", sync.lastErrorClass ? `${sync.lastErrorClass}: ${sync.lastErrorMessage}` : "none"),
    line("Uptime", `${Math.floor(data.uptimeSeconds / 60)} min`),
    line("Version", data.version),
  ].join("");
  setControl("immich_url", data.immich.url || "");
  setControl("album_id", data.immich.albumId || "");
  setControl("presentation_mode", data.display.presentationMode);
  setControl("photo_duration_seconds", data.display.photoDurationSeconds);
  setControl("transition", data.display.transition);
  setControl("show_overlay", data.display.showOverlay);
  setControl("videos_enabled", data.display.videosEnabled);
  setControl("new_window_hours", data.display.newWindowHours);
  const system = data.system || {};
  setControl("sync_incremental_minutes", system.syncIncrementalMinutes);
  setControl("sync_reconcile_hours", system.syncReconcileHours);
  setControl("cache_ceiling_gb", Math.round((system.cacheCeilingBytes || 0) / 1e9));
  setControl("reserved_gb", ((system.reservedBytes || 0) / 1e9).toFixed(1));
  setControl("http_timeout_seconds", system.httpTimeoutSeconds);
  setControl("download_timeout_seconds", system.downloadTimeoutSeconds);
}

async function post(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || payload.message || response.statusText);
  }
  return payload;
}

document.getElementById("immich-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  formNote.textContent = "Saving…";
  try {
    await post("/api/admin/immich", {
      immichUrl: document.getElementById("immich_url").value,
      albumId: document.getElementById("album_id").value,
      apiKey: document.getElementById("api_key").value || null,
    });
    document.getElementById("api_key").value = "";
    clearDirty(["immich_url", "album_id", "api_key"]);
    formNote.textContent = "Immich settings saved. The key is not shown again.";
    formNote.className = "note ok";
    refresh();
  } catch (error) {
    formNote.textContent = error.message;
    formNote.className = "note bad";
  }
});

document.getElementById("display-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await post("/api/admin/display", {
      presentationMode: document.getElementById("presentation_mode").value,
      photoDurationSeconds: Number(document.getElementById("photo_duration_seconds").value),
      transition: document.getElementById("transition").value,
      showOverlay: document.getElementById("show_overlay").checked,
      videosEnabled: document.getElementById("videos_enabled").checked,
      newWindowHours: Number(document.getElementById("new_window_hours").value),
    });
    clearDirty([
      "presentation_mode",
      "photo_duration_seconds",
      "transition",
      "show_overlay",
      "videos_enabled",
      "new_window_hours",
    ]);
    formNote.textContent = "Display settings saved.";
    formNote.className = "note ok";
  } catch (error) {
    formNote.textContent = error.message;
    formNote.className = "note bad";
  }
});

document.getElementById("system-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await post("/api/admin/system", {
      syncIncrementalMinutes: Number(document.getElementById("sync_incremental_minutes").value),
      syncReconcileHours: Number(document.getElementById("sync_reconcile_hours").value),
      cacheCeilingBytes: Math.round(Number(document.getElementById("cache_ceiling_gb").value) * 1e9),
      reservedBytes: Math.round(Number(document.getElementById("reserved_gb").value) * 1e9),
      httpTimeoutSeconds: Number(document.getElementById("http_timeout_seconds").value),
      downloadTimeoutSeconds: Number(document.getElementById("download_timeout_seconds").value),
    });
    clearDirty([
      "sync_incremental_minutes",
      "sync_reconcile_hours",
      "cache_ceiling_gb",
      "reserved_gb",
      "http_timeout_seconds",
      "download_timeout_seconds",
    ]);
    formNote.textContent = "Sync and storage settings saved.";
    formNote.className = "note ok";
    refresh();
  } catch (error) {
    formNote.textContent = error.message;
    formNote.className = "note bad";
  }
});

document.getElementById("test").addEventListener("click", async () => {
  formNote.textContent = "Contacting Immich…";
  const response = await fetch("/api/admin/immich/test", { method: "POST" });
  const payload = await response.json();
  const albums = document.getElementById("albums");
  if (!payload.ok) {
    formNote.textContent = payload.message || "connection failed";
    formNote.className = "note bad";
    albums.textContent = "";
    return;
  }
  formNote.textContent = "Connected.";
  formNote.className = "note ok";
  albums.innerHTML = (payload.albums || []).map((album) => {
    const name = album.name || "Untitled";
    return `<button type="button" class="secondary pick" data-id="${album.id}">${name} (${album.count ?? "?"})</button>`;
  }).join(" ");
  albums.querySelectorAll(".pick").forEach((button) => {
    button.addEventListener("click", () => {
      document.getElementById("album_id").value = button.dataset.id;
    });
  });
});

async function sync(kind) {
  formNote.textContent = `Running ${kind} sync…`;
  try {
    const payload = await post(`/api/admin/sync?kind=${kind}`, {});
    formNote.textContent = payload.message || (payload.ok ? "sync finished" : "sync failed");
    formNote.className = payload.ok ? "note ok" : "note bad";
  } catch (error) {
    formNote.textContent = error.message;
    formNote.className = "note bad";
  }
  refresh();
}

document.getElementById("sync-now").addEventListener("click", () => sync("incremental"));
document.getElementById("reconcile").addEventListener("click", () => sync("reconciliation"));

document.getElementById("wifi-scan").addEventListener("click", async () => {
  const response = await fetch("/api/admin/wifi");
  const payload = await response.json();
  const list = document.getElementById("wifi-list");
  if (!payload.nmcli) {
    list.textContent = "NetworkManager is not available here. Wi-Fi setup runs on the Pi.";
    return;
  }
  list.innerHTML = (payload.networks || []).map(
    (ssid) => `<button type="button" class="secondary ssid">${ssid}</button>`,
  ).join(" ");
  list.querySelectorAll(".ssid").forEach((button) => {
    button.addEventListener("click", () => {
      document.getElementById("ssid").value = button.textContent;
    });
  });
});

document.getElementById("wifi-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const payload = await post("/api/admin/wifi", {
      ssid: document.getElementById("ssid").value,
      password: document.getElementById("wifi_password").value,
    });
    document.getElementById("wifi_password").value = "";
    formNote.textContent = payload.message || (payload.ok ? "connected" : "not connected");
    formNote.className = payload.ok ? "note ok" : "note bad";
  } catch (error) {
    formNote.textContent = error.message;
    formNote.className = "note bad";
  }
});

refresh();
setInterval(refresh, 15000);
