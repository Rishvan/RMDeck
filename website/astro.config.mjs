import { defineConfig } from "astro/config";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  site: "https://rmdex.rishvan.com",
  vite: {
    plugins: [tailwindcss()],
  },
});
