/* Chart fullscreen toggle — delegated, no Dash callbacks needed.
 *
 * Any element with class="chart-fullscreen-btn" inside a parent with
 * data-fs-wrapper will trigger the fullscreen toggle when clicked.
 */
(function () {
  function toggle(wrapper, btn) {
    var isFs = wrapper.classList.toggle("chart-fullscreen");
    document.body.classList.toggle("chart-fullscreen-active", isFs);
    var icon = btn.querySelector(".material-symbols-outlined");
    if (icon) icon.textContent = isFs ? "fullscreen_exit" : "fullscreen";
    // Give the DOM one frame to apply the new class, then trigger LWC autoSize
    requestAnimationFrame(function () {
      window.dispatchEvent(new Event("resize"));
    });
  }

  document.addEventListener("click", function (e) {
    var btn = e.target.closest(".chart-fullscreen-btn");
    if (!btn) return;
    var wrapper = btn.closest("[data-fs-wrapper]");
    if (wrapper) toggle(wrapper, btn);
  });

  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    var active = document.querySelector("[data-fs-wrapper].chart-fullscreen");
    if (!active) return;
    var btn = active.querySelector(".chart-fullscreen-btn");
    toggle(active, btn || active);
  });
})();
