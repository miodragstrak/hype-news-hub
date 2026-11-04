import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  envDir: false, envPrefix: [],
  define: { "import.meta.env.VITE_DEMO_MODE": '"false"', "import.meta.env.VITE_API_URL": '""', "import.meta.env.VITE_API_BASE_URL": '""' },
  plugins: [react(), { name: "selfhosted-session-entry", transformIndexHtml: { order: "pre", handler(html) {
    if (!html.includes('src="/src/main.tsx"')) throw Error("Expected frontend entry was not found.");
    return html.replace('src="/src/main.tsx"', 'src="/src/auth/main.tsx"');
  } } }],
  build: { outDir: "dist-selfhosted", sourcemap: false },
});
