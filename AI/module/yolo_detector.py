import base64
import binascii
import os
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np


APP_DIR = Path(__file__).resolve().parents[1]
MODEL_PATH = Path(os.getenv("MODEL_PATH", APP_DIR / "models" / "bestM.pt"))
CONF_THRES = float(os.getenv("CONF_THRES", "0.30"))
IMGSZ = int(os.getenv("IMGSZ", "480"))
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")


@lru_cache(maxsize=1)
def _model():
    from ultralytics import YOLO

    return YOLO(str(MODEL_PATH))


def decode_image(image_bytes: bytes):
    image_array = np.frombuffer(image_bytes, dtype=np.uint8)
    frame = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("invalid image")
    return frame


def decode_base64_image(image_text: str):
    if "," in image_text:
        image_text = image_text.split(",", 1)[1]
    try:
        return decode_image(base64.b64decode(image_text, validate=True))
    except (binascii.Error, ValueError):
        raise ValueError("invalid base64 image")


def detect_yawn_frame(frame):
    result = _model().predict(frame, conf=CONF_THRES, imgsz=IMGSZ, verbose=False)[0]
    detections = []
    yawn_confidence = 0.0

    for box in result.boxes:
        class_id = int(box.cls[0])
        label = result.names[class_id]
        confidence = float(box.conf[0])
        xyxy = [float(value) for value in box.xyxy[0]]
        is_yawn = "yawn" in label.lower()

        detections.append({
            "label": label,
            "confidence": confidence,
            "box": xyxy,
        })

        if is_yawn:
            yawn_confidence = max(yawn_confidence, confidence)

    return {
        "yawning": yawn_confidence > 0.0,
        "yawn_confidence": yawn_confidence,
        "detections": detections,
    }


def detect_yawn_bytes(image_bytes: bytes):
    return detect_yawn_frame(decode_image(image_bytes))
