const captureButton = document.querySelector("#capture-button");
const captureLabel = document.querySelector("#capture-label");
const statusMessage = document.querySelector("#status");
const latestSection = document.querySelector("#latest");
const latestImage = document.querySelector("#latest-image");
const latestTime = document.querySelector("#latest-time");
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

const photosPerPage = 8;
let photos = [];
let currentPage = 1;
let selectedPhoto = null;
let latestPhotoId = null;
let statusTimer = null;
let cooldownTimer = null;
let cooldownEndsAt = 0;

function formatDate(value) {
  return new Intl.DateTimeFormat("ja-JP", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(value));
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

    latestImage.src = `${payload.url}?v=${encodeURIComponent(payload.id)}`;
    latestTime.textContent = formatDate(payload.captured_at);
    latestPhotoId = payload.id;
    latestSection.hidden = false;
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

    if (latestPhotoId === selectedPhoto.id) {
      latestSection.hidden = true;
      latestPhotoId = null;
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
closeDialogButton.addEventListener("click", () => photoDialog.close());
deletePhotoButton.addEventListener("click", deleteSelectedPhoto);
photoDialog.addEventListener("close", () => {
  selectedPhoto = null;
  dialogImage.removeAttribute("src");
});
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") {
    loadPhotos();
  }
});
loadPhotos();
