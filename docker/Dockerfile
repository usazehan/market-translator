FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install -U pip && pip install -e .

COPY src ./src
COPY data ./data

EXPOSE 8000
CMD ["python","-m","uvicorn","src.app.main:app","--host","0.0.0.0","--port","8000"]
