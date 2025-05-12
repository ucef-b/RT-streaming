import os
import time
import json 
import rasterio
import numpy as np
from kafka import KafkaProducer
from minio import Minio
from io import BytesIO
from PIL import Image
import warnings
from rasterio.errors import NotGeoreferencedWarning
warnings.filterwarnings("ignore", category=NotGeoreferencedWarning)

# Configuration
UAV_ID = os.getenv("UAV_ID")
MISSION_PATH = f"/data/{UAV_ID}" # 
KAFKA_TOPIC = f"uav.{UAV_ID}.images" # depence on uav-producer are runing in the same container


def calculate_ndvi(red_band, nir_band):
    red = red_band.astype(np.float32)
    nir = nir_band.astype(np.float32)
    ndvi = (nir - red) / (nir + red + 1e-8)
    
    ndvi_normalized = ((ndvi + 1) * 127.5).astype(np.uint8)
    
    rgb_ndvi = np.zeros((ndvi.shape[0], ndvi.shape[1], 3), dtype=np.uint8)
    
    rgb_ndvi[:, :, 0] = 255 - ndvi_normalized  
    rgb_ndvi[:, :, 1] = ndvi_normalized        
    rgb_ndvi[:, :, 2] = 0                      
    
    return rgb_ndvi

def process_image(base_name, minio_client):
    bands = {}
    for band in ['red', 'green', 'blue', 'nir']:
        tif_path = f"{MISSION_PATH}/{base_name}_{band}_high.tif"
        if not os.path.exists(tif_path):
            raise FileNotFoundError(f"Missing {band} band file: {tif_path}")

        with rasterio.open(tif_path) as src:
            bands[band] = src.read(1)
            
    # Create RGB JPEG
    rgb = np.dstack([bands['red'], bands['green'], bands['blue']])
    rgb_normalized = (rgb / rgb.max() * 255).astype(np.uint8)
    rgb_img = Image.fromarray(rgb_normalized)
    
    # Create colored NDVI
    ndvi_colored = calculate_ndvi(bands['red'], bands['nir'])
    ndvi_img = Image.fromarray(ndvi_colored)
    
    # Upload to MinIO
    timestamp = int(time.time())
    jpeg_bytes = BytesIO()
    rgb_img.save(jpeg_bytes, format='JPEG')
    jpeg_bytes.seek(0)
    
    ndvi_bytes = BytesIO()
    ndvi_img.save(ndvi_bytes, format='JPEG')
    ndvi_bytes.seek(0)
    
    # Store in MinIO
    minio_client.put_object(
        "uav-images",
        f"{UAV_ID}/{timestamp}_rgb.jpg",
        jpeg_bytes,
        length=jpeg_bytes.getbuffer().nbytes,
        content_type='image/jpeg'
    )
    
    minio_client.put_object(
        "uav-images",
        f"{UAV_ID}/{timestamp}_ndvi.jpg",
        ndvi_bytes,
        length=ndvi_bytes.getbuffer().nbytes,
        content_type='image/jpeg'
    )
    
    return {
        "uav_id": UAV_ID,
        "timestamp": timestamp,
        "rgb_url": f"http://localhost:9000/uav-images/{UAV_ID}/{timestamp}_rgb.jpg",
        "ndvi_url": f"http://localhost:9000/uav-images/{UAV_ID}/{timestamp}_ndvi.jpg",
        "metadata": {
            "resolution": bands['red'].shape,
            "bands": list(bands.keys())
        }
    }

def main():
    processed_files = set()

    minio_client = Minio(
        os.getenv("MINIO_ENDPOINT"),
        access_key=os.getenv("MINIO_ACCESS_KEY"),
        secret_key=os.getenv("MINIO_SECRET_KEY"),
        secure=False
    )


    producer = KafkaProducer(
    bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS").split(","),
    value_serializer=lambda v: json.dumps(v).encode('utf-8'),
    retries=5
    )

    if not minio_client.bucket_exists("uav-images"):
        minio_client.make_bucket("uav-images")

    for filename in os.listdir(MISSION_PATH):
        if filename.endswith('_red_high.tif'):
            base_name = filename.replace('_red_high.tif', '')
            if base_name not in processed_files:
                try:
                    data = process_image(base_name, minio_client)
                    producer.send(KAFKA_TOPIC, value=data)
                    print(f"Sent data for {base_name}")
                    processed_files.add(base_name)
                except Exception as e:
                    print(f"Error processing {base_name}: {str(e)}")
        

if __name__ == "__main__":
    main()