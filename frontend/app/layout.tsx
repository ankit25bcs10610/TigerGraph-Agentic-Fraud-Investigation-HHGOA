import "./globals.css";
import type { Metadata, Viewport } from "next";

export const metadata: Metadata = { title: "Sentinel Workbench", description: "Graph-grounded fraud investigation for analysts" };
export const viewport: Viewport = { themeColor: [{ media: "(prefers-color-scheme: dark)", color: "#0a0f16" }, { media: "(prefers-color-scheme: light)", color: "#f3f5f9" }] };

// Applies the saved (or system) theme before first paint so the page never flashes.
const themeScript = `try{var t=localStorage.getItem("sentinel.theme");if(t!=="light"&&t!=="dark"){t=matchMedia("(prefers-color-scheme: light)").matches?"light":"dark"}document.documentElement.dataset.theme=t}catch(e){document.documentElement.dataset.theme="dark"}`;

export default function Layout({ children }: { children: React.ReactNode }) {
  return <html lang="en" suppressHydrationWarning>
    <head>
      <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      <link href="https://fonts.googleapis.com" rel="preconnect" />
      <link crossOrigin="" href="https://fonts.gstatic.com" rel="preconnect" />
      <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap" rel="stylesheet" />
    </head>
    <body>{children}</body>
  </html>;
}
