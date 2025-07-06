import os
import numpy as np
import cv2
from glob import glob
from pathlib import Path
import argparse
from tqdm import tqdm
import shutil
import pandas as pd
from collections import defaultdict

def clean_and_process_data(source_path, output_path, selected_classes, not_relevant_classes,
                           img_size=(512, 512), max_samples=None,
                           max_per_class=2000):
    source_path = Path(source_path)
    output_path = Path(output_path)

    inputs_dir = output_path / "inputs"
    labels_dir = output_path / "labels"
    boundaries_dir = output_path / "boundaries"

    os.makedirs(inputs_dir, exist_ok=True)
    os.makedirs(labels_dir, exist_ok=True)
    os.makedirs(boundaries_dir, exist_ok=True)

    available_classes = [d.name for d in (source_path / "labels").iterdir() if d.is_dir()]
    image_class_map = defaultdict(set)

    all_relevant_classes = set(selected_classes) | set(not_relevant_classes)

    print("Precomputing class mappings...")
    for cls in tqdm(available_classes):
        if cls in all_relevant_classes: 
            cls_dir = source_path / "labels" / cls
            for mask_path in cls_dir.glob("*.png"):
                image_id = mask_path.stem
                image_class_map[image_id].add(cls)

    rgb_paths = {Path(p).stem: p for p in glob(str(source_path / "images" / "rgb" / "*.jpg"))}
    nir_paths = {Path(p).stem: p for p in glob(str(source_path / "images" / "nir" / "*.jpg"))}
    boundaries = {Path(p).stem: p for p in glob(str(source_path / "boundaries" / "*.png"))}

    all_image_ids = set(rgb_paths.keys()) & set(nir_paths.keys())
    image_class_map = {
        k: v for k, v in image_class_map.items()
        if k in all_image_ids and any(cls in all_relevant_classes for cls in v)
    }

    num_selected_classes = len(selected_classes)

    print(f"Output mask will have {num_selected_classes} channels.")

    selected_class_mapping = {cls: idx for idx, cls in enumerate(selected_classes)}

    stats = {cls: 0 for cls in selected_classes}
    stats["no_stress_found"] = 0
    csv_data = []
    processed_count = 0
    per_selected_class_count = {cls: 0 for cls in selected_classes}

    print("\nProcessing images...")
    image_ids_to_process = list(image_class_map.keys())
    np.random.shuffle(image_ids_to_process)  # Shuffle to randomize processing order

    for image_id in tqdm(image_ids_to_process):
        classes_present_in_image = image_class_map[image_id]
        output_mask = np.zeros((*img_size, num_selected_classes), dtype=np.uint8)
        has_selected_content = False
        has_no_stress_content = False
        processed_classes_in_image = set()
        for cls in classes_present_in_image:

            if cls not in selected_class_mapping:
                continue
            if per_selected_class_count[cls] >= max_per_class:
                continue  # Skip if class limit reached
            mask_path = source_path / "labels" / cls / f"{image_id}.png"
            if not mask_path.exists():
                continue
            mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
            if mask is None:
                continue
            mask_resized = cv2.resize(mask, img_size, interpolation=cv2.INTER_NEAREST)
            binary_mask = (mask_resized > 0).astype(np.uint8)
            if np.any(binary_mask) > 0:
                class_idx = selected_class_mapping[cls]
                output_mask[:, :, class_idx] = binary_mask
                has_selected_content = True
                processed_classes_in_image.add(cls)
                per_selected_class_count[cls] += 1


            boundarie = cv2.imread(str(boundaries[image_id]), cv2.IMREAD_GRAYSCALE)
            if boundarie is not None:
                boundarie = cv2.resize(boundarie, img_size, interpolation=cv2.INTER_NEAREST)

                boundarie = (boundarie > 0).astype(np.uint8)
                if stats["no_stress_found"] > max_per_class:
                    continue
                for cls in classes_present_in_image:
                    
                    if cls in not_relevant_classes:
                        mask_path = source_path / "labels" / cls / f"{image_id}.png"
                        
                        if mask_path.exists():
                            mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
                            if mask is None:
                                continue
                            mask_resized = cv2.resize(mask, img_size, interpolation=cv2.INTER_NEAREST)
                            binary_mask = (mask_resized > 0).astype(np.uint8)
                            if np.any(binary_mask):
                                has_no_stress_content = True

        if has_selected_content or has_no_stress_content:
                    # Load and save image data
                    rgb = cv2.imread(str(rgb_paths[image_id]))
                    rgb = cv2.cvtColor(rgb, cv2.COLOR_BGR2RGB)
                    rgb = cv2.resize(rgb, img_size, interpolation=cv2.INTER_AREA)
                    nir = cv2.imread(str(nir_paths[image_id]), cv2.IMREAD_GRAYSCALE)
                    nir = cv2.resize(nir, img_size, interpolation=cv2.INTER_AREA)
                    rgbn = np.dstack((rgb, nir))
                    
                    np.save(inputs_dir / f"{image_id}.npy", rgbn)
                    np.save(labels_dir / f"{image_id}.npy", output_mask)
                    record = {"image_id": image_id}
                    for sel_cls in selected_classes:
                        record[sel_cls] = int(sel_cls in processed_classes_in_image)
                    record["no_stress_found"] = int(has_no_stress_content)
                    csv_data.append(record)

                    for cls in processed_classes_in_image:
                        if cls in selected_classes:
                            stats[cls] += 1
                    if has_no_stress_content:
                        stats["no_stress_found"] += 1

                    processed_count += 1
            
        if max_samples and processed_count >= max_samples:
            break

    # Save metadata and statistics
    if csv_data:
        df = pd.DataFrame(csv_data)
        df.to_csv(output_path / "metadata.csv", index=False)
        print(f"\nFinal statistics (Total processed: {processed_count}):")
        for cls, count in stats.items():
            print(f"- {cls}: {count} ({count/processed_count*100:.1f}%)")
    else:
        print("\nNo images processed.")

    return processed_count, stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agriculture Vision Data Preparer (Simplified Multi-Channel)")
    parser.add_argument("--source", required=True, help="Source dataset directory")
    parser.add_argument("--output", required=True, help="Output directory")
    # Class selection
    parser.add_argument("--selected", nargs="+",
                        default=["nutrient_deficiency", "drydown", "planter_skip", "water", "weed_cluster", "storm_damage"],
                        help="Target classes representing stress (each gets its own channel)")
    parser.add_argument("--no-labels", nargs="+",
                        default=["endrow", "waterway", "double_plant"],
                        help="Classes representing 'no-stress' (merged into a single channel)")
    # Processing options
    parser.add_argument("--img-size", type=int, nargs=2, default=[512, 512], help="Target image size (height, width)")
    parser.add_argument("--test-split", type=float, default=0.2, help="Fraction for test set (0 to disable)")
    parser.add_argument("--max-samples", type=int, default=None, help="Max samples to process (default: all)")
    parser.add_argument("--max-per-class", type=int, default=5000,
                        help="Max samples per SELECTED stress class (default: 5000)")

    args = parser.parse_args()
    args.img_size = tuple(args.img_size)

    # --- Process Data ---
    total, stats_dict = clean_and_process_data(
        args.source,
        args.output,
        selected_classes=args.selected,
        not_relevant_classes=args.no_labels,
        img_size=args.img_size,
        max_samples=args.max_samples,
        max_per_class=args.max_per_class
    )

    # --- Create Train-Test Split (same logic as before, using the new metadata) ---
    if args.test_split > 0 and total > 0:
        output_base = Path(args.output)
        metadata_path = output_base / "metadata.csv"
        if not metadata_path.exists():
             print(f"Error: Metadata file not found at {metadata_path}. Cannot perform train/test split.")
        else:
            all_ids_df = pd.read_csv(metadata_path)
            if 'image_id' not in all_ids_df.columns:
                 print("Error: 'image_id' column missing in metadata.csv. Cannot perform train/test split.")
            else:
                all_image_ids = all_ids_df['image_id'].tolist()
                np.random.shuffle(all_image_ids)
                split_idx = int(len(all_image_ids) * (1 - args.test_split))
                train_ids = all_image_ids[:split_idx]
                test_ids = all_image_ids[split_idx:]
                print(f"\nSplitting dataset: {len(train_ids)} train, {len(test_ids)} test samples...")
                # (Copying logic remains the same)
                for subset, ids in [("train", train_ids), ("test", test_ids)]:
                    subset_dir = output_base / subset
                    subset_inputs = subset_dir / "inputs"
                    subset_labels = subset_dir / "labels"
                    os.makedirs(subset_inputs, exist_ok=True)
                    os.makedirs(subset_labels, exist_ok=True)
                    for image_id in tqdm(ids, desc=f"Copying {subset} files"):
                        src_input = output_base / "inputs" / f"{image_id}.npy"
                        if src_input.exists(): shutil.copy(src_input, subset_inputs / f"{image_id}.npy")
                        src_label = output_base / "labels" / f"{image_id}.npy"
                        if src_label.exists(): shutil.copy(src_label, subset_labels / f"{image_id}.npy")
                df_train = all_ids_df[all_ids_df.image_id.isin(train_ids)]
                df_test = all_ids_df[all_ids_df.image_id.isin(test_ids)]
                df_train.to_csv(output_base / "train_metadata.csv", index=False)
                df_test.to_csv(output_base / "test_metadata.csv", index=False)
                print(f"Train/Test split metadata saved.")

    elif total == 0: print("\nNo images processed, skipping train/test split.")
    else: print("\nTest split not requested (test_split=0).")