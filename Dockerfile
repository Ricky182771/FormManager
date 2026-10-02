# syntax=docker/dockerfile:1

FROM python:3.12.15-slim-bookworm AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

FROM python:3.12.15-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    FORMS_DIR=/data/forms
RUN groupadd --system --gid 10001 formmanager \
    && useradd --system --uid 10001 --gid formmanager --no-create-home --home-dir /nonexistent \
       --shell /usr/sbin/nologin formmanager \
    && mkdir -p /data/forms \
    && chown formmanager:formmanager /data/forms \
    && chmod 0750 /data/forms
WORKDIR /srv
COPY --from=builder /opt/venv /opt/venv
COPY --chown=root:root alembic.ini ./
COPY --chown=root:root alembic ./alembic
COPY --chown=root:root app ./app
COPY --chown=root:root docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 0755 /usr/local/bin/entrypoint.sh && find /srv -type d -exec chmod 0755 {} + \
    && find /srv -type f -exec chmod 0644 {} +
USER formmanager:formmanager
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"]
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["serve"]
