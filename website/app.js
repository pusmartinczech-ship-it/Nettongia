const buttons = document.querySelectorAll("[data-language]");
const translatable = document.querySelectorAll("[data-en][data-cs]");
const visitCount = document.querySelector("#visit-count");
const downloadCount = document.querySelector("#download-count");
const counterStatus = document.querySelector("#counter-status");
let latestCounters = null;

function renderCounters() {
  if (!latestCounters || !visitCount || !downloadCount) return;
  const locale = document.documentElement.lang === "cs" ? "cs-CZ" : "en-US";
  const format = new Intl.NumberFormat(locale);
  visitCount.textContent = format.format(latestCounters.visits);
  downloadCount.textContent = format.format(latestCounters.downloads);
}

function setLanguage(language) {
  const selected = language === "cs" ? "cs" : "en";
  document.documentElement.lang = selected;
  translatable.forEach((element) => {
    element.textContent = element.dataset[selected];
  });
  buttons.forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.language === selected));
  });
  renderCounters();
  try { localStorage.setItem("nettongia-language", selected); } catch (_) {}
}

buttons.forEach((button) => button.addEventListener("click", () => setLanguage(button.dataset.language)));
let stored = "";
try { stored = localStorage.getItem("nettongia-language") || ""; } catch (_) {}
setLanguage(stored || "en");

async function counterRequest(method = "GET", event = "") {
  const options = { method, headers: { Accept: "application/json" } };
  if (event) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify({ event });
  }
  const response = await fetch("/api/counters", options);
  if (!response.ok) throw new Error("Counter service unavailable");
  return response.json();
}

async function initializeCounters() {
  if (!visitCount || !downloadCount) return;
  try {
    let counted = false;
    try { counted = sessionStorage.getItem("nettongia-visit-counted") === "1"; } catch (_) {}
    latestCounters = counted
      ? await counterRequest()
      : await counterRequest("POST", "visit");
    if (!counted) {
      try { sessionStorage.setItem("nettongia-visit-counted", "1"); } catch (_) {}
    }
    renderCounters();
  } catch (_) {
    if (counterStatus) counterStatus.hidden = false;
  }
}

document.querySelectorAll("[data-download]").forEach((link) => {
  link.addEventListener("click", () => {
    fetch("/api/counters", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ event: "download" }),
      keepalive: true,
    }).catch(() => {});
  });
});

initializeCounters();
