FROM node:22-alpine AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY apps/web/package*.json ./
RUN npm ci
COPY apps/web/ ./
# The voice call connects its WebSocket straight to the gateway (route
# handlers cannot proxy WebSockets); empty means ws(s)://<page host>:8000.
ARG NEXT_PUBLIC_VOICE_URL=""
ENV NEXT_PUBLIC_VOICE_URL=$NEXT_PUBLIC_VOICE_URL
RUN npm run build

FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
COPY --from=build --chown=node:node /app/public ./public
USER node
EXPOSE 3000
CMD ["node", "server.js"]
