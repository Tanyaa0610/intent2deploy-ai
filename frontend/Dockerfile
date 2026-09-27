FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
# Vite inlines VITE_* variables at BUILD time, not at container runtime — a
# static `serve` process has no way to read an environment variable set on
# `docker run`/compose later. This must be a build ARG, not a runtime env
# var. Defaults to the host-published backend port, since the browser
# (which actually executes this bundle) runs outside Docker networking and
# cannot resolve a container hostname like `backend`.
ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM node:20-slim
WORKDIR /app
RUN npm install -g serve
COPY --chown=node:node --from=build /app/dist ./dist
EXPOSE 5173
USER node
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD node -e "fetch('http://localhost:5173/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["serve", "-s", "dist", "-l", "5173"]
