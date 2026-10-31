# Lotto worker image for Azure Container Apps Jobs: azure/runner.py plus git, poppler-utils, Node and Playwright's
# headless Chromium. It holds no repo code; runner.py clones main at run time. Built by .github/workflows/azure-deploy.yml
# (context = repo root). Rebuilt from the image history; the Node major version is a best guess (22) as history
# only records that /usr/local was copied from a Node image.
FROM node:22-bookworm-slim AS node

FROM python:3.12-slim-bookworm
COPY --from=node /usr/local/ /usr/local/
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends git poppler-utils \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /opt/playwright \
    && npm install --prefix /opt/playwright playwright@1.63.0 \
    && PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
       /opt/playwright/node_modules/.bin/playwright install --with-deps --only-shell chromium \
    && npm cache clean --force \
    && rm -rf /var/lib/apt/lists/* \
    && chmod -R a+rX /opt/ms-playwright \
    && useradd --create-home --uid 10001 worker
COPY --chown=10001:10001 azure/runner.py /app/runner.py
ENV NODE_PATH=/opt/playwright/node_modules PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright PYTHONUNBUFFERED=1
USER worker
ENTRYPOINT ["python3", "/app/runner.py"]
