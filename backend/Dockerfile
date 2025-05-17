FROM python:3.9-slim

RUN apt-get update && apt-get install -y \
    libexpat1 \
    libgdal-dev \
    gcc \
    g++ \
    python3-dev \
    netcat-traditional \
    && rm -rf /var/lib/apt/lists/*
    
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


COPY . .


RUN ls -la /app/ && \
    cat /app/entrypoint.sh && \
    sed -i 's/\r$//' /app/entrypoint.sh && \
    chmod +x /app/entrypoint.sh


CMD sh /app/entrypoint.sh