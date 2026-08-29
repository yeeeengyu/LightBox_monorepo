from collections import deque
import os
import sys
import time
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from ultralytics import YOLO


APP_DIR = Path(__file__).resolve().parents[1]
MODEL_PATH = APP_DIR / "models" / "bestM.pt"
CONF_THRES = float(os.getenv("CONF_THRES", "0.30"))
IMGSZ = int(os.getenv("IMGSZ", "480"))
EAR_THRESH = float(os.getenv("EAR_THRESH", "0.19"))
SMOOTH_N = int(os.getenv("SMOOTH_N", "5"))
FRAME_W = int(os.getenv("FRAME_W", "1900"))
FRAME_H = int(os.getenv("FRAME_H", "1000"))
FONT = cv2.FONT_HERSHEY_SIMPLEX
WINDOW_NAME = "bestM.pt test"

RIGHT_EYE_IDXS = [33, 160, 158, 133, 153, 144]
LEFT_EYE_IDXS = [263, 387, 385, 362, 380, 373]

mp_face = mp.solutions.face_mesh
face_mesh = mp_face.FaceMesh(
    static_image_mode=False,
    max_num_faces=1,
    refine_landmarks=True,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5,
)


def euclidean(p1, p2) -> float:
    return np.linalg.norm(np.array(p1) - np.array(p2))


def eye_ear(pts) -> float:
    p1, p2, p3, p4, p5, p6 = pts
    return (euclidean(p2, p6) + euclidean(p3, p5)) / (2.0 * euclidean(p1, p4) + 1e-6)


def predict(model: YOLO, frame):
    return model.predict(frame, conf=CONF_THRES, imgsz=IMGSZ, verbose=False)[0]


def draw_ear(source_frame, draw_frame, ear_hist: deque) -> None:
    h, w = source_frame.shape[:2]
    rgb = cv2.cvtColor(source_frame, cv2.COLOR_BGR2RGB)
    results = face_mesh.process(rgb)

    if results.multi_face_landmarks:
        lm = results.multi_face_landmarks[0].landmark

        def to_xy(idx):
            return (lm[idx].x * w, lm[idx].y * h)

        right_eye_pts = [to_xy(i) for i in RIGHT_EYE_IDXS]
        left_eye_pts = [to_xy(i) for i in LEFT_EYE_IDXS]

        ear_r = eye_ear(right_eye_pts)
        ear_l = eye_ear(left_eye_pts)
        ear_hist.append((ear_r + ear_l) / 2.0)

        for x, y in right_eye_pts + left_eye_pts:
            cv2.circle(draw_frame, (int(x), int(y)), 2, (0, 255, 255), -1)

    if ear_hist:
        ear_smooth = sum(ear_hist) / len(ear_hist)
        status = "OPEN" if ear_smooth >= EAR_THRESH else "CLOSED"
        color = (0, 255, 0) if status == "OPEN" else (0, 0, 255)

        cv2.putText(draw_frame, f"EAR: {ear_smooth:.3f}  [{status}]", (10, 30), FONT, 0.8, color, 2)

        bar_max = 200
        ear_clamped = max(0.0, min(0.4, ear_smooth))
        bar_len = int((ear_clamped / 0.4) * bar_max)
        cv2.rectangle(draw_frame, (10, 40), (10 + bar_max, 60), (50, 50, 50), 1)
        cv2.rectangle(draw_frame, (10, 40), (10 + bar_len, 60), color, -1)
    else:
        cv2.putText(draw_frame, "EAR: -- (no face)", (10, 30), FONT, 0.8, (0, 255, 255), 2)


def draw_fps(frame, fps: float) -> None:
    cv2.putText(frame, f"FPS: {fps:.1f}", (10, 90), FONT, 0.7, (255, 255, 255), 2)


def resize_for_display(frame):
    return cv2.resize(frame, (FRAME_W, FRAME_H), interpolation=cv2.INTER_AREA)


def predict_image(model: YOLO, image_path: str) -> None:
    frame = cv2.imread(image_path)
    if frame is None:
        raise FileNotFoundError(f"Cannot read image: {image_path}")

    result = predict(model, frame)
    output = result.plot()
    draw_ear(frame, output, deque(maxlen=SMOOTH_N))
    output = resize_for_display(output)

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_NAME, FRAME_W, FRAME_H)
    cv2.imshow(WINDOW_NAME, output)
    cv2.waitKey(0)
    cv2.destroyAllWindows()


def predict_webcam(model: YOLO, device_index: int = 0) -> None:
    cap = cv2.VideoCapture(device_index)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_H)

    if not cap.isOpened():
        raise RuntimeError(f"Cannot open camera: {device_index}")

    ear_hist = deque(maxlen=SMOOTH_N)
    last_ts = time.perf_counter()
    fps = 0.0

    try:
        cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(WINDOW_NAME, FRAME_W, FRAME_H)

        while True:
            ok, frame = cap.read()
            if not ok:
                break

            result = predict(model, frame)
            output = result.plot()
            draw_ear(frame, output, ear_hist)

            now = time.perf_counter()
            instant_fps = 1.0 / max(now - last_ts, 1e-6)
            fps = instant_fps if fps == 0.0 else (fps * 0.9) + (instant_fps * 0.1)
            last_ts = now
            draw_fps(output, fps)
            output = resize_for_display(output)

            cv2.imshow(WINDOW_NAME, output)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()


def main() -> None:
    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"Model not found: {MODEL_PATH}")

    model = YOLO(str(MODEL_PATH))

    if len(sys.argv) > 1:
        predict_image(model, sys.argv[1])
    else:
        predict_webcam(model)


if __name__ == "__main__":
    main()
