// Bundle the web app into web/dist. Usage: `npm run build` (or `node build.cjs --watch`).
const esbuild = require("esbuild");
const fs = require("node:fs");
const path = require("node:path");

const dist = path.join(__dirname, "dist");
fs.rmSync(dist, { recursive: true, force: true });
fs.mkdirSync(dist, { recursive: true });
// index.html, the stylesheet and everything under public/ (fonts, the landing demo) go to dist/ as they are.
const copyStatic = () => {
  fs.copyFileSync(path.join(__dirname, "index.html"), path.join(dist, "index.html"));
  fs.copyFileSync(path.join(__dirname, "src", "styles.css"), path.join(dist, "styles.css"));
  const pub = path.join(__dirname, "public");
  if (fs.existsSync(pub)) fs.cpSync(pub, dist, { recursive: true });
};

const options = {
  entryPoints: [path.join(__dirname, "src", "main.tsx")],
  bundle: true,
  outfile: path.join(dist, "app.js"),
  minify: true,
  sourcemap: true,
  target: ["es2020"],
  jsx: "automatic",
  define: { "process.env.NODE_ENV": '"production"' },
  nodePaths: (process.env.NODE_PATH || "").split(path.delimiter).filter(Boolean),
  logLevel: "info",
};

if (process.argv.includes("--watch")) {
  esbuild.context(options).then((ctx) => { copyStatic(); return ctx.watch(); });
} else {
  esbuild.build(options).then(copyStatic).catch(() => process.exit(1));
}
