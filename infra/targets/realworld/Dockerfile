# Dependency provisioning only. Captured application code is never copied here.
FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df
RUN apt-get update && apt-get install -y --no-install-recommends libpq-dev gcc libc6-dev curl \
    && rm -rf /var/lib/apt/lists/*
ARG REQUIREMENTS=requirements.lock
COPY ${REQUIREMENTS} /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 65534:65534
ENTRYPOINT ["python"]
