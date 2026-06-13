// Frontend build: transform/minify our JSX into plain JS bundles and vendor
// React locally — so pages need no in-browser Babel and no CDN (strict CSP,
// offline-capable). Run: npm install && npm run build
import { build } from "esbuild";
import { copyFileSync, mkdirSync } from "node:fs";

const DIST = "server/static/dist";
const VENDOR = "server/static/vendor";
mkdirSync(DIST, { recursive: true });
mkdirSync(VENDOR, { recursive: true });

// Vendor React UMD production builds (loaded as window.React / window.ReactDOM).
copyFileSync("node_modules/react/umd/react.production.min.js", `${VENDOR}/react.js`);
copyFileSync("node_modules/react-dom/umd/react-dom.production.min.js", `${VENDOR}/react-dom.js`);

await build({
  entryPoints: [
    { in: "server/static/dashboard.jsx", out: "dashboard" },
    { in: "server/static/playground.jsx", out: "playground" },
    { in: "server/static/auth-app.jsx", out: "auth-app" },
    { in: "Debug_AI/templates/landing/sections-hero.jsx", out: "sections-hero" },
    { in: "Debug_AI/templates/landing/sections-content.jsx", out: "sections-content" },
    { in: "Debug_AI/templates/landing/main.jsx", out: "main" },
  ],
  outdir: DIST,
  bundle: true,
  minify: true,
  format: "iife",
  target: "es2019",
  // Our JSX uses the global React (no imports) — match that at build time.
  jsxFactory: "React.createElement",
  jsxFragment: "React.Fragment",
  loader: { ".jsx": "jsx" },
  logLevel: "info",
});

console.log("frontend build complete →", DIST);
