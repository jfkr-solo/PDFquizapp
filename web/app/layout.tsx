import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = { title: "問題集クイズ", description: "PDF問題集から作ったクイズで学習する" };
export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ja">
      <body>
        <main className="wrap">{children}</main>
      </body>
    </html>
  );
}
