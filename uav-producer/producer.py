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
import cv2
from collections import defaultdict

interpreter = Interpreter(model_path="model.tflite")
interpreter.allocate_tensors()

CLASS_COLORS = {
    0: (255, 0, 0),    # Red for class 0 nutrient_deficiency 
    1: (0, 255, 0),    # Green for class 1 drydown 
    2: (0, 0, 255),    # Blue for class 2 water 
    3: (255, 255, 0),  # Cyan for class 3 weed_cluster 
    4: (255, 0, 255),  # Magenta for class 4 planter_skip
    5: None            # No color for class 5 (not detected)
}

# Add anomaly class names
ANOMALY_CLASSES = {
    0: "nutrient_deficiency",
    1: "drydown",
    2: "water",
    3: "weed_cluster",
    4: "planter_skip",
    5: "not_detected"
}

# Get input and output details
input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()

# Configuration
UAV_ID = os.getenv("UAV_ID")
MISSION_PATH = f"/data/{UAV_ID}" # 

# Define Kafka topics for each image type
KAFKA_TOPIC_RGB = f"uav.{UAV_ID}.images.rgb"
KAFKA_TOPIC_NDVI = f"uav.{UAV_ID}.images.ndvi"
KAFKA_TOPIC_PREDICTED = f"uav.{UAV_ID}.images.predicted"

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

def create_segmentation_overlay(rgb_img, segmentation_preds, classification_preds, patch_positions, patch_size=512):
    """Create colored overlay of segmentation masks on RGB image"""
    # Convert PIL Image to numpy array
    rgb_array = np.array(rgb_img)
    
    # Create empty overlay with same size as RGB image
    overlay = np.zeros_like(rgb_array)
    
    # For each patch
    for patch_pred, class_pred, (y, x) in zip(segmentation_preds, classification_preds, patch_positions):
        # Get the most likely class
        predicted_class = np.argmax(class_pred)
        
        # Skip if it's class 5 (not detected)
        if predicted_class == 5:
            continue
            
        # Get color for this class
        color = CLASS_COLORS[predicted_class]
        
        # Resize segmentation mask back to 512x512
        mask = cv2.resize(patch_pred, (patch_size, patch_size))
        
        # Threshold the mask
        mask = (mask > 0.5).astype(np.uint8)
        
        # Create colored mask
        colored_mask = np.zeros((patch_size, patch_size, 3), dtype=np.uint8)
        colored_mask[mask > 0] = color
        
        # Add to overlay at correct position
        try:
            overlay[y:y+patch_size, x:x+patch_size] = colored_mask
        except ValueError as e:
            print(f"Error placing patch at position ({x}, {y}): {str(e)}")
            continue
    
    # Blend RGB image with overlay
    alpha = 0.5  # Transparency factor
    blended = cv2.addWeighted(rgb_array, 1, overlay, alpha, 0)
    
    return Image.fromarray(blended)

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

def send_rgb_and_ndvi_immediately(base_name, minio_client, producer):
    """Process and send RGB and NDVI images immediately after preparation"""
    start_time = time.time()
    timestamp = int(time.time())
    
    # Load bands
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
    ndvi_bytes = ndvi_to_bytes(ndvi)
    
    # Prepare RGB bytes
    jpeg_bytes = BytesIO()
    rgb_img.save(jpeg_bytes, format='JPEG')
    jpeg_bytes.seek(0)
    
    # Upload RGB to MinIO
    minio_client.put_object(
        "uav-images",
        f"{UAV_ID}/{timestamp}_rgb.jpg",
        jpeg_bytes,
        length=jpeg_bytes.getbuffer().nbytes,
        content_type='image/jpeg'
    )
    
    # Upload NDVI to MinIO
    minio_client.put_object(
        "uav-images",
        f"{UAV_ID}/{timestamp}_ndvi.jpg",
        ndvi_bytes,
        length=ndvi_bytes.getbuffer().nbytes,
        content_type='image/jpeg'
    )
    
    # Create basic metadata for RGB and NDVI
    basic_metadata = {
        "resolution": bands['red'].shape,
        "bands": list(bands.keys()),
        "processing_info": {
            "time_seconds": round(time.time() - start_time, 2),
            "stage": "basic_processing"
        }
    }
    
    # Send RGB message immediately
    rgb_message = {
        "uav_id": UAV_ID,
        "timestamp": timestamp,
        "image_url": f"http://localhost:9000/uav-images/{UAV_ID}/{timestamp}_rgb.jpg",
        "image_type": "rgb",
        "metadata": basic_metadata
    }
    
    # Send NDVI message immediately
    ndvi_message = {
        "uav_id": UAV_ID,
        "timestamp": timestamp,
        "image_url": f"http://localhost:9000/uav-images/{UAV_ID}/{timestamp}_ndvi.jpg",
        "image_type": "ndvi",
        "metadata": basic_metadata
    }
    
    producer.send(KAFKA_TOPIC_RGB, value=rgb_message)
    producer.send(KAFKA_TOPIC_NDVI, value=ndvi_message)
    
    print(f"Sent RGB and NDVI for {base_name} immediately to topics: {KAFKA_TOPIC_RGB}, {KAFKA_TOPIC_NDVI}")
    
    return rgb_img, ndvi, bands, timestamp

def process_predictions_and_send(base_name, rgb_img, ndvi, bands, timestamp, minio_client, producer):
    """Process model predictions and send the predicted image"""
    start_time = time.time()
    detected_anomalies = set()
    
    # Create patches and run predictions
    patches, patch_positions = create_patches(ndvi)
    segmentation_preds, classification_preds = predict_patches(patches, interpreter)
    segmentation_overlay = create_segmentation_overlay(
        rgb_img, 
        segmentation_preds, 
        classification_preds, 
        patch_positions
    )
    
    # Upload predicted image to MinIO
    overlay_bytes = BytesIO()
    segmentation_overlay.save(overlay_bytes, format='JPEG')
    overlay_bytes.seek(0)
    
    minio_client.put_object(
        "uav-images",
        f"{UAV_ID}/{timestamp}_predicted.jpg",
        overlay_bytes,
        length=overlay_bytes.getbuffer().nbytes,
        content_type='image/jpeg'
    )
    
    # Analyze classifications for anomalies
    for class_pred in classification_preds:
        predicted_class = np.argmax(class_pred)
        if predicted_class != 5:  # If not "not_detected"
            detected_anomalies.add(ANOMALY_CLASSES[predicted_class])
    
    # Create complete metadata with predictions
    complete_metadata = {
        "resolution": bands['red'].shape,
        "bands": list(bands.keys()),
        "predictions": {
            "classification": classification_preds.tolist(),
            "segmentation_shape": segmentation_preds.shape
        },
        "processing_info": {
            "time_seconds": round(time.time() - start_time, 2),
            "detected_anomalies": list(detected_anomalies),
            "stage": "prediction_complete"
        }
    }
    
    # Send predicted image message
    predicted_message = {
        "uav_id": UAV_ID,
        "timestamp": timestamp,
        "image_url": f"http://localhost:9000/uav-images/{UAV_ID}/{timestamp}_predicted.jpg",
        "image_type": "predicted",
        "metadata": complete_metadata
    }
    
    producer.send(KAFKA_TOPIC_PREDICTED, value=predicted_message)
    
    print(f"Sent predicted image for {base_name} to topic: {KAFKA_TOPIC_PREDICTED}")

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
                    # Step 1: Process and send RGB and NDVI immediately
                    rgb_img, ndvi, bands, timestamp = send_rgb_and_ndvi_immediately(
                        base_name, minio_client, producer
                    )
                    
                    # Step 2: Process predictions and send predicted image
                    process_predictions_and_send(
                        base_name, rgb_img, ndvi, bands, timestamp, minio_client, producer
                    )
                    
                    processed_files.add(base_name)
                    
                except Exception as e:
                    print(f"Error processing {base_name}: {str(e)}")
        

if __name__ == "__main__":
    main()
