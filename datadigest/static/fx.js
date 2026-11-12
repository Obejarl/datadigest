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
    const SURFACES = ".card, .tile, .col, .kind-card, .promo, .section-card, .drop";
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

  // Depth: background layers follow the pointer and the scroll at different speeds.
  if (!calm) {
    const layer = document.createElement("div");
    layer.className = "depth";
    layer.setAttribute("aria-hidden", "true");
    layer.append(document.createElement("i"), document.createElement("i"), document.createElement("i"));
    document.body.prepend(layer);
    let queued = 0;
    let px = 0, py = 0;
    const apply = () => {
      queued = 0;
      root.style.setProperty("--px", px.toFixed(3));
      root.style.setProperty("--py", py.toFixed(3));
      root.style.setProperty("--sy", String(Math.round(window.scrollY)));
    };
    const ask = () => { if (!queued) queued = requestAnimationFrame(apply); };
    if (fine) {
      window.addEventListener("pointermove", (event) => {
        px = event.clientX / window.innerWidth - 0.5;
        py = event.clientY / window.innerHeight - 0.5;
        ask();
      }, { passive: true });
    }
    window.addEventListener("scroll", ask, { passive: true });
  }

  // Small cards tilt towards the pointer; their contents sit at different heights (see style.css).
  if (fine && !calm) {
    const TILT = ".tile, .kind-card, .section-card";
    const MAX = 7;  // degrees
    let current = null;
    const rest = (card) => {
      card.classList.remove("tilting");
      card.style.setProperty("--rx", "0deg");
      card.style.setProperty("--ry", "0deg");
    };
    document.addEventListener("pointermove", (event) => {
      const card = event.target instanceof Element ? event.target.closest(TILT) : null;
      if (current && current !== card) { rest(current); current = null; }
      if (!card) return;
      current = card;
      const box = card.getBoundingClientRect();
      const x = (event.clientX - box.left) / box.width - 0.5;
      const y = (event.clientY - box.top) / box.height - 0.5;
      card.classList.add("tilting");
      card.style.setProperty("--ry", `${(x * 2 * MAX).toFixed(2)}deg`);
      card.style.setProperty("--rx", `${(-y * 2 * MAX).toFixed(2)}deg`);
    }, { passive: true });
    document.addEventListener("pointerleave", () => { if (current) { rest(current); current = null; } });
  }

  // Menu: a glass pill under the current page that follows the pointer along the links.
  const nav = document.querySelector(".nav");
  if (nav) {
    const ink = document.createElement("span");
    ink.className = "nav-ink";
    ink.setAttribute("aria-hidden", "true");
    nav.prepend(ink);
    const place = (link) => {
      if (!link || !link.offsetWidth) { ink.style.opacity = "0"; return; }
      const from = nav.getBoundingClientRect();
      const to = link.getBoundingClientRect();
      ink.style.opacity = "1";
      ink.style.width = `${to.width}px`;
      ink.style.transform = `translateX(${to.left - from.left}px)`;
    };
    const home = () => place(nav.querySelector("a.active"));
    nav.classList.add("inked");
    nav.addEventListener("pointerover", (event) => {
      const link = event.target instanceof Element ? event.target.closest("a") : null;
      if (link) place(link);
    });
    nav.addEventListener("pointerleave", home);
    nav.addEventListener("focusin", (event) => place(event.target.closest("a")));
    nav.addEventListener("focusout", home);
    window.addEventListener("resize", home);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(home);
    home();
  }

  // Page changes know which way they are going, so the transition can match (style.css):
  // along the menu is sideways, into a dataset or a result is a zoom in, back out is a zoom out.
  const DEEP = /^\/(datasets|optimizations)\//;
  const order = nav ? [...nav.querySelectorAll("a")].map((a) => a.pathname) : [];
  const menuIndex = (path) => {
    if (path.startsWith("/datasets/")) return order.indexOf("/");
    if (path.startsWith("/optimizations/")) return order.indexOf("/optimize");
    return order.indexOf(path);
  };
  function direction(from, to) {
    if (DEEP.test(to) && !DEEP.test(from)) return "in";
    if (DEEP.test(from) && !DEEP.test(to) && menuIndex(from) === menuIndex(to)) return "out";
    const a = menuIndex(from), b = menuIndex(to);
    if (a < 0 || b < 0 || a === b) return "";
    return b > a ? "forward" : "back";
  }
  const remember = (to) => {
    try { sessionStorage.setItem("dd-dir", direction(location.pathname, to)); } catch { /* private mode */ }
  };
  document.addEventListener("click", (event) => {
    const link = event.target instanceof Element ? event.target.closest("a[href]") : null;
    if (!link || link.target === "_blank" || link.origin !== location.origin || event.defaultPrevented) return;
    if (link.pathname !== location.pathname) remember(link.pathname);
  }, true);
  // Pages that navigate from script (after an upload or a solve) go one level deeper.
  window.addEventListener("pagehide", () => {
    try { if (sessionStorage.getItem("dd-dir") === null) sessionStorage.setItem("dd-dir", "in"); } catch { /* private mode */ }
  });

  // Tabs slide in from the side the new tab is on.
  document.querySelectorAll(".tabs").forEach((tabs) => {
    const main = document.querySelector("main");
    const index = () => [...tabs.querySelectorAll(".tab")].findIndex((t) => t.classList.contains("active"));
    let last = index();
    new MutationObserver(() => {
      const now = index();
      if (now === last || now < 0) return;
      if (main && main.dataset.dir !== (now < last ? "back" : "forward")) main.dataset.dir = now < last ? "back" : "forward";
      last = now;
    }).observe(tabs, { attributes: true, attributeFilter: ["class"], subtree: true });
  });

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
