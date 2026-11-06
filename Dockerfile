# 独立全栈部署：同一个镜像提供页面和 API
FROM node:22-slim AS web
WORKDIR /src
COPY web ./web
RUN mkdir -p reportagent && cd web && npm ci && npm run build

FROM python:3.12-slim
ENV PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1 CHROME_PATH=/usr/bin/chromium CHROME_NO_SANDBOX=1
RUN apt-get update && apt-get install -y --no-install-recommends chromium fonts-noto-cjk fonts-arphic-ukai fonts-liberation && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml semantic.real.yaml semantic.demo.yaml ./
COPY reportagent ./reportagent
COPY --from=web /src/reportagent/static ./reportagent/static
RUN pip install .
ENV REPORTAGENT_SEMANTIC=semantic.real.yaml
EXPOSE 8000
CMD ["reportagent", "serve", "--host", "0.0.0.0", "--port", "8000"]
