/* Visual effects shared by every page. Nothing here is needed for the app to work:
   each effect is optional, and all motion is skipped when the user prefers reduced motion. */
(() => {
  const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const fine = window.matchMedia("(hover: hover) and (pointer: fine)").matches;
  const root = document.documentElement;

  // Top bar gains a shadow once the page has scrolled.
  const bar = document.querySelector(".topbar");
  if (bar) {
    const onScroll = () => bar.classList.toggle("scrolled", window.scrollY > 6);
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  // A thin progress bar while requests are in flight. Fast requests never show it.
  if (typeof window.fetch === "function") {
    const original = window.fetch.bind(window);
    let inflight = 0;
    let timer = null;
    const done = () => {
      inflight = Math.max(0, inflight - 1);
      if (!inflight) { clearTimeout(timer); timer = null; root.classList.remove("busy"); }
    };
    window.fetch = (...args) => {
      inflight += 1;
      if (!timer) timer = setTimeout(() => root.classList.add("busy"), 250);
      return original(...args).finally(done);
    };
  }

  // Cursor spotlight: tell the hovered surface where the pointer is.
  if (fine && !calm) {
    const SURFACES = ".card, .tile, .col, .kind-card, .promo, .drop";
    let frame = 0;
    document.addEventListener("pointermove", (event) => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        const target = event.target instanceof Element ? event.target.closest(SURFACES) : null;
        if (!target) return;
        const box = target.getBoundingClientRect();
        target.style.setProperty("--mx", `${event.clientX - box.left}px`);
        target.style.setProperty("--my", `${event.clientY - box.top}px`);
      });
    }, { passive: true });
  }

  // Tabs: one ink bar glides under the active tab.
  function inkTabs(tabs) {
    const ink = document.createElement("span");
    ink.className = "tab-ink";
    ink.setAttribute("aria-hidden", "true");
    tabs.append(ink);
    const place = () => {
      const active = tabs.querySelector(".tab.active");
      if (!active || !active.offsetWidth) return;  // hidden: measured again once shown
      ink.style.width = `${Math.max(0, active.offsetWidth - 28)}px`;
      ink.style.transform = `translateX(${active.offsetLeft + 14}px)`;
      // Adding a class that is already there still queues a mutation record, which would
      // call place() again from the observer below, forever. Touch the class only once.
      if (!tabs.classList.contains("inked")) tabs.classList.add("inked");
    };
    tabs.addEventListener("click", () => requestAnimationFrame(place));
    new MutationObserver(place).observe(tabs, { attributes: true, attributeFilter: ["class"], subtree: true });
    if ("ResizeObserver" in window) new ResizeObserver(place).observe(tabs);
    window.addEventListener("resize", place);
    place();
  }
  document.querySelectorAll(".tabs").forEach(inkTabs);

  // Numbers on tiles count up to their value when the tile appears.
  const NUMBER = /^(\d[\d,]*)(\.\d+)?$/;
  function countUp(tile) {
    const value = tile.querySelector(".v");
    const node = value && value.firstChild;
    if (!node || node.nodeType !== Node.TEXT_NODE) return;
    const match = NUMBER.exec(node.data.trim());
    if (!match) return;
    const target = Number(node.data.replace(/,/g, ""));
    if (!Number.isFinite(target) || target === 0) return;
    const decimals = match[2] ? match[2].length - 1 : 0;
    const grouped = match[1].includes(",");
    const final = node.data;
    const start = performance.now();
    const length = 700;
    const step = (now) => {
      const t = Math.min(1, (now - start) / length);
      const eased = 1 - Math.pow(1 - t, 3);
      node.data = t === 1 ? final : (target * eased).toLocaleString("en-US", {
        minimumFractionDigits: decimals, maximumFractionDigits: decimals, useGrouping: grouped,
      });
      if (t < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
  if (!calm) {
    new MutationObserver((records) => {
      for (const record of records) {
        for (const added of record.addedNodes) {
          if (!(added instanceof Element)) continue;
          if (added.matches(".tile")) countUp(added);
          added.querySelectorAll?.(".tile").forEach(countUp);
        }
      }
    }).observe(document.body, { childList: true, subtree: true });
  }
})();
