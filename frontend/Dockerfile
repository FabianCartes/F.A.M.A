# ==============================================================================
# Dockerfile Frontend F.A.M.A. (Next.js Multi-stage Standalone)
# ==============================================================================

# ------------------------------------------------------------------------------
# Fase 1: Instalación de dependencias (deps)
# ------------------------------------------------------------------------------
FROM node:20-alpine AS deps
RUN apk add --no-cache libc6-compat
WORKDIR /app

# Copiar manifiestos de paquetes
COPY package.json package-lock.json ./
RUN npm ci

# ------------------------------------------------------------------------------
# Fase 2: Compilación de producción (builder)
# ------------------------------------------------------------------------------
FROM node:20-alpine AS builder
WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Argumentos y variables de compilación
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
ENV NEXT_TELEMETRY_DISABLED=1

# Generación del bundle standalone de Next.js
RUN npm run build

# ------------------------------------------------------------------------------
# Fase 3: Ejecutable de producción mínimo (runner)
# ------------------------------------------------------------------------------
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

# Crear usuario y grupo de sistema sin privilegios de root
RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# Copiar activos estáticos públicos
COPY --from=builder /app/public ./public

# Crear directorio de caché con permisos asignados al usuario nextjs
RUN mkdir .next && chown nextjs:nodejs .next

# Copiar el build standalone y archivos estáticos generados
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

# Verificación de salud con wget (integrado en BusyBox de Alpine)
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD wget -qO- http://localhost:3000/ || exit 1

CMD ["node", "server.js"]
