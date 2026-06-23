import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Touchline ’26",
  description: "Live World Cup scores, data, and explainable predictions."
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
