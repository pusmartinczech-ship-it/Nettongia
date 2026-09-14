const buttons = document.querySelectorAll("[data-language]");
const translatable = document.querySelectorAll("[data-en][data-cs]");
function setLanguage(language) {
  const selected = language === "cs" ? "cs" : "en";
  document.documentElement.lang = selected;
  translatable.forEach((element) => {
    element.textContent = element.dataset[selected];
  });
  buttons.forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.language === selected));
  });
  try { localStorage.setItem("nettongia-language", selected); } catch (_) {}
}
buttons.forEach((button) => button.addEventListener("click", () => setLanguage(button.dataset.language)));
let stored = "";
try { stored = localStorage.getItem("nettongia-language") || ""; } catch (_) {}
setLanguage(stored || (navigator.language.toLowerCase().startsWith("cs") ? "cs" : "en"));
