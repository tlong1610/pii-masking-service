FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN useradd --create-home --uid 10001 app

# Service che PII và tool xuất dữ liệu. Không chứa mockup hay thư viện sinh dữ liệu giả.
FROM base AS service
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY piimask piimask
COPY api api
COPY tool tool
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
    CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://localhost:8000/health', timeout=2)"]
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Sinh và nạp mockup.
FROM base AS mockup
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY piimask piimask
COPY mockup mockup
USER app
