import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";

// Emit the checked-in demo inputs without copying or inventing their values.
const demoFiles = [
  {
    route: "/demo-portfolio.json",
    path: "../data/portfolio.json",
    type: "application/json",
  },
  {
    route: "/demo-persona.md",
    path: "../data/PERSONA.md",
    type: "text/markdown",
  },
].map((file) => ({
  ...file,
  source: readFileSync(new URL(file.path, import.meta.url), "utf8"),
}));
export default defineConfig({
  plugins: [
    react(),
    {
      name: "council-demo-inputs",
      configureServer(server) {
        server.middlewares.use((req, res, next) => {
          const file = demoFiles.find(
            (file) => file.route === req.url?.split("?")[0],
          );
          if (!file) return next();
          res.setHeader("Content-Type", file.type);
          res.end(file.source);
        });
      },
      generateBundle() {
        for (const file of demoFiles)
          this.emitFile({
            type: "asset",
            fileName: file.route.slice(1),
            source: file.source,
          });
      },
    },
  ],
  server: {
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: true } },
  },
});
