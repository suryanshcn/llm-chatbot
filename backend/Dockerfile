# ---- build stage: install deps into a venv
FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1
WORKDIR /w
RUN python -m venv /opt/venv
COPY requirements.txt .
RUN /opt/venv/bin/pip install -r requirements.txt

# ---- runtime stage
FROM python:3.12-slim
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN useradd -m app && mkdir /data && chown app /data
WORKDIR /srv
COPY --from=build /opt/venv /opt/venv
COPY app ./app
USER app
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os;urllib.request.urlopen('http://localhost:'+os.getenv('PORT','8000')+'/health')"
CMD ["sh", "-c", "uvicorn app.main:build_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]
