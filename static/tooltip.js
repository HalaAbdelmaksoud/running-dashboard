// Hover tooltips for any element with a data-tip attribute (all chart marks).
(function () {
  const tip = document.getElementById("tip");
  if (!tip) return;
  document.addEventListener("mouseover", (e) => {
    const el = e.target.closest("[data-tip]");
    if (!el) return;
    tip.textContent = el.getAttribute("data-tip");
    tip.hidden = false;
  });
  document.addEventListener("mousemove", (e) => {
    if (tip.hidden) return;
    const pad = 14, w = tip.offsetWidth, h = tip.offsetHeight;
    let x = e.clientX + pad, y = e.clientY - h - pad;
    if (x + w > innerWidth - 8) x = e.clientX - w - pad;
    if (y < 8) y = e.clientY + pad;
    tip.style.left = x + "px"; tip.style.top = y + "px";
  });
  document.addEventListener("mouseout", (e) => {
    if (e.target.closest("[data-tip]") && !e.relatedTarget?.closest?.("[data-tip]")) tip.hidden = true;
  });
})();
