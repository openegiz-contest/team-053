# One image for the four Sekisovskoye services (setup, simulator, advisor, Stand).
# Build context: team/. Compose builds it once, through the sekis-setup service.

# Stage 1: pick the application directories that exist. Later work packages add
# stand/ and more of sekis/ and tests/, and the image must build before and after.
FROM python:3.12-slim AS src
WORKDIR /src
COPY . /src/
RUN mkdir /out \
 && for d in sekis model stand tests; do if [ -d "$d" ]; then cp -r "$d" /out/; fi; done \
 && find /out -type d -name __pycache__ -prune -exec rm -rf {} + \
 && chmod -R a+rX /out

# Stage 2: the runtime image. The dependency layer comes first so that code
# edits do not reinstall packages.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --from=src /out/ /app/
USER nobody
CMD ["python", "-m", "sekis.setup_twins"]
