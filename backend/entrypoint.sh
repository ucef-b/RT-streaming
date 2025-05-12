#!/bin/bash

echo "Waiting for Kafka to be ready..."
while ! nc -z kafka 9092; do
  sleep 5
done
echo "Kafka is ready!"

echo "Waiting for MinIO to be ready..."
while ! nc -z minio 9000; do
  sleep 5
done

echo "MinIO is ready!"

exec uvicorn main:app --host 0.0.0.0 --port 8000