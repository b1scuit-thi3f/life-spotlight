const statusNode = document.getElementById("status");
const formNote = document.getElementById("form-note");

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
    line("Album", data.immich.album_name || data.immich.album_id || "not selected"),
    line("API key", data.immich.api_key_configured ? "stored" : "missing"),
    line("Last attempt", sync.last_attempted_at),
    line("Last success", sync.last_success_at),
    line("Last full sync", sync.last_full_reconciliation_at),
    line("Remote count", sync.last_remote_count),
    line("Local assets", `${cache.photos} photos, ${cache.videos} videos`),
    line("Cache", `${bytes(cache.bytes)} of ${bytes(cache.ceiling_bytes)}`),
    line("Free space", bytes(cache.free_bytes)),
    line("Last result", sync.last_result_message),
    line("Last error", sync.last_error_class ? `${sync.last_error_class}: ${sync.last_error_message}` : "none"),
    line("Uptime", `${Math.floor(data.uptime_seconds / 60)} min`),
    line("Version", data.version),
  ].join("");
  document.getElementById("immich_url").value = data.immich.url || "";
  document.getElementById("album_id").value = data.immich.album_id || "";
  document.getElementById("presentation_mode").value = data.display.presentation_mode;
  document.getElementById("photo_duration_seconds").value = data.display.photo_duration_seconds;
  document.getElementById("transition").value = data.display.transition;
  document.getElementById("show_overlay").checked = data.display.show_overlay;
  document.getElementById("videos_enabled").checked = data.display.videos_enabled;
  document.getElementById("new_window_hours").value = data.display.new_window_hours;
  const system = data.system || {};
  document.getElementById("sync_incremental_minutes").value = system.sync_incremental_minutes;
  document.getElementById("sync_reconcile_hours").value = system.sync_reconcile_hours;
  document.getElementById("cache_ceiling_gb").value = Math.round((system.cache_ceiling_bytes || 0) / 1e9);
  document.getElementById("reserved_gb").value = ((system.reserved_bytes || 0) / 1e9).toFixed(1);
  document.getElementById("http_timeout_seconds").value = system.http_timeout_seconds;
  document.getElementById("download_timeout_seconds").value = system.download_timeout_seconds;
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
      immich_url: document.getElementById("immich_url").value,
      album_id: document.getElementById("album_id").value,
      api_key: document.getElementById("api_key").value || null,
    });
    document.getElementById("api_key").value = "";
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
      presentation_mode: document.getElementById("presentation_mode").value,
      photo_duration_seconds: Number(document.getElementById("photo_duration_seconds").value),
      transition: document.getElementById("transition").value,
      show_overlay: document.getElementById("show_overlay").checked,
      videos_enabled: document.getElementById("videos_enabled").checked,
      new_window_hours: Number(document.getElementById("new_window_hours").value),
    });
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
      sync_incremental_minutes: Number(document.getElementById("sync_incremental_minutes").value),
      sync_reconcile_hours: Number(document.getElementById("sync_reconcile_hours").value),
      cache_ceiling_bytes: Math.round(Number(document.getElementById("cache_ceiling_gb").value) * 1e9),
      reserved_bytes: Math.round(Number(document.getElementById("reserved_gb").value) * 1e9),
      http_timeout_seconds: Number(document.getElementById("http_timeout_seconds").value),
      download_timeout_seconds: Number(document.getElementById("download_timeout_seconds").value),
    });
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
