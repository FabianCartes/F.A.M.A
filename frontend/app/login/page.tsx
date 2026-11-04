"use client";

import SessionBoundary from "@/components/auth/SessionBoundary";

export default function LoginPage() {
  return <SessionBoundary mode="login" />;
}
