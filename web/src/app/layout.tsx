import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ControlPlane.ai — Runtime Governance",
  description: "Evidence-aware runtime governance middleware for enterprise AI",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
