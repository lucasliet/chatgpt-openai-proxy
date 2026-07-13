# syntax=docker/dockerfile:1

FROM oven/bun:1 AS build
WORKDIR /app

COPY package.json bun.lockb* ./
RUN bun install --frozen-lockfile

COPY tsconfig.json ./
COPY src ./src
COPY tests ./tests

RUN bun run typecheck
RUN bun test

FROM oven/bun:1-slim AS runtime
WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000
ENV OAUTH_CALLBACK_PORT=1455

COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/package.json tsconfig.json ./
COPY --from=build /app/src ./src

EXPOSE 3000 1455
VOLUME ["/root/.config/chatgpt-proxy"]

CMD ["bun", "run", "src/index.ts"]
