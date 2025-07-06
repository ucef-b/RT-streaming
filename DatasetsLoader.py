import numpy as np
import torch
from torch.utils.data import Dataset, DataLoader
from pathlib import Path
from typing import Tuple, Dict, List, Optional, Union
import random
from torchvision import transforms
import torchvision.transforms.functional as TF

class PyTorchDatasetLoader(Dataset):
    """
    PyTorch Dataset for Agriculture-Vision preprocessed dataset with single-channel binary mask output
    and classification output
    """
    def __init__(
        self,
        working_path: str,
        export_type: str = "RGBN",
        outputs_type: str = "both",
        augmentation: bool = False,
        shuffle: bool = False,
        test_size=None,
        val_size = None
    ):
        """
        Args:
            working_path (str): Path to preprocessed dataset
            export_type (str): Type of input image ('RGBN', 'NDVI', or 'RGB')
            outputs_type (str): Type of output ('mask_only', 'class_only', or 'both')
            augmentation (bool): Whether to apply data augmentation
            shuffle (bool): Whether to shuffle the dataset
        """
        self.working_path = Path(working_path)
        self.export_type = export_type
        self.outputs_type = outputs_type
        self.augmentation = augmentation

        # Load file paths
        self.input_files = sorted(list((self.working_path / "inputs").glob("*.npy")))
        self.label_files = sorted(list((self.working_path / "labels").glob("*.npy")))

        # Validation checks
        assert len(self.input_files) == len(self.label_files), "Mismatch in input and label files"
        assert export_type in ["RGBN", "NDVI", "RGB"], "Invalid export_type"
        assert outputs_type in ["mask_only", "class_only", "both"], "Invalid outputs_type"

        self.num_samples = len(self.input_files)
        self.num_testsize = int(len(self.input_files) * (split_test))
    
        # Shuffle files if requested
        if shuffle:
            combined = list(zip(self.input_files, self.label_files))
            random.shuffle(combined)
            self.input_files, self.label_files = zip(*combined)

    def __len__(self) -> int:
        return self.num_samples

    def calculate_ndvi(self, rgbn_image: np.ndarray) -> np.ndarray:
        """Calculate NDVI from RGBN image"""
        nir = rgbn_image[:, :, 3].astype(np.float32) / 255.0
        red = rgbn_image[:, :, 0].astype(np.float32) / 255.0

        # Calculate NDVI
        ndvi = (nir - red) / (nir + red + 1e-8)  # ranges from -1 to +1

        # Scale NDVI to [0, 255]
        ndvi_scaled = ((ndvi + 1) * 127.5).astype(np.uint8)

        return np.expand_dims(ndvi_scaled, axis=-1)

    def process_input(self, rgbn_image: np.ndarray) -> np.ndarray:
        """Process input image based on export_type"""
        if self.export_type == "RGBN":
            return rgbn_image
        elif self.export_type == "NDVI":
            return self.calculate_ndvi(rgbn_image)
        else:  # RGB
            return rgbn_image[:, :, :3]

    def create_binary_mask(self, multi_class_mask: np.ndarray) -> np.ndarray:
        """Convert multi-class mask to binary mask using OR logic"""
        # Combine all channels using logical OR
        binary_mask = np.any(multi_class_mask > 0, axis=-1).astype(np.float32)
        # Expand dimensions to create shape (H, W, 1)
        return np.expand_dims(binary_mask, axis=-1)

    def augment_data(self, image: torch.Tensor, mask: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """Apply data augmentation using PyTorch transforms"""
        if not self.augmentation:
            return image, mask

        # Random horizontal flip
        if random.random() > 0.5:
            image = TF.hflip(image)
            mask = TF.hflip(mask)

        # Random vertical flip
        if random.random() > 0.5:
            image = TF.vflip(image)
            mask = TF.vflip(mask)

        # Random rotation (±15 degrees)
        if random.random() > 0.5:
            angle = random.uniform(-15, 15)
            image = TF.rotate(image, angle)
            mask = TF.rotate(mask, angle)

        return image, mask

    def __getitem__(self, idx: int) -> Tuple[torch.Tensor, Union[torch.Tensor, Dict[str, torch.Tensor]]]:
        """Get item by index"""
        # Load data
        rgbn_image = np.load(self.input_files[idx])
        multi_class_mask = np.load(self.label_files[idx])

        # Process input
        processed_image = self.process_input(rgbn_image)

        # Create binary mask using OR logic across all class channels
        binary_mask = self.create_binary_mask(multi_class_mask)

        # Get class presence (1 if class exists, 0 otherwise)
        class_presence = (np.sum(multi_class_mask, axis=(0,1)) > 0).astype(np.float32)
        no_class = float(class_presence.sum() == 0)
        class_presence = np.concatenate([class_presence, [no_class]], axis=0)

        # Convert to PyTorch tensors and normalize
        # Convert HWC to CHW format for PyTorch
        image_tensor = torch.FloatTensor(processed_image).permute(2, 0, 1) / 255.0
        mask_tensor = torch.FloatTensor(binary_mask).permute(2, 0, 1)
        class_tensor = torch.FloatTensor(class_presence)

        # Apply augmentation
        if self.augmentation:
            image_tensor, mask_tensor = self.augment_data(image_tensor, mask_tensor)

        # Prepare output based on outputs_type
        if self.outputs_type == "mask_only":
            return image_tensor, mask_tensor
        elif self.outputs_type == "class_only":
            return image_tensor, class_tensor
        else:  # both
            return image_tensor, {
                'segmentation_output': mask_tensor,
                'classification_output': class_tensor
            }


class DatasetLoaderWrapper:
    """
    Wrapper class to maintain compatibility with your existing code structure
    while providing PyTorch DataLoader functionality
    """
    def __init__(
        self,
        working_path: str,
        batch_size: int = 8,
        export_type: str = "RGBN",
        outputs_type: str = "both",
        augmentation: bool = False,
        shuffle: bool = False,
        num_workers: int = 4,
        pin_memory: bool = True
    ):
        """
        Args:
            working_path (str): Path to preprocessed dataset
            batch_size (int): Number of samples per batch
            export_type (str): Type of input image ('RGBN', 'NDVI', or 'RGB')
            outputs_type (str): Type of output ('mask_only', 'class_only', or 'both')
            augmentation (bool): Whether to apply data augmentation
            shuffle (bool): Whether to shuffle the dataset
            num_workers (int): Number of worker processes for data loading
            pin_memory (bool): Whether to pin memory for faster GPU transfer
        """
        self.dataset = PyTorchDatasetLoader(
            working_path=working_path,
            export_type=export_type,
            outputs_type=outputs_type,
            augmentation=augmentation,
            shuffle=shuffle
        )
        
        self.dataloader = DataLoader(
            self.dataset,
            batch_size=batch_size,
            shuffle=shuffle,
            num_workers=num_workers,
            pin_memory=pin_memory,
            drop_last=False
        )
        
        self.batch_size = batch_size
        self.export_type = export_type
        self.outputs_type = outputs_type

    def __len__(self) -> int:
        return len(self.dataset)

    def __iter__(self):
        """Return iterator for the DataLoader"""
        return iter(self.dataloader)

    def get_single_batch(self) -> Tuple[torch.Tensor, Union[torch.Tensor, Dict[str, torch.Tensor]]]:
        """Get a single batch for testing purposes"""
        for batch in self.dataloader:
            return batch
        raise StopIteration("No data available")