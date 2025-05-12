#!/bin/bash
set -e

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

# Print environment variables for debugging
echo "Environment variables:"
env | grep -E 'UAV_ID|KAFKA|MINIO'

echo "All services ready! Starting producer..."
exec python producer.py