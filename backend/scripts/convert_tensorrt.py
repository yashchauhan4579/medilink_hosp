"""
Convert best_head.pt to TensorRT engine.
Run ON the Jetson:
    python3 scripts/convert_tensorrt.py
"""
import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Convert YOLO .pt to TensorRT .engine")
    parser.add_argument("--model", default="models/best_head.pt", help="Path to .pt file")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--half", action="store_true", default=True, help="FP16 quantization")
    args = parser.parse_args()

    from ultralytics import YOLO

    model_path = Path(args.model)
    if not model_path.exists():
        print(f"ERROR: Model not found at {model_path}")
        return

    print(f"Loading model from {model_path}...")
    model = YOLO(str(model_path))

    print(f"Exporting to TensorRT (FP16={args.half}, imgsz={args.imgsz})...")
    print("This may take 5-15 minutes on first run.")
    engine_path = model.export(
        format="engine",
        imgsz=args.imgsz,
        half=args.half,
        batch=1,
        device=0,
        workspace=4,
        simplify=True,
    )
    print(f"Engine saved to: {engine_path}")

    # Verify
    print("Verifying engine loads...")
    test_model = YOLO(engine_path, task="detect")
    import numpy as np
    dummy = np.zeros((args.imgsz, args.imgsz, 3), dtype=np.uint8)
    results = test_model.predict(dummy, verbose=False)
    print(f"Verification OK — {len(results[0].boxes)} detections on blank image (expected 0)")
    print("Done!")


if __name__ == "__main__":
    main()
