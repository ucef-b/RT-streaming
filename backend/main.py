# from fastapi import FastAPI, WebSocket
# from aiokafka import AIOKafkaConsumer
# import asyncio
# import json
# import os
# from fastapi.middleware.cors import CORSMiddleware
# import logging

# logging.basicConfig(level=logging.INFO)
# logger = logging.getLogger(__name__)

# KAFKA_TOPIC = "uav.01.images"

# KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

# app = FastAPI()

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],  
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# websocket_connections = []

# @app.websocket("/ws")
# async def websocket_endpoint(websocket: WebSocket):
#     await websocket.accept()
#     websocket_connections.append(websocket)
    
#     try:
#         while True:
#             await websocket.receive_text()
#     except:
#         websocket_connections.remove(websocket)

# async def consume_kafka():
#     retries = 5
#     retry_delay = 5
    
#     for attempt in range(retries):
#         try:
#             consumer = AIOKafkaConsumer(
#                 "uav.01.images",
#                 bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
#                 group_id="dashboard-group",
#                 auto_offset_reset='earliest',
#                 enable_auto_commit=True,
#                 max_poll_interval_ms=300000,
#                 session_timeout_ms=45000,
#                 heartbeat_interval_ms=15000
#             )
            
#             await consumer.start()
#             logger.info("Kafka Consumer started.")
            
#             try:
#                 async for msg in consumer:
#                     data = json.loads(msg.value)
#                     for conn in websocket_connections:
#                         await conn.send_text(json.dumps(data))
#                     print(f"Received message: {data}")
#             except Exception as e:
#                 print(f"Error processing message: {str(e)}")
#             finally:
#                 await consumer.stop()
                
#         except Exception as e:
#             print(f"Connection attempt {attempt + 1} failed: {str(e)}")
#             if attempt < retries - 1:
#                 print(f"Retrying in {retry_delay} seconds...")
#                 await asyncio.sleep(retry_delay)
#             else:
#                 print("Max retries reached. Failed to connect to Kafka.")
#                 raise

# @app.on_event("startup")
# async def startup_event():
#     asyncio.create_task(consume_kafka())



import asyncio
import uvicorn

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from aiokafka import AIOKafkaConsumer
import json
import logging
from contextlib import asynccontextmanager
from typing import Set
import os
from fastapi.responses import StreamingResponse
import io
from minio import Minio
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Use environment variable with fallback to localhost:9092
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:29092")
KAFKA_TOPIC = ["uav.01.images","uav.02.images", "uav.03.images", "uav.04.images", "uav.05.images", "uav.06.images", "uav.07.images", "uav.08.images", "uav.09.images", "uav.10.images"]
KAFKA_CONSUMER_GROUP = "image_display_group_v2" 

clients: Set[WebSocket] = set()

async def consume_messages():
    logger.info(f"Connecting to Kafka at {KAFKA_BOOTSTRAP_SERVERS}")
    consumer = AIOKafkaConsumer(
        *KAFKA_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        group_id=KAFKA_CONSUMER_GROUP,
        auto_offset_reset='earliest',
        value_deserializer=lambda m: json.loads(m.decode('utf-8')),
    )
    await consumer.start()
    logger.info("Kafka Consumer started.")
    
    try:
        async for msg in consumer:
            await broadcast_message(msg.value)
    except Exception as e:
        logger.error(f"Error consuming messages: {str(e)}")
    finally:
        await consumer.stop()

async def broadcast_message(data):
    if not clients:
        logger.warning("No WebSocket clients connected. Message not broadcasted.")
        return
        
    message = json.dumps(data)
    logger.info(f"Broadcasting message to {len(clients)} clients")
    
    for client in clients:
        try:
            await client.send_text(message)
        except Exception as e:
            logger.error(f"Error sending message to client: {str(e)}")


kafka_task = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global kafka_task
    logger.info("Starting up application...")
    kafka_task = asyncio.create_task(consume_messages())
    yield
    logger.info("Shutting down application...")
    if kafka_task:
        kafka_task.cancel()
        try:
            await kafka_task
        except asyncio.CancelledError:
            logger.info("Kafka task successfully cancelled.")
    logger.info(f"Closing {len(clients)} WebSocket connections...")
    await asyncio.gather(
        *[client.close(code=1000, reason="Server shutting down") for client in clients],
        return_exceptions=True
    )
    clients.clear()
    logger.info("WebSocket connections closed.")

app = FastAPI(lifespan=lifespan)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    clients.add(websocket)
    logger.info(f"Client connected: {websocket.client}. Total clients: {len(clients)}")
    
    # Send initial setup message
    setup_message = json.dumps({
        "type": "setup",
        "tileSize": 512  # Match the tile size from producer
    })
    await websocket.send_text(setup_message)
    
    try:
        while True:
            msg = await websocket.receive_text()
            # Handle any client messages if needed
    except WebSocketDisconnect:
        logger.info(f"Client disconnected: {websocket.client}")
    finally:
        clients.discard(websocket)

async def broadcast_patch(msg):
    message_to_send = json.dumps({
        "type": "patch",
        "imageId": msg['image_id'],
        "metadata": msg['metadata'],
        "patchMetadata": msg['patch_metadata'],
        "patchData": msg['patch_data'],
        "nirData": msg.get('nir_data')  # Include NIR data if available
    })
    
    results = await asyncio.gather(
        *[client.send_text(message_to_send) for client in clients],
        return_exceptions=True
    )


@app.get("/")
async def read_root():
    return {"message": "Image Streaming Service v2 is running. Connect via WebSocket at /ws"}

# MinIO configuration
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = "uav-images"

# Initialize MinIO client
minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False  # Set to True if using HTTPS
)

# Create bucket if it doesn't exist
try:
    if not minio_client.bucket_exists(MINIO_BUCKET):
        minio_client.make_bucket(MINIO_BUCKET)
    
    # Set bucket policy to public - this is the key change
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"AWS": ["*"]},
                "Action": ["s3:GetObject", "s3:GetBucketLocation"],
                "Resource": [
                    f"arn:aws:s3:::{MINIO_BUCKET}/*",
                    f"arn:aws:s3:::{MINIO_BUCKET}"
                ]
            }
        ]
    }
    minio_client.set_bucket_policy(MINIO_BUCKET, json.dumps(policy))
    logger.info(f"Successfully set bucket policy for {MINIO_BUCKET}")
except Exception as e:
    logger.error(f"Error initializing MinIO bucket: {str(e)}")

@app.get("/images/{uav_id}/{image_name}")
async def get_image(uav_id: str, image_name: str):
    """Serve images from MinIO"""
    try:
        # Construct the object path
        object_path = f"{uav_id}/{image_name}"
        
        # Get the object from MinIO
        response = minio_client.get_object(MINIO_BUCKET, object_path)
        
        # Read the data
        image_data = response.read()
        
        # Determine content type based on file extension
        content_type = "image/jpeg"  # Default
        if image_name.endswith(".png"):
            content_type = "image/png"
        
        # Return the image as a streaming response
        return StreamingResponse(
            io.BytesIO(image_data),
            media_type=content_type
        )
    except Exception as e:
        logger.error(f"Error retrieving image {object_path}: {str(e)}")
        raise HTTPException(status_code=404, detail=f"Image not found: {str(e)}")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")