# Lotto worker image for Azure Container Apps Jobs: azure/runner.py and azure/blobsync.py, the worker code (workers/,
# analysis/ under /app/repo), poppler-utils, Node, Playwright's headless Chromium and the Static Web Apps CLI (swa).
# The image carries the code and no data: runner.py pulls the registers from the Azure Blob container lotto-data into
# /app/repo/data at the start of a run and uploads the changed files at the end. There is no git in the image.
# Built by .github/workflows/azure-deploy.yml (context = repo root), rebuilt whenever azure/, workers/ or analysis/
# change. Rebuilt from the image history; the Node major version is a best guess (22) as history only records that
# /usr/local was copied from a Node image.
FROM node:22-bookworm-slim AS node

FROM python:3.12-slim-bookworm
COPY --from=node /usr/local/ /usr/local/
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /opt/playwright \
    && npm install --prefix /opt/playwright playwright@1.63.0 @azure/static-web-apps-cli@2.0.2 \
    && PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
       /opt/playwright/node_modules/.bin/playwright install --with-deps --only-shell chromium \
    && npm cache clean --force \
    && rm -rf /var/lib/apt/lists/* \
    && chmod -R a+rX /opt/ms-playwright \
    && useradd --create-home --uid 10001 worker \
    && mkdir -p /app/repo/data \
    && chown -R 10001:10001 /app/repo
COPY --chown=10001:10001 azure/runner.py azure/blobsync.py /app/
COPY --chown=10001:10001 workers/ /app/repo/workers/
COPY --chown=10001:10001 analysis/ /app/repo/analysis/
ENV NODE_PATH=/opt/playwright/node_modules PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright PYTHONUNBUFFERED=1 LOTTO_REPO_ROOT=/app/repo
USER worker
ENTRYPOINT ["python3", "/app/runner.py"]
