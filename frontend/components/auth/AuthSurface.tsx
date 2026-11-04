"use client";

import Image from "next/image";
import { type ReactNode } from "react";
import "./auth.css";

export default function AuthSurface({ children }: { children: ReactNode }) {
  return <main className="auth-surface">
    <div className="auth-static-background" aria-hidden="true" />
    <section className="auth-card" aria-label="Acceso a F.A.M.A.">
      <Image src="/F.A.M.A-sinFondoBlanco.png" alt="F.A.M.A." width={180} height={45} unoptimized priority className="auth-logo" />
      {children}
    </section>
    <p className="auth-caption">Framework MLOps · Clasificación acústica</p>
  </main>;
}
