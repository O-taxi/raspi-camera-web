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
const motionSettingsButton = document.querySelector("#motion-settings-button");
const motionSettingsDialog = document.querySelector("#motion-settings-dialog");
const motionSettingsForm = document.querySelector("#motion-settings-form");
const motionSettingsError = document.querySelector("#motion-settings-error");
const saveMotionSettingsButton = document.querySelector("#save-motion-settings");
const cancelMotionSettingsButton = document.querySelector("#cancel-motion-settings");
const closeMotionSettingsButton = document.querySelector("#close-motion-settings");
const minimumRecordSecondsInput = document.querySelector("#minimum-record-seconds");
const recordSecondsInput = document.querySelector("#record-seconds");
const maximumRecordSecondsInput = document.querySelector("#maximum-record-seconds");
const cooldownSecondsInput = document.querySelector("#cooldown-seconds");
const motionThresholdInput = document.querySelector("#motion-threshold");
const videoRecordButton = document.querySelector("#video-record-button");
const videoRecordLabel = document.querySelector("#video-record-label");
const rotationButton = document.querySelector("#rotation-button");
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
let motionSettingsUpdateInProgress = false;
let motionSettingsLoaded = false;
let videoRecordingControlInProgress = false;
let rotationUpdateInProgress = false;
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
  if (rotationButton !== null) {
    const degrees = payload.rotation_degrees;
    rotationButton.disabled = rotationUpdateInProgress || payload.recording_source !== null;
    rotationButton.setAttribute("aria-label", `映像を右に90度回転（現在${degrees}度）`);
    rotationButton.title = `映像を右に90度回転（現在${degrees}度）`;
  }
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
  if (motionSettingsButton !== null) {
    motionSettingsButton.disabled = motionSettingsUpdateInProgress;
  }
  if (videoRecordButton !== null && videoRecordLabel !== null) {
    const manualRecording = payload.recording_source === "manual";
    const motionRecording = payload.recording_source === "motion";
    videoRecordLabel.textContent = manualRecording
      ? "録画停止"
      : motionRecording ? "動体検知録画中" : "動画";
    videoRecordButton.disabled = videoRecordingControlInProgress || motionRecording;
    videoRecordButton.classList.toggle("recording", manualRecording);
    videoRecordButton.setAttribute(
      "aria-label",
      manualRecording
        ? "手動録画を停止して保存"
        : motionRecording ? "動体検知で録画中です。手動録画は開始できません" : "動画撮影を開始",
    );
  }
  if (saveMotionSettingsButton !== null && motionSettingsDialog?.open) {
    saveMotionSettingsButton.disabled = motionSettingsUpdateInProgress
      || !motionSettingsLoaded
      || payload.recording_source !== null;
  }
}

function renderMotionAnalysis(payload) {
  if (motionDiagnostics === null || motionOverlay === null) return;
  motionOverlay.replaceChildren();
  // SVGElement does not reflect the HTML `hidden` property into its attributes.
  motionOverlay.toggleAttribute("hidden", !motionDiagnostics.open);
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
    camera_motion: "カメラの揺れを補正（動きなし）",
    candidate: "動きの候補（連続回数を確認中）",
    motion: "動きを検知",
  };
  const percent = (value) => `${(value * 100).toFixed(1)}%`;
  motionAnalysisStatus.textContent = `${formatDate(analysis.at)}：${reasons[analysis.reason]}。`
    + ` 最大領域変化 ${percent(analysis.largest_tile_changed_ratio)}`
    + ` / 判定基準 ${percent(analysis.min_changed_ratio)}、`
    + `連続 ${analysis.consecutive_frames}/${analysis.required_frames} 回。`
    + ` 明るさ補正 ${analysis.brightness_shift}、画素差の閾値 ${analysis.threshold}、`
    + `補正前の全体変化 ${percent(analysis.raw_changed_ratio)}。`
    + ` 位置補正 横${analysis.camera_shift_x ?? 0}px・縦${analysis.camera_shift_y ?? 0}px`
    + `（低解像度映像上、補正を支持した領域 ${percent(analysis.camera_shift_support ?? 0)}）。`;
  const degrees = payload.rotation_degrees || 0;
  const portrait = degrees === 90 || degrees === 270;
  motionOverlay.setAttribute("viewBox", `0 0 ${portrait ? analysis.height : analysis.width} ${portrait ? analysis.width : analysis.height}`);
  for (const tile of analysis.tiles) {
    const width = Math.min(analysis.tile_size, analysis.width - tile.x);
    const height = Math.min(analysis.tile_size, analysis.height - tile.y);
    let x = tile.x;
    let y = tile.y;
    let boxWidth = width;
    let boxHeight = height;
    if (degrees === 90) {
      x = analysis.height - tile.y - height;
      y = tile.x;
      boxWidth = height;
      boxHeight = width;
    } else if (degrees === 180) {
      x = analysis.width - tile.x - width;
      y = analysis.height - tile.y - height;
    } else if (degrees === 270) {
      x = tile.y;
      y = analysis.width - tile.x - width;
      boxWidth = height;
      boxHeight = width;
    }
    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("x", x);
    rect.setAttribute("y", y);
    rect.setAttribute("width", boxWidth);
    rect.setAttribute("height", boxHeight);
    rect.setAttribute("fill", tile.confirmed ? "#ff404033" : "#ffd54f22");
    rect.setAttribute("stroke", tile.confirmed ? "#ff4040" : "#ffd54f");
    rect.setAttribute("stroke-width", "2");
    motionOverlay.append(rect);
  }
}

function showMotionConnectionError() {
  if (rotationButton !== null) rotationButton.disabled = true;
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
  if (videoRecordButton !== null) {
    videoRecordButton.disabled = true;
  }
  if (motionSettingsButton !== null) {
    motionSettingsButton.disabled = true;
  }
}

async function rotateCamera() {
  if (rotationButton === null || motionStatus === null || rotationUpdateInProgress) return;
  rotationUpdateInProgress = true;
  rotationButton.disabled = true;
  const degrees = ((motionStatus.rotation_degrees || 0) + 90) % 360;
  ++motionStatusRequestToken;
  try {
    const { response, payload } = await fetchMotionJson("/api/rotation", {
      method: "PUT",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ degrees }),
    });
    if (!response.ok) throw new Error(response.status === 409
      ? "録画中は回転できません。録画の終了後に再度お試しください。"
      : "回転設定を保存できませんでした。");
    renderMotionStatus({ ...motionStatus, rotation_degrees: payload.degrees });
    setStatus(`映像を${payload.degrees}度に回転しました。`);
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    rotationUpdateInProgress = false;
    if (motionStatus !== null) renderMotionStatus(motionStatus);
    loadMotionStatus();
  }
}

function setMotionSettingsError(message) {
  if (motionSettingsError === null) return;
  motionSettingsError.textContent = message;
  motionSettingsError.hidden = message === "";
}

function setMotionSettingsBusy(busy) {
  motionSettingsUpdateInProgress = busy;
  if (motionSettingsButton !== null) motionSettingsButton.disabled = busy;
  if (saveMotionSettingsButton !== null) {
    saveMotionSettingsButton.disabled = busy
      || !motionSettingsLoaded
      || (motionStatus !== null && motionStatus.recording_source !== null);
    saveMotionSettingsButton.textContent = busy ? "保存中…" : "保存";
  }
  if (cancelMotionSettingsButton !== null) cancelMotionSettingsButton.disabled = busy;
  if (closeMotionSettingsButton !== null) closeMotionSettingsButton.disabled = busy;
}

async function openMotionSettings() {
  if (motionSettingsDialog === null || motionSettingsUpdateInProgress) return;
  motionSettingsLoaded = false;
  setMotionSettingsError("");
  motionSettingsDialog.showModal();
  setMotionSettingsBusy(true);
  try {
    const { response, payload } = await fetchMotionJson("/api/motion/settings", {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) throw new Error("設定を読み込めませんでした。");
    minimumRecordSecondsInput.value = payload.minimum_record_seconds;
    recordSecondsInput.value = payload.record_seconds;
    maximumRecordSecondsInput.value = payload.maximum_record_seconds;
    cooldownSecondsInput.value = payload.cooldown_seconds;
    motionThresholdInput.value = payload.threshold;
    motionSettingsLoaded = true;
  } catch (error) {
    setMotionSettingsError(error.message);
  } finally {
    setMotionSettingsBusy(false);
    if (
      motionStatus !== null
      && motionStatus.recording_source !== null
      && saveMotionSettingsButton !== null
    ) {
      saveMotionSettingsButton.disabled = true;
    }
  }
}

async function saveMotionSettings(event) {
  event.preventDefault();
  if (motionSettingsForm === null || motionSettingsUpdateInProgress || !motionSettingsLoaded) return;
  if (!motionSettingsForm.reportValidity()) return;
  const payload = {
    minimum_record_seconds: Number(minimumRecordSecondsInput.value),
    record_seconds: Number(recordSecondsInput.value),
    maximum_record_seconds: Number(maximumRecordSecondsInput.value),
    cooldown_seconds: Number(cooldownSecondsInput.value),
    threshold: Number(motionThresholdInput.value),
  };
  if (
    payload.minimum_record_seconds > payload.record_seconds
    || payload.record_seconds > payload.maximum_record_seconds
  ) {
    setMotionSettingsError("最短保存時間、検知後の録画時間、最大録画時間の順に小さい値から設定してください。");
    return;
  }

  setMotionSettingsError("");
  setMotionSettingsBusy(true);
  try {
    const { response, payload: result } = await fetchMotionJson("/api/motion/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      if (response.status === 409) {
        throw new Error("録画中は変更できません。録画の終了後に保存してください。");
      }
      throw new Error(typeof result.detail === "string" ? result.detail : "設定を保存できませんでした。");
    }
    motionSettingsDialog.close();
    setStatus("動体検知・録画設定を保存しました。");
  } catch (error) {
    setMotionSettingsError(error.message);
  } finally {
    setMotionSettingsBusy(false);
    loadMotionStatus();
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
    || motionSettingsUpdateInProgress
    || videoRecordingControlInProgress
    || rotationUpdateInProgress
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
    if (
      requestToken !== motionStatusRequestToken
      || motionUpdateInProgress
      || motionSettingsUpdateInProgress
      || videoRecordingControlInProgress
      || rotationUpdateInProgress
    ) {
      return;
    }
    renderMotionStatus(payload);
  } catch (error) {
    if (
      requestToken !== motionStatusRequestToken
      || motionUpdateInProgress
      || motionSettingsUpdateInProgress
      || videoRecordingControlInProgress
      || rotationUpdateInProgress
    ) {
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
    : motionStatus.recording_source === "manual"
      ? "動体検知を停止しますか？手動録画中の動画はそのまま継続します。"
      : "動体検知を停止しますか？動体検知で録画中の動画は保存されず、破棄されます。";
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

async function toggleVideoRecording() {
  if (
    videoRecordButton === null
    || motionStatus === null
    || videoRecordingControlInProgress
    || motionStatus.recording_source === "motion"
  ) {
    return;
  }

  const stopping = motionStatus.recording_source === "manual";
  const requestToken = ++motionStatusRequestToken;
  videoRecordingControlInProgress = true;
  videoRecordButton.disabled = true;
  videoRecordLabel.textContent = stopping ? "保存中…" : "録画開始中…";
  try {
    const { response, payload } = await fetchMotionJson(
      stopping ? "/api/recording/stop" : "/api/recording/start",
      {
        method: "POST",
        headers: { Accept: "application/json" },
      },
    );
    if (!response.ok) {
      const messages = {
        "Video storage is full": "動画の保存容量が上限に達しています。古い動画を整理してください。",
        "A recording is already active": "すでに録画中です。",
        "No manual recording is active": "手動録画はすでに停止しています。",
      };
      throw new Error(messages[payload.detail] || "動画を開始・停止できませんでした。");
    }
    if (requestToken === motionStatusRequestToken) renderMotionStatus(payload);
    setStatus(stopping ? "動画を保存しました。" : "動画撮影を開始しました。");
    if (stopping) await loadVideos();
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    videoRecordingControlInProgress = false;
    if (motionStatus !== null) renderMotionStatus(motionStatus);
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
if (motionSettingsButton !== null && motionSettingsForm !== null) {
  motionSettingsButton.addEventListener("click", openMotionSettings);
  motionSettingsForm.addEventListener("submit", saveMotionSettings);
  cancelMotionSettingsButton.addEventListener("click", () => motionSettingsDialog.close());
  closeMotionSettingsButton.addEventListener("click", () => motionSettingsDialog.close());
}
if (videoRecordButton !== null) {
  videoRecordButton.addEventListener("click", toggleVideoRecording);
}
if (rotationButton !== null) {
  rotationButton.addEventListener("click", rotateCamera);
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
    if (
      document.visibilityState === "visible"
      && (motionDiagnostics.open || motionStatus?.recording_source === "manual" || statusTicks % 3 === 0)
    ) {
      loadMotionStatus();
    }
  }, 1000);
}
if (videoList !== null) {
  window.setInterval(loadVideos, 10_000);
}
