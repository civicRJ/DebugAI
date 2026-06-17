/* DebugAI landing — boot. Waits for the DS bundle + section globals. */
(function () {
  function ready() {
    return (
      window.DesignSystem_90c6f1 &&
      window.DebugAINav && window.DebugAIHero &&
      window.DebugAIHowItWorks && window.DebugAIFeatures &&
      window.DebugAIUseCases && window.DebugAICTA && window.DebugAIFooter
    );
  }

  function App() {
    return (
      <div className="page">
        {React.createElement(window.DebugAINav)}
        {React.createElement(window.DebugAIHero)}
        <div className="shell"><div className="divider" /></div>
        {React.createElement(window.DebugAIHowItWorks)}
        {React.createElement(window.DebugAIFeatures)}
        {React.createElement(window.DebugAIUseCases)}
        {React.createElement(window.DebugAICTA)}
        {React.createElement(window.DebugAIFooter)}
      </div>
    );
  }

  function mountRevealObserver() {
    if (!("IntersectionObserver" in window)) {
      document.querySelectorAll(".reveal").forEach((el) => el.classList.add("in"));
      return;
    }
    const io = new IntersectionObserver(
      (entries) => entries.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } }),
      { threshold: 0.12, rootMargin: "0px 0px -8% 0px" }
    );
    document.querySelectorAll(".reveal").forEach((el) => io.observe(el));
  }

  function boot() {
    if (!ready()) return setTimeout(boot, 30);
    const root = ReactDOM.createRoot(document.getElementById("root"));
    root.render(React.createElement(App));
    requestAnimationFrame(() => setTimeout(() => {
      mountRevealObserver();
      if (window.location.hash) {
        const target = document.querySelector(window.location.hash);
        if (target) target.scrollIntoView({ block: "start" });
      }
    }, 60));
  }
  boot();
})();
