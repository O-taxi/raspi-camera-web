const captureButton = document.querySelector("#capture-button");
const captureLabel = document.querySelector("#capture-label");
const statusMessage = document.querySelector("#status");
const gallery = document.querySelector("#gallery");
const emptyMessage = document.querySelector("#empty-message");
const pagination = document.querySelector("#pagination");
const previousPageButton = document.querySelector("#previous-page");
const nextPageButton = document.querySelector("#next-page");
const pageInfo = document.querySelector("#page-info");
const photoDialog = document.querySelector("#photo-dialog");
const dialogImage = document.querySelector("#dialog-image");
const dialogTime = document.querySelector("#dialog-time");
const closeDialogButton = document.querySelector("#close-dialog");
const deletePhotoButton = document.querySelector("#delete-photo");
const videoList = document.querySelector("#video-list");
const emptyVideoMessage = document.querySelector("#empty-video-message");
const videoTableWrap = document.querySelector(".video-table-wrap");
const videoPagination = document.querySelector("#video-pagination");
const previousVideoPageButton = document.querySelector("#previous-video-page");
const nextVideoPageButton = document.querySelector("#next-video-page");
const videoPageInfo = document.querySelector("#video-page-info");
const motionToggle = document.querySelector("#motion-toggle");
const cameraNotice = document.querySelector("#camera-notice");
const motionDiagnostics = document.querySelector("#motion-diagnostics");
const motionAnalysisSource = document.querySelector("#motion-analysis-source");
const motionAnalysisStatus = document.querySelector("#motion-analysis-status");
const motionOverlay = document.querySelector("#motion-overlay");

const photosPerPage = 8;
const videosPerPage = 10;
let photos = [];
let videos = [];
let motionStatus = null;
let motionStatusRequestToken = 0;
let motionStatusRequestInProgress = false;
let motionUpdateInProgress = false;
let currentPage = 1;
let currentVideoPage = 1;
let selectedPhoto = null;
let statusTimer = null;
let cooldownTimer = null;
let cooldownEndsAt = 0;

function formatDate(value) {
  return new Intl.DateTimeFormat("ja-JP", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(value));
}

function formatDuration(seconds) {
  if (!Number.isInteger(seconds) || seconds <= 0) {
    return "—";
  }
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return minutes > 0
    ? `${minutes}:${String(remainingSeconds).padStart(2, "0")}`
    : `${remainingSeconds}秒`;
}

function setStatus(message, isError = false) {
  window.clearTimeout(statusTimer);
  statusMessage.textContent = message;
  statusMessage.classList.toggle("error", isError);
  statusMessage.hidden = false;
  statusTimer = window.setTimeout(() => {
    statusMessage.hidden = true;
  }, isError ? 5000 : 3000);
}

function startCaptureCooldown(seconds) {
  window.clearInterval(cooldownTimer);
  cooldownEndsAt = Date.now() + seconds * 1000;
  captureButton.disabled = true;

  function updateCooldown() {
    const remainingSeconds = Math.max(0, Math.ceil((cooldownEndsAt - Date.now()) / 1000));
    if (remainingSeconds === 0) {
      window.clearInterval(cooldownTimer);
      cooldownTimer = null;
      cooldownEndsAt = 0;
      captureLabel.textContent = "撮影";
      captureButton.disabled = false;
      return;
    }
    captureLabel.textContent = `撮影 (${remainingSeconds})`;
  }

  updateCooldown();
  cooldownTimer = window.setInterval(updateCooldown, 250);
}

function openPhoto(photo) {
  selectedPhoto = photo;
  dialogImage.src = `${photo.url}?v=${encodeURIComponent(photo.id)}`;
  dialogTime.textContent = formatDate(photo.captured_at);
  photoDialog.showModal();
}

function renderGallery() {
  gallery.replaceChildren();
  emptyMessage.hidden = photos.length > 0;
  const totalPages = Math.max(1, Math.ceil(photos.length / photosPerPage));
  currentPage = Math.min(currentPage, totalPages);
  const firstPhoto = (currentPage - 1) * photosPerPage;
  const visiblePhotos = photos.slice(firstPhoto, firstPhoto + photosPerPage);

  for (const photo of visiblePhotos) {
    const card = document.createElement("article");
    const selectButton = document.createElement("button");
    const image = document.createElement("img");
    const caption = document.createElement("p");

    card.className = "photo-card";
    selectButton.className = "photo-select-button";
    selectButton.type = "button";
    selectButton.setAttribute("aria-label", `${formatDate(photo.captured_at)}の写真を拡大`);
    selectButton.addEventListener("click", () => openPhoto(photo));
    image.src = `${photo.url}?v=${encodeURIComponent(photo.id)}`;
    image.alt = `${formatDate(photo.captured_at)}に撮影したカメラ画像`;
    image.loading = "lazy";
    caption.textContent = formatDate(photo.captured_at);
    selectButton.append(image, caption);
    card.append(selectButton);
    gallery.append(card);
  }

  pagination.hidden = photos.length <= photosPerPage;
  pageInfo.textContent = `${currentPage} / ${totalPages}`;
  previousPageButton.disabled = currentPage === 1;
  nextPageButton.disabled = currentPage === totalPages;
}

async function loadPhotos() {
  try {
    const response = await fetch("/api/photos", { headers: { Accept: "application/json" } });
    if (!response.ok) {
      throw new Error("撮影履歴を取得できませんでした。");
    }
    photos = await response.json();
    renderGallery();
  } catch (error) {
    setStatus(error.message, true);
  }
}

function renderVideos() {
  if (
    videoList === null
    || emptyVideoMessage === null
    || videoTableWrap === null
    || videoPagination === null
    || previousVideoPageButton === null
    || nextVideoPageButton === null
    || videoPageInfo === null
  ) {
    return;
  }

  videoList.replaceChildren();
  emptyVideoMessage.hidden = videos.length > 0;
  videoTableWrap.hidden = videos.length === 0;
  const totalPages = Math.max(1, Math.ceil(videos.length / videosPerPage));
  currentVideoPage = Math.min(currentVideoPage, totalPages);
  const firstVideo = (currentVideoPage - 1) * videosPerPage;
  const visibleVideos = videos.slice(firstVideo, firstVideo + videosPerPage);

  for (const video of visibleVideos) {
    const row = document.createElement("tr");
    const time = document.createElement("td");
    const duration = document.createElement("td");
    const actions = document.createElement("td");
    const downloadLink = document.createElement("a");
    const downloadIcon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    const downloadPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
    const deleteButton = document.createElement("button");
    const deleteIcon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    const deletePath = document.createElementNS("http://www.w3.org/2000/svg", "path");

    time.textContent = formatDate(video.captured_at);
    duration.textContent = formatDuration(video.duration_seconds);
    actions.className = "video-actions";
    downloadLink.className = "download-button";
    downloadLink.href = video.url;
    downloadLink.download = `${video.id}.mp4`;
    downloadLink.setAttribute("aria-label", `${formatDate(video.captured_at)}の動画をダウンロード`);
    downloadIcon.setAttribute("viewBox", "0 0 24 24");
    downloadIcon.setAttribute("aria-hidden", "true");
    downloadPath.setAttribute("d", "M12 3v12m0 0 4-4m-4 4-4-4M5 21h14");
    downloadIcon.append(downloadPath);
    downloadLink.append(downloadIcon);
    deleteButton.className = "delete-video-button";
    deleteButton.type = "button";
    deleteButton.setAttribute("aria-label", `${formatDate(video.captured_at)}の動画を削除`);
    deleteButton.addEventListener("click", () => deleteVideo(video, deleteButton));
    deleteIcon.setAttribute("viewBox", "0 0 24 24");
    deleteIcon.setAttribute("aria-hidden", "true");
    deletePath.setAttribute("d", "M4 7h16M10 11v6m4-6v6M9 7V4h6v3m-9 0 1 14h10l1-14");
    deleteIcon.append(deletePath);
    deleteButton.append(deleteIcon);
    actions.append(downloadLink, deleteButton);
    row.append(time, duration, actions);
    videoList.append(row);
  }

  videoPagination.hidden = videos.length <= videosPerPage;
  videoPageInfo.textContent = `${currentVideoPage} / ${totalPages}`;
  previousVideoPageButton.disabled = currentVideoPage === 1;
  nextVideoPageButton.disabled = currentVideoPage === totalPages;
}

async function loadVideos() {
  if (videoList === null) {
    return;
  }

  try {
    const response = await fetch("/api/videos", { headers: { Accept: "application/json" } });
    if (!response.ok) {
      throw new Error("録画動画の一覧を取得できませんでした。");
    }
    videos = await response.json();
    renderVideos();
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function deleteVideo(video, deleteButton) {
  if (!window.confirm(`${formatDate(video.captured_at)}の動画を削除しますか？`)) {
    return;
  }

  deleteButton.disabled = true;
  try {
    const response = await fetch(`/api/videos/${encodeURIComponent(video.id)}`, {
      method: "DELETE",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      const payload = await response.json();
      throw new Error(payload.detail || "動画を削除できませんでした。");
    }

    setStatus("動画を削除しました。");
    await loadVideos();
  } catch (error) {
    setStatus(error.message, true);
    deleteButton.disabled = false;
  }
}

const publicErrorMessages = {
  "Video storage is full": "動画の保存容量が上限に達しました。",
  "Recording failed": "動画の録画に失敗しました。",
  "Recording stop failed": "録画を停止できませんでした。",
  "Live frame unavailable": "映像を表示できません。カメラの接続を確認してください。",
};

function publicErrorMessage(message) {
  return publicErrorMessages[message] || "動体検知でエラーが発生しました。";
}

function renderMotionStatus(payload) {
  motionStatus = payload;
  renderMotionAnalysis(payload);
  if (cameraNotice !== null) {
    const isError = Boolean(payload.error) || payload.stream_state === "stale" || payload.state === "error";
    let message = "";
    if (payload.error) {
      message = publicErrorMessage(payload.error);
    } else if (payload.stream_state === "stale") {
      message = "映像が更新されていません。";
    } else if (payload.state === "error") {
      message = "動体検知でエラーが発生しました。";
    } else if (payload.state === "recording") {
      message = "録画中";
    }
    cameraNotice.textContent = message;
    cameraNotice.classList.toggle("error", isError);
    cameraNotice.hidden = cameraNotice.textContent === "";
  }

  if (motionToggle !== null) {
    motionToggle.disabled = motionUpdateInProgress;
    motionToggle.classList.toggle("enabled", payload.enabled);
    motionToggle.textContent = payload.enabled ? "動体検知を停止" : "動体検知を開始";
  }
}

function renderMotionAnalysis(payload) {
  if (motionDiagnostics === null || motionOverlay === null) return;
  motionOverlay.replaceChildren();
  motionOverlay.hidden = !motionDiagnostics.open;
  if (!motionDiagnostics.open) return;
  if (!("analysis" in payload) || !("last_recording_trigger" in payload)) {
    motionAnalysisStatus.textContent = "サーバーから判定情報が返されていません。サービスの更新・再起動を確認してください。";
    return;
  }
  const historical = motionAnalysisSource.value === "trigger";
  const analysis = historical ? payload.last_recording_trigger : payload.analysis;
  if (!historical && (payload.stream_state === "stale" || payload.state === "error")) {
    motionAnalysisStatus.textContent = "カメラの状態を確認できないため、現在の判定を表示できません。";
    return;
  }
  if (!analysis) {
    motionAnalysisStatus.textContent = historical
      ? "この起動中の録画開始記録はありません。"
      : (payload.enabled ? "初期化・最初の判定を待っています。" : "動体検知は停止しています。");
    return;
  }
  const reasons = {
    illumination: "画面全体の明るさ変化として除外",
    settling: "露出が落ち着くまで待機",
    still: "動きなし",
    candidate: "動きの候補（連続回数を確認中）",
    motion: "動きを検知",
  };
  const percent = (value) => `${(value * 100).toFixed(1)}%`;
  motionAnalysisStatus.textContent = `${formatDate(analysis.at)}：${reasons[analysis.reason]}。`
    + ` 最大領域変化 ${percent(analysis.largest_tile_changed_ratio)}`
    + ` / 判定基準 ${percent(analysis.min_changed_ratio)}、`
    + `連続 ${analysis.consecutive_frames}/${analysis.required_frames} 回。`
    + ` 明るさ補正 ${analysis.brightness_shift}、画素差の閾値 ${analysis.threshold}、`
    + `補正前の全体変化 ${percent(analysis.raw_changed_ratio)}。`;
  motionOverlay.setAttribute("viewBox", `0 0 ${analysis.width} ${analysis.height}`);
  for (const tile of analysis.tiles) {
    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("x", tile.x);
    rect.setAttribute("y", tile.y);
    rect.setAttribute("width", Math.min(analysis.tile_size, analysis.width - tile.x));
    rect.setAttribute("height", Math.min(analysis.tile_size, analysis.height - tile.y));
    rect.setAttribute("fill", tile.confirmed ? "#ff404033" : "#ffd54f22");
    rect.setAttribute("stroke", tile.confirmed ? "#ff4040" : "#ffd54f");
    rect.setAttribute("stroke-width", "2");
    motionOverlay.append(rect);
  }
}

function showMotionConnectionError() {
  if (motionOverlay !== null) motionOverlay.replaceChildren();
  if (motionAnalysisStatus !== null) {
    motionAnalysisStatus.textContent = "判定情報を取得できません。";
  }
  if (cameraNotice !== null) {
    cameraNotice.textContent = "カメラの状態を取得できません。";
    cameraNotice.classList.add("error");
    cameraNotice.hidden = false;
  }
  if (motionToggle !== null) {
    motionToggle.disabled = true;
  }
}

async function fetchMotionJson(url, options = {}) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 5000);
  try {
    const response = await fetch(url, { ...options, cache: "no-store", signal: controller.signal });
    const payload = await response.json();
    return { response, payload };
  } finally {
    window.clearTimeout(timeout);
  }
}

async function loadMotionStatus() {
  if (
    motionToggle === null
    || motionUpdateInProgress
    || motionStatusRequestInProgress
    || document.visibilityState !== "visible"
  ) {
    return;
  }
  motionStatusRequestInProgress = true;
  const requestToken = ++motionStatusRequestToken;
  try {
    const { response, payload } = await fetchMotionJson("/api/motion", {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      throw new Error("動体検知の状態を取得できませんでした。");
    }
    if (requestToken !== motionStatusRequestToken || motionUpdateInProgress) {
      return;
    }
    renderMotionStatus(payload);
  } catch (error) {
    if (requestToken !== motionStatusRequestToken || motionUpdateInProgress) {
      return;
    }
    showMotionConnectionError();
  } finally {
    motionStatusRequestInProgress = false;
  }
}

async function toggleMotionDetection() {
  if (motionToggle === null || motionStatus === null || motionUpdateInProgress) {
    return;
  }

  const nextEnabled = !motionStatus.enabled;
  const action = nextEnabled ? "開始" : "停止";
  const confirmation = nextEnabled
    ? "動体検知を開始しますか？"
    : "動体検知を停止しますか？録画中の動画は保存されず、破棄されます。";
  if (!window.confirm(confirmation)) {
    return;
  }
  motionUpdateInProgress = true;
  let updateSucceeded = false;
  const requestToken = ++motionStatusRequestToken;
  motionToggle.disabled = true;
  motionToggle.textContent = `動体検知を${action}中…`;
  try {
    const { response, payload } = await fetchMotionJson("/api/motion", {
      method: "PUT",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ enabled: nextEnabled }),
    });
    if (!response.ok) {
      throw new Error(payload.detail || "動体検知を切り替えられませんでした。");
    }
    if (requestToken === motionStatusRequestToken) {
      renderMotionStatus(payload);
      updateSucceeded = true;
      setStatus(payload.enabled ? "動体検知を開始しました。" : "動体検知を停止しました。");
    }
  } catch (error) {
    if (requestToken === motionStatusRequestToken) {
      showMotionConnectionError();
      setStatus(error.message, true);
    }
  } finally {
    motionUpdateInProgress = false;
    if (updateSucceeded && motionStatus !== null) {
      renderMotionStatus(motionStatus);
    }
    loadMotionStatus();
  }
}

async function capturePhoto() {
  captureButton.disabled = true;
  captureLabel.textContent = "撮影中…";
  setStatus("撮影しています…");

  try {
    const response = await fetch("/api/capture", {
      method: "POST",
      headers: { Accept: "application/json" },
    });
    const payload = await response.json();
    if (!response.ok) {
      const retryAfter = Number.parseInt(response.headers.get("Retry-After"), 10);
      if (Number.isFinite(retryAfter) && retryAfter > 0) {
        startCaptureCooldown(retryAfter);
      }
      throw new Error(payload.detail || "撮影に失敗しました。");
    }

    setStatus("撮影しました。");
    currentPage = 1;
    await loadPhotos();
    const cooldown = Number.parseInt(response.headers.get("X-Capture-Cooldown"), 10);
    if (Number.isFinite(cooldown) && cooldown > 0) {
      startCaptureCooldown(cooldown);
    }
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    if (Date.now() >= cooldownEndsAt) {
      captureLabel.textContent = "撮影";
      captureButton.disabled = false;
    }
  }
}

async function deleteSelectedPhoto() {
  if (selectedPhoto === null) {
    return;
  }
  if (!window.confirm(`${formatDate(selectedPhoto.captured_at)}の写真を削除しますか？`)) {
    return;
  }

  deletePhotoButton.disabled = true;
  try {
    const response = await fetch(`/api/photos/${encodeURIComponent(selectedPhoto.id)}`, {
      method: "DELETE",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      const payload = await response.json();
      throw new Error(payload.detail || "写真を削除できませんでした。");
    }

    selectedPhoto = null;
    photoDialog.close();
    setStatus("写真を削除しました。");
    await loadPhotos();
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    deletePhotoButton.disabled = false;
  }
}

captureButton.addEventListener("click", capturePhoto);
previousPageButton.addEventListener("click", () => {
  currentPage -= 1;
  renderGallery();
});
nextPageButton.addEventListener("click", () => {
  currentPage += 1;
  renderGallery();
});
if (previousVideoPageButton !== null && nextVideoPageButton !== null) {
  previousVideoPageButton.addEventListener("click", () => {
    currentVideoPage -= 1;
    renderVideos();
  });
  nextVideoPageButton.addEventListener("click", () => {
    currentVideoPage += 1;
    renderVideos();
  });
}
closeDialogButton.addEventListener("click", () => photoDialog.close());
deletePhotoButton.addEventListener("click", deleteSelectedPhoto);
if (motionToggle !== null) {
  motionAnalysisStatus.textContent = "判定情報を取得中です。";
  motionToggle.addEventListener("click", toggleMotionDetection);
  motionDiagnostics.addEventListener("toggle", () => {
    if (motionStatus !== null) renderMotionAnalysis(motionStatus);
    if (motionDiagnostics.open) loadMotionStatus();
  });
  motionAnalysisSource.addEventListener("change", () => {
    if (motionStatus !== null) renderMotionAnalysis(motionStatus);
  });
}
photoDialog.addEventListener("close", () => {
  selectedPhoto = null;
  dialogImage.removeAttribute("src");
});
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") {
    loadPhotos();
    loadVideos();
    loadMotionStatus();
  }
});
loadPhotos();
loadVideos();
if (document.visibilityState === "visible") {
  loadMotionStatus();
}
if (motionToggle !== null) {
  let statusTicks = 0;
  window.setInterval(() => {
    statusTicks += 1;
    if (document.visibilityState === "visible" && (motionDiagnostics.open || statusTicks % 3 === 0)) {
      loadMotionStatus();
    }
  }, 1000);
}
if (videoList !== null) {
  window.setInterval(loadVideos, 10_000);
}
