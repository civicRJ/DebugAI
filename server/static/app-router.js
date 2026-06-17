(function () {
  if (window.DebugAIAppRouter) return;

  const ROUTES = new Set(["/account", "/admin", "/dashboard", "/docs", "/playground"]);
  const SHARED_SCRIPTS = new Set([
    "/static/vendor/react.js",
    "/static/vendor/react-dom.js",
    "/ds/_ds_bundle.js",
    "/static/app-router.js",
  ]);
  const cache = new Map();
  let navigating = false;

  function routeKey(url) {
    return url.pathname;
  }

  function isSoftRoute(url) {
    return url.origin === location.origin && ROUTES.has(routeKey(url));
  }

  function shouldHandleClick(event, anchor) {
    if (!anchor || event.defaultPrevented) return false;
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return false;
    if (anchor.target && anchor.target !== "_self") return false;
    if (anchor.hasAttribute("download")) return false;
    const url = new URL(anchor.href, location.href);
    if (!isSoftRoute(url)) return false;
    return url.href !== location.href || url.hash;
  }

  function sameAsset(node, candidate) {
    if (node.tagName !== candidate.tagName) return false;
    if (candidate.tagName === "LINK") {
      return node.rel === candidate.rel && node.href === candidate.href;
    }
    if (candidate.tagName === "STYLE") {
      return node.textContent === candidate.textContent;
    }
    return false;
  }

  function mergeHead(nextDoc) {
    document.title = nextDoc.title || document.title;
    nextDoc.head.querySelectorAll('link[rel="stylesheet"], style').forEach(candidate => {
      const exists = [...document.head.children].some(node => sameAsset(node, candidate));
      if (!exists) document.head.appendChild(candidate.cloneNode(true));
    });
  }

  function scriptSrc(script) {
    if (!script.src) return "";
    return new URL(script.src, location.origin).pathname;
  }

  function loadScript(script) {
    return new Promise((resolve, reject) => {
      const src = scriptSrc(script);
      if (src && SHARED_SCRIPTS.has(src) && document.querySelector(`script[src="${src}"]`)) {
        resolve();
        return;
      }
      const fresh = document.createElement("script");
      [...script.attributes].forEach(attr => fresh.setAttribute(attr.name, attr.value));
      fresh.async = false;
      fresh.onload = resolve;
      fresh.onerror = reject;
      fresh.text = script.textContent || "";
      document.body.appendChild(fresh);
      if (!fresh.src) resolve();
    });
  }

  async function runScripts(nextDoc) {
    const scripts = [
      ...nextDoc.head.querySelectorAll("script"),
      ...nextDoc.body.querySelectorAll("script"),
    ];
    for (const script of scripts) {
      await loadScript(script);
    }
  }

  async function fetchPage(url) {
    const cached = cache.get(url.href);
    if (cached) return cached;
    const response = await fetch(url.href, {
      credentials: "same-origin",
      headers: { "X-DebugAI-Soft-Navigation": "1" },
    });
    if (response.redirected && new URL(response.url).pathname === "/login") {
      window.location.href = response.url;
      return null;
    }
    if (!response.ok) throw new Error("navigation failed");
    const html = await response.text();
    cache.set(url.href, html);
    return html;
  }

  async function navigate(href, options) {
    const url = new URL(href, location.href);
    if (!isSoftRoute(url) || navigating) {
      window.location.href = url.href;
      return;
    }
    navigating = true;
    document.documentElement.dataset.softNavigating = "true";
    try {
      const html = await fetchPage(url);
      if (!html) return;
      const nextDoc = new DOMParser().parseFromString(html, "text/html");
      if (window.__debugaiUnmountRoute) {
        try { window.__debugaiUnmountRoute(); } catch (_) {}
        window.__debugaiUnmountRoute = null;
      }
      mergeHead(nextDoc);
      document.body.innerHTML = nextDoc.body.innerHTML;
      if (!options || !options.replace) history.pushState({}, "", url.href);
      await runScripts(nextDoc);
      window.scrollTo(0, 0);
    } catch (_) {
      window.location.href = url.href;
    } finally {
      navigating = false;
      delete document.documentElement.dataset.softNavigating;
    }
  }

  function prefetch(href) {
    const url = new URL(href, location.href);
    if (!isSoftRoute(url) || cache.has(url.href)) return;
    fetchPage(url).catch(() => {});
  }

  document.addEventListener("click", event => {
    const anchor = event.target.closest && event.target.closest("a[href]");
    if (!shouldHandleClick(event, anchor)) return;
    event.preventDefault();
    navigate(anchor.href);
  });

  document.addEventListener("pointerover", event => {
    const anchor = event.target.closest && event.target.closest("a[href]");
    if (anchor) prefetch(anchor.href);
  });

  window.addEventListener("popstate", () => navigate(location.href, { replace: true }));

  window.DebugAIAppRouter = { navigate, prefetch };
})();
