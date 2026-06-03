/* ── State ── */
let selectedFile = null;
let progressInterval = null;
let progressIdx = 0;
let toastTimer = null;

const PROGRESS_MESSAGES = [
  "Reading your PDF...",
  "Extracting text...",
  "Sending to AI...",
  "Analyzing the manual...",
  "Writing simplified steps...",
  "Almost done..."
];

/* ── DOM refs ── */
const uploadSection     = document.getElementById("uploadSection");
const processingSection = document.getElementById("processingSection");
const guideModal        = document.getElementById("guideModal");
const toast             = document.getElementById("toast");
const fileInput         = document.getElementById("fileInput");
const filePreview       = document.getElementById("filePreview");
const fileNameEl        = document.getElementById("fileName");
const fileSizeEl        = document.getElementById("fileSize");
const simplifyBtn       = document.getElementById("simplifyBtn");
const clearFileBtn      = document.getElementById("clearFile");
const uploadZone        = document.getElementById("uploadZone");
const processingStatus  = document.getElementById("processingStatus");
const stepsContainer    = document.getElementById("stepsContainer");
const guideTitle        = document.getElementById("guideTitle");
const guideSummary      = document.getElementById("guideSummary");
const printBtn          = document.getElementById("printBtn");
const closeModal        = document.getElementById("closeModal");

/* ── Upload zone ── */
uploadZone.addEventListener("click", () => fileInput.click());
uploadZone.addEventListener("dragover", e => { e.preventDefault(); uploadZone.classList.add("drag-over"); });
uploadZone.addEventListener("dragleave", () => uploadZone.classList.remove("drag-over"));
uploadZone.addEventListener("drop", e => {
  e.preventDefault();
  uploadZone.classList.remove("drag-over");
  if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]);
});
fileInput.addEventListener("change", () => { if (fileInput.files[0]) setFile(fileInput.files[0]); });

function setFile(f) {
  if (!f.name.toLowerCase().endsWith(".pdf")) { showToast("Only PDF files are accepted."); return; }
  if (f.size > 50 * 1024 * 1024) { showToast("File too large — max 50 MB."); return; }
  selectedFile = f;
  fileNameEl.textContent = f.name;
  fileSizeEl.textContent = formatBytes(f.size);
  filePreview.hidden = false;
  simplifyBtn.disabled = false;
}

clearFileBtn.addEventListener("click", () => {
  selectedFile = null;
  fileInput.value = "";
  filePreview.hidden = true;
  simplifyBtn.disabled = true;
});

/* ── Main flow ── */
simplifyBtn.addEventListener("click", async () => {
  if (!selectedFile) return;

  uploadSection.hidden = true;
  processingSection.hidden = false;
  startProgress();

  const formData = new FormData();
  formData.append("pdf", selectedFile);

  try {
    const uploadRes = await fetch("/api/upload", { method: "POST", body: formData });
    const uploadData = await uploadRes.json();
    if (!uploadRes.ok) throw new Error(uploadData.error || "Upload failed");

    const processRes = await fetch(`/api/process/${uploadData.job_id}`);
    const guide = await processRes.json();
    if (!processRes.ok) throw new Error(guide.error || "Processing failed");

    stopProgress();
    processingSection.hidden = true;
    uploadSection.hidden = false;

    renderGuide(guide);
    openModal();

  } catch (err) {
    stopProgress();
    processingSection.hidden = true;
    uploadSection.hidden = false;
    showToast(err.message || "Something went wrong — please try again.");
  }
});

/* ── Modal ── */
function openModal() {
  guideModal.hidden = false;
  document.body.style.overflow = "hidden";
}

function closeGuideModal() {
  guideModal.hidden = true;
  document.body.style.overflow = "";
}

closeModal.addEventListener("click", closeGuideModal);

guideModal.addEventListener("click", e => {
  if (e.target === guideModal) closeGuideModal();
});

/* ── Progress ── */
function startProgress() {
  progressIdx = 0;
  processingStatus.textContent = PROGRESS_MESSAGES[0];
  progressInterval = setInterval(() => {
    progressIdx = (progressIdx + 1) % PROGRESS_MESSAGES.length;
    processingStatus.style.opacity = "0";
    setTimeout(() => {
      processingStatus.textContent = PROGRESS_MESSAGES[progressIdx];
      processingStatus.style.opacity = "1";
    }, 200);
  }, 7000);
}
function stopProgress() { clearInterval(progressInterval); progressInterval = null; }

/* ── Guide renderer ── */
function renderGuide(data) {
  guideTitle.textContent = data.title || "Simplified Guide";
  guideSummary.textContent = data.summary || "";
  stepsContainer.innerHTML = "";
  (data.steps || []).forEach(step => stepsContainer.appendChild(buildCard(step)));
}

function buildCard(step) {
  const card = document.createElement("div");
  card.className = "step-card";
  card.innerHTML = `
    <div class="step-header">
      <span class="step-num">${step.step_number}</span>
      <span class="step-title">${escHtml(step.title)}</span>
    </div>
    <div class="step-body">
      <p class="step-instructions">${escHtml(step.instructions)}</p>
      <p class="step-why">${escHtml(step.why_it_matters)}</p>
      ${buildWarnings(step.warnings)}
    </div>
  `;
  return card;
}

function buildWarnings(warnings) {
  if (!warnings || !warnings.length) return "";
  return `<div class="warnings">${warnings.map(w => `<div class="warning">${escHtml(w)}</div>`).join("")}</div>`;
}

/* ── Toast ── */
function showToast(msg) {
  toast.textContent = msg;
  toast.hidden = false;
  requestAnimationFrame(() => toast.classList.add("visible"));
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toast.classList.remove("visible");
    setTimeout(() => { toast.hidden = true; }, 200);
  }, 3500);
}

/* ── Print ── */
printBtn.addEventListener("click", () => window.print());

/* ── Utilities ── */
function escHtml(str) {
  return String(str || "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
function formatBytes(b) {
  if (b < 1024) return b + " B";
  if (b < 1024 * 1024) return (b / 1024).toFixed(1) + " KB";
  return (b / (1024 * 1024)).toFixed(1) + " MB";
}
