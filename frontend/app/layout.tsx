import "./globals.css";
import type { Metadata, Viewport } from "next";

export const metadata: Metadata = { title: "Sentinel Workbench", description: "Graph-grounded fraud investigation for analysts" };
export const viewport: Viewport = { themeColor: "#0a0f16", colorScheme: "dark" };

export default function Layout({ children }: { children: React.ReactNode }) {
  return <html lang="en">
    <head>
      <link href="https://fonts.googleapis.com" rel="preconnect" />
      <link crossOrigin="" href="https://fonts.gstatic.com" rel="preconnect" />
      <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap" rel="stylesheet" />
    </head>
    <body>{children}</body>
  </html>;
}
