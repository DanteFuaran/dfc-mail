FROM python:3.12-alpine AS builder

WORKDIR /opt/dfc-mail

COPY requirements.txt ./

RUN pip install --no-cache-dir --prefix=/install -r requirements.txt \
    && find /install -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

FROM python:3.12-alpine AS final

WORKDIR /opt/dfc-mail

ARG BUILD_TIME
ARG BUILD_BRANCH
ARG BUILD_COMMIT
ARG BUILD_TAG

ENV BUILD_TIME=${BUILD_TIME}
ENV BUILD_BRANCH=${BUILD_BRANCH}
ENV BUILD_COMMIT=${BUILD_COMMIT}
ENV BUILD_TAG=${BUILD_TAG}

RUN apk add --no-cache postgresql-client

COPY --from=builder /install /usr/local

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/opt/dfc-mail

COPY ./src ./src
COPY ./version ./version
COPY ./scripts/docker-entrypoint.sh ./scripts/docker-entrypoint.sh

RUN chmod +x ./scripts/docker-entrypoint.sh

CMD ["./scripts/docker-entrypoint.sh"]
