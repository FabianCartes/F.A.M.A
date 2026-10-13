import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import "./globals.css";

const montserrat = localFont({
  src: "./fonts/Montserrat-latin-variable.woff2",
  weight: "500 800",
  style: "normal",
  variable: "--font-montserrat",
  display: "swap",
});

const openSans = localFont({
  src: "./fonts/OpenSans-latin-variable.woff2",
  weight: "400 600",
  style: "normal",
  variable: "--font-open-sans",
  display: "swap",
});

export const metadata: Metadata = {
  title: "F.A.M.A. | Clasificación Bioacústica",
  description: "Framework MLOps Híbrido para Monitoreo y Análisis de Fauna Acústica",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#030712",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="es"
      className={`${montserrat.variable} ${openSans.variable} dark`}
    >
      <body className="min-h-screen bg-gray-950 text-white antialiased">
        {children}
      </body>
    </html>
  );
}
