"use client";

import Image from "next/image";
import { useState, type ReactNode } from "react";
import "./auth.css";
import AuthBackdrop from "./AuthBackdrop";

export default function AuthSurface({ children }: { children: ReactNode }) {
  const [paused, setPaused] = useState(false);
  return <main className="auth-surface">
    <div className="auth-static-background" aria-hidden="true" />
    <AuthBackdrop paused={paused} />
    <section className="auth-card" aria-label="Acceso a F.A.M.A.">
      <Image src="/F.A.M.A-sinFondoBlanco.png" alt="F.A.M.A." width={180} height={45} unoptimized priority className="auth-logo" />
      {children}
    </section>
    <p className="auth-caption">Framework MLOps · Clasificación acústica</p>
    <button className="auth-motion" type="button" aria-pressed={paused} onClick={() => setPaused((value) => !value)}>
      {paused ? "Reanudar animación" : "Pausar animación"}
    </button>
  </main>;
}
