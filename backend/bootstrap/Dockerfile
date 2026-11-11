# Build ONLY with the source-only context described by source-files.txt.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHON_DOTENV_DISABLED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /bootstrap
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
COPY migrations/ ./migrations/
COPY scripts/ ./scripts/
# The private host context is 0600/0700; only source code becomes readable in the image.
RUN chmod -R a+rX /bootstrap/app /bootstrap/migrations /bootstrap/scripts
USER 10001:10001
ENTRYPOINT ["python", "-B", "-m", "scripts.prepare_zip_manual_database"]
