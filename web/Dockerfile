# syntax=docker/dockerfile:1.7

FROM docker.io/library/node:24-alpine AS dependencies
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM docker.io/library/node:24-alpine AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
ARG API_URL=http://backend:8000
ENV API_URL=$API_URL
COPY --from=dependencies /app/node_modules ./node_modules
COPY . .
RUN npm run lint && npm run build

FROM docker.io/library/node:24-alpine AS runtime
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000 \
    API_URL=http://backend:8000

RUN addgroup --system --gid 10001 controlplane \
    && adduser --system --uid 10001 --ingroup controlplane controlplane

COPY --from=builder --chown=controlplane:controlplane /app/.next/standalone ./
COPY --from=builder --chown=controlplane:controlplane /app/.next/static ./.next/static

USER 10001:10001

EXPOSE 3000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
  CMD node -e "fetch('http://127.0.0.1:3000').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"

CMD ["node", "server.js"]

