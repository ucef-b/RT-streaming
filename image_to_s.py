import os
import numpy as np
import cv2
import rasterio

input_dir  = "data"
output_dir = "data"
base_code  = 72817     
n_frames   = 10
max_shift  = 50.0         # pixels
max_rot    = 10.0         # degrees
bands      = ["green","red","blue","nir"]

#Open one band to get meta & shape
with rasterio.open(os.path.join(input_dir, f"{base_code:06d}_{bands[0]}_high.tif")) as src0:
    meta = src0.meta.copy()
    h, w = src0.height, src0.width

#Read all bands into memory
arrays = {}
for band in bands:
    path = os.path.join(input_dir, f"{base_code:06d}_{band}_high.tif")
    print(f"Reading {path}")
    with rasterio.open(path) as src:
        arrays[band] = src.read(1)

#Precompute linear ramps for shift & rotation
shifts = np.linspace(0, max_shift, n_frames)
rots   = np.linspace(0, max_rot,   n_frames)

for i in range(1, n_frames+1):
    code = base_code + i
    # Circular motion in X/Y
    dx = shifts[i-1] * np.cos(2 * np.pi * i / n_frames)
    dy = shifts[i-1] * np.sin(2 * np.pi * i / n_frames)
    angle = rots[i-1]  # degrees

    # Build an OpenCV affine matrix:
    # Rotate about center, then translate
    center = (w/2, h/2)
    M_rot = cv2.getRotationMatrix2D(center, angle, 1.0)  # 2x3 matrix
    M_rot[0,2] += dx
    M_rot[1,2] += dy

    # Warp each band and write out
    for band in bands:
        src_arr = arrays[band]
        warped = cv2.warpAffine(
            src_arr,
            M_rot,
            (w, h),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT
        )

        # Update meta (no georef):
        out_meta = meta.copy()
        out_meta.update({
            "height": h,
            "width":  w,
            "transform": rasterio.transform.Affine(1,0,0, 0,1,0)
        })

        out_path = os.path.join(output_dir, f"{code:06d}_{band}_high.tif")
        print(f"Writing {out_path}")
        with rasterio.open(out_path, "w", **out_meta) as dst:
            dst.write(warped, 1)

    print(f"Frame {i}/{n_frames} → {code:06d}.tif written")

print("All done!")