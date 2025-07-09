# RT-Streaming: UAV Agricultural Vision Streaming Platform

## Project Structure

```
.
├── backend/           # FastAPI backend for streaming, MinIO, Kafka integration
│   ├── Dockerfile
│   ├── entrypoint.sh
│   ├── main.py
│   └── requirements.txt
├── frontend/          # React frontend for visualization
│   ├── Dockerfile
│   ├── package.json
│   ├── public/
│   └── src/
├── uav-producer/      # UAV producer service (model inference, MinIO/Kafka upload)
│   ├── Dockerfile
│   ├── entrypoint.sh
│   ├── model.tflite
│   ├── producer.py
│   └── requirements.txt
├── data/              # (You mount this for UAV input/output)
├── create_yml.py      # Script to generate docker-compose files with multiple UAVs
├── docker-compose.yml # Main Compose file (edit or generate as needed)
├── ...
```

## Folder Descriptions

- **backend/**: FastAPI app that consumes Kafka messages, serves WebSocket/API for frontend, and manages MinIO bucket.
- **frontend/**: React app for real-time visualization of UAV images, predictions, and logs.
- **uav-producer/**: Simulates UAVs. Reads images, runs ML inference, uploads to MinIO, and sends Kafka messages.
- **data/**: data from agriculture-vision-2021 (raw).
- **create_yml.py**: Python script to generate a `docker-compose` file with any number of UAV producers.

---

## Dataset

You can access the datasets through the following link:  
🔗 [https://www.agriculture-vision.com/agriculture-vision-2021/dataset-2021](https://www.agriculture-vision.com/agriculture-vision-2021/dataset-2021)

---

## Quick Start Guide

### 1. Generate a Docker Compose File with Multiple UAV Producers

To create a Compose file with multiple UAV producers (e.g., 5 UAVs):

```sh
python create_yml.py uav-producer 5 docker-compose.yml docker-compose.multi.yml
```

- This will create `docker-compose.multi.yml` with services: `uav-producer-1`, `uav-producer-2`, ..., `uav-producer-5`.
- Each producer gets a unique `UAV_ID` (e.g., "01", "02", ...).

### 2. Prepare Data

- Place your UAV input data (GeoTIFF bands, etc.) in the `data/` directory.
- Each producer expects its files under `/data/<UAV_ID>` inside the container.

### 3. Build and Launch the Stack

To launch the full system (backend, frontend, MinIO, Kafka, and all producers):

```sh
docker compose -f docker-compose.multi.yml up --build
```

- The first launch may take a few minutes to build images and initialize services.
- The backend will be available at [http://localhost:8000](http://localhost:8000)
- The frontend will be available at [http://localhost:3000](http://localhost:3000)
- MinIO console: [http://localhost:9001](http://localhost:9001) (login: `minioadmin`/`minioadmin`)
- Kafka UI: [http://localhost:8080](http://localhost:8080)

### 4. Stopping the System

To stop and remove all containers:

```sh
docker compose -f docker-compose.multi.yml down
```

---

## Notes

- The MinIO bucket `uav-images` is created and made public automatically by the `minio-init` service.
- Each UAV producer uploads images and predictions to MinIO and sends metadata to Kafka.
- The backend consumes Kafka messages and serves them to the frontend via WebSocket.
- The frontend displays real-time UAV imagery, predictions, and logs.

---

## Customization

- To change the number of UAVs, rerun `create_yml.py` with a different count and restart Docker Compose.
- To use the default single-producer setup, you can use the provided [`docker-compose.yml`](docker-compose.yml) directly.

---

## Troubleshooting

- Ensure ports 8000, 3000, 9000, 9001, and 8080 are free.
- If you change the number of UAVs, always regenerate the compose file and restart the stack.
- Check logs with `docker compose logs -f`.
