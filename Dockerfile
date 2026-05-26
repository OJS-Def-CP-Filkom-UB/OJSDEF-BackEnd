FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev libcairo2 libpango-1.0-0 libpangocairo-1.0-0 \
    libpangoft2-1.0-0 libharfbuzz0b libgdk-pixbuf-2.0-0 \
    libffi-dev shared-mime-info \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
