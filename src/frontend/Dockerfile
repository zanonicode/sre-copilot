FROM node:20-slim AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
# Build needs devDependencies (typescript, tailwindcss, @types/*) for Next.js
# to resolve tsconfig path aliases and compile TS. Standalone output excludes
# node_modules from the runner image, so dev deps don't bloat the final image.
RUN npm ci


FROM node:20-slim AS builder
ARG NEXT_PUBLIC_API_URL=https://api.sre-copilot.localtest.me
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1 \
    NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
RUN npm run build


FROM node:20-slim AS runner
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME="0.0.0.0"

RUN groupadd --gid 1001 nodejs && \
    useradd --uid 1001 --gid nodejs --no-create-home nextjs

WORKDIR /app
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
    CMD node -e "require('http').get('http://localhost:3000/', r => process.exit(r.statusCode === 200 ? 0 : 1))"

CMD ["node", "server.js"]
