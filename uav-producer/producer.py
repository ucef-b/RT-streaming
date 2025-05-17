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
import matplotlib.pyplot as plt
from ai_edge_litert.interpreter import Interpreter

interpreter = Interpreter(model_path="model.tflite")
interpreter.allocate_tensors()

# Get input and output details
input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()

# Configuration
UAV_ID = os.getenv("UAV_ID")
MISSION_PATH = f"/data/{UAV_ID}" # 
KAFKA_TOPIC = f"uav.{UAV_ID}.images" # depence on uav-producer are runing in the same container

def create_patches(ndvi_array, patch_size=512):
    """Create patches from NDVI array"""
    patches = []
    patch_positions = []  # Store positions for reconstruction
    h, w = ndvi_array.shape
    
    for i in range(0, h-patch_size+1, patch_size):
        for j in range(0, w-patch_size+1, patch_size):
            patch = ndvi_array[i:i+patch_size, j:j+patch_size]
            # Resize patch to 256x256
            patch_img = Image.fromarray((patch * 255).astype(np.uint8))
            patch_resized = patch_img.resize((256, 256), Image.Resampling.BILINEAR)
            patch_array = np.array(patch_resized) / 255.0
            patches.append(patch_array)
            patch_positions.append((i, j))
    
    return np.array(patches), patch_positions

def predict_patches(patches, interpreter):
    """Make predictions on patches using TFLite"""
    predictions = []
    classification_outputs = []
    patches = patches[..., np.newaxis].astype(np.float32)
    
    for patch in patches:
        # Prepare input tensor
        input_data = np.expand_dims(patch, axis=0)
        interpreter.set_tensor(input_details[0]['index'], input_data)
        
        # Run inference
        interpreter.invoke()
        
        # Get predictions from both outputs
        classification_output = interpreter.get_tensor(output_details[0]['index'])  # Shape: [1, 6]
        segmentation_output = interpreter.get_tensor(output_details[1]['index'])   # Shape: [1, 256, 256, 1]
        
        predictions.append(segmentation_output[0])  # Remove batch dimension
        classification_outputs.append(classification_output[0])  # Remove batch dimension
        
        # Log first prediction for debugging
        if len(predictions) == 1:
            print(f"Classification output shape: {classification_output.shape}")
            print(f"Classification values: {classification_output[0]}")
            print(f"Segmentation output shape: {segmentation_output.shape}")
    
    return np.array(predictions), np.array(classification_outputs)


def calculate_ndvi(red_band, nir_band):
    red = red_band.astype(np.float32)
    nir = nir_band.astype(np.float32)
    ndvi = (nir - red) / (nir + red + 1e-8)
    return ndvi

def ndvi_to_bytes(ndvi):
    buf = BytesIO()
    plt.figure(figsize=(ndvi.shape[1] / 100, ndvi.shape[0] / 100), dpi=100)
    plt.imshow(ndvi, cmap='RdYlGn', vmin=-1, vmax=1)
    plt.axis('off')
    plt.savefig(buf, format='JPEG', bbox_inches='tight', pad_inches=0)
    plt.close()
    buf.seek(0)
    return buf

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
    ndvi = calculate_ndvi(bands['red'], bands['nir'])

    patches, patch_positions = create_patches(ndvi)
    segmentation_preds, classification_preds = predict_patches(patches, interpreter)

    print(f"Segmentation predictions shape: {segmentation_preds.shape}")
    print(f"Classification predictions shape: {classification_preds.shape}")

    ndvi_bytes = ndvi_to_bytes(ndvi)
    
    # Upload to MinIO
    timestamp = int(time.time())
    jpeg_bytes = BytesIO()
    rgb_img.save(jpeg_bytes, format='JPEG')
    jpeg_bytes.seek(0)
    
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
            "bands": list(bands.keys()),
            "predictions": {
                "classification": classification_preds.tolist(),
                "segmentation_shape": segmentation_preds.shape
            }
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