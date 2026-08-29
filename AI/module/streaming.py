from collections import defaultdict, deque
import math
import os
# from pymongo import MongoClient
import time
# import datetime
# import os
# from dotenv import load_dotenv

# load_dotenv()
# MONGODB_URL = os.getenv("MONGODB_URL")
# mongodb = MongoClient(MONGODB_URL, serverSelectionTimeoutMS=1000)
# db = mongodb['spotipy']
# col = db['sleepy']

EAR_THRESH = float(os.getenv("EAR_THRESH", "0.19"))
DEVICE_EAR_THRESHOLDS = {
    "phone": float(os.getenv("EAR_THRESH_PHONE", "0.095")),
    "mobile": float(os.getenv("EAR_THRESH_MOBILE", "0.095")),
    "laptop": float(os.getenv("EAR_THRESH_LAPTOP", str(EAR_THRESH))),
    "desktop": float(os.getenv("EAR_THRESH_DESKTOP", str(EAR_THRESH))),
}
MOBILE_DEVICE_HINTS = (
    "phone",
    "mobile",
    "iphone",
    "ipad",
    "ios",
    "android",
    "safari",
    "galaxy",
    "pixel",
)
DESKTOP_DEVICE_HINTS = ("laptop", "desktop", "macintosh", "mac os", "windows", "linux")
SMOOTH_N = 5
# SAVE_EVERY_N = 20
# processed_count = 0
latest_result = None
latest_results = {}

def euclidean(p1, p2) -> float:
    return math.dist(p1, p2)


def eye_ear(pts) -> float:
    p1, p2, p3, p4, p5, p6 = pts
    return (euclidean(p2, p6) + euclidean(p3, p5)) / (2.0 * euclidean(p1, p4) + 1e-6)

RIGHT_EYE_IDXS = [33, 160, 158, 133, 153, 144]
LEFT_EYE_IDXS  = [263, 387, 385, 362, 380, 373]

ear_hists = defaultdict(lambda: deque(maxlen=SMOOTH_N))


def _pick_keypoints(payload):
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        raise ValueError("invalid json")
    return (
        payload.get("keypoints")
        or payload.get("landmarks")
        or payload.get("faceLandmarks")
        or payload.get("face_landmarks")
    )


def _pick_direct_eye_points(payload):
    if not isinstance(payload, dict):
        return None

    right_eye = payload.get("rightEye") or payload.get("right_eye")
    left_eye = payload.get("leftEye") or payload.get("left_eye")
    if right_eye and left_eye:
        return (right_eye, left_eye)
    return None


def make_state_key(user_id=None, device="default"):
    device_key = str(device or "default").strip().lower() or "default"
    if user_id is None:
        return device_key
    return f"user:{user_id}:device:{device_key}"


def _device_key(payload):
    if not isinstance(payload, dict):
        return "default"

    device = (
        payload.get("device")
        or payload.get("deviceType")
        or payload.get("device_type")
        or payload.get("client")
        or payload.get("clientId")
        or payload.get("client_id")
        or "default"
    )
    return str(device).strip().lower() or "default"


def _state_key(payload, device):
    if not isinstance(payload, dict):
        return make_state_key(device=device)

    user_id = (
        payload.get("_auth_user_id")
        or payload.get("userId")
        or payload.get("user_id")
        or payload.get("memberId")
        or payload.get("member_id")
    )
    return make_state_key(user_id=user_id, device=device)


def _device_category(payload, device):
    if not isinstance(payload, dict):
        return device if device in DEVICE_EAR_THRESHOLDS else "default"

    hints = [
        device,
        payload.get("device"),
        payload.get("deviceType"),
        payload.get("device_type"),
        payload.get("platform"),
        payload.get("os"),
        payload.get("userAgent"),
        payload.get("user_agent"),
        payload.get("browser"),
    ]
    hint_text = " ".join(str(hint).lower() for hint in hints if hint)

    if any(hint in hint_text for hint in MOBILE_DEVICE_HINTS):
        return "phone"
    if any(hint in hint_text for hint in DESKTOP_DEVICE_HINTS):
        return "laptop"
    if device in DEVICE_EAR_THRESHOLDS:
        return device
    return "default"


def _ear_threshold(payload, device_category):
    if isinstance(payload, dict):
        threshold = payload.get("earThreshold", payload.get("ear_threshold"))
        if threshold is not None:
            try:
                return float(threshold)
            except (TypeError, ValueError):
                raise ValueError("invalid ear threshold")

    return DEVICE_EAR_THRESHOLDS.get(device_category, EAR_THRESH)


def _xy(point):
    if isinstance(point, dict):
        if "x" not in point or "y" not in point:
            raise ValueError("invalid keypoint")
        return (float(point["x"]), float(point["y"]))
    if isinstance(point, (list, tuple)) and len(point) >= 2:
        return (float(point[0]), float(point[1]))
    raise ValueError("invalid keypoint")


def _keypoint_at(keypoints, idx):
    if isinstance(keypoints, dict):
        if idx in keypoints:
            return keypoints[idx]
        return keypoints[str(idx)]
    return keypoints[idx]


def _eye_points(keypoints, indexes):
    try:
        return [_xy(_keypoint_at(keypoints, i)) for i in indexes]
    except (IndexError, KeyError, TypeError):
        raise ValueError("not enough keypoints")


def process_keypoints(payload):
    global latest_result

    device = _device_key(payload)
    device_category = _device_category(payload, device)
    ear_threshold = _ear_threshold(payload, device_category)
    state_key = _state_key(payload, device)
    keypoints = _pick_keypoints(payload)
    direct_eye_points = _pick_direct_eye_points(payload)

    if direct_eye_points:
        right_eye_pts = [_xy(point) for point in direct_eye_points[0]]
        left_eye_pts = [_xy(point) for point in direct_eye_points[1]]
        if len(right_eye_pts) != 6 or len(left_eye_pts) != 6:
            raise ValueError("each eye needs 6 keypoints")
    else:
        if not keypoints:
            raise ValueError("empty keypoints")
        right_eye_pts = _eye_points(keypoints, RIGHT_EYE_IDXS)
        left_eye_pts = _eye_points(keypoints, LEFT_EYE_IDXS)

    ear_r = eye_ear(right_eye_pts)
    ear_l = eye_ear(left_eye_pts)
    ear_value = (ear_r + ear_l) / 2.0
    ear_hist = ear_hists[state_key]
    ear_hist.append(ear_value)

    ear_smooth = sum(ear_hist) / len(ear_hist)
    status = "OPEN" if ear_smooth >= ear_threshold else "CLOSED"
    alarm = status == "CLOSED"
    result = {
        "ear": float(ear_value),
        "ear_smooth": float(ear_smooth),
        "ear_threshold": float(ear_threshold),
        "device": device,
        "device_category": device_category,
        "state_key": state_key,
        "status": status,
        "alarm": alarm,
    }
    latest_result = {**result, "right_eye": right_eye_pts, "left_eye": left_eye_pts}
    latest_results[state_key] = latest_result

    # processed_count += 1
    # if processed_count % SAVE_EVERY_N == 0:
    #     doc = {
    #         "timestamp": datetime.datetime.utcnow(),
    #         "ear_smooth": float(ear_smooth),
    #         "status": status,
    #     }
    #     try:
    #         col.insert_one(doc)
    #     except Exception as e:
    #         print(f"몽고디비 삽입 오류남\n{e}")

    return result


def _frame(text: str = "Waiting for keypoints...", result=None) -> bytes:
    import cv2
    import numpy as np

    font = cv2.FONT_HERSHEY_SIMPLEX
    canvas = np.zeros((360, 640, 3), dtype=np.uint8)
    cv2.putText(canvas, text, (20, 170), font, 0.8, (0, 255, 255), 2)

    if result:
        status = result["status"]
        color = (0, 255, 0) if status == "OPEN" else (0, 0, 255)
        cv2.putText(canvas, f"EAR: {result['ear_smooth']:.3f}  [{status}]", (20, 210), font, 0.8, color, 2)

        bar_max = 200
        ear_clamped = max(0.0, min(0.4, result["ear_smooth"]))
        bar_len = int((ear_clamped / 0.4) * bar_max)
        cv2.rectangle(canvas, (20, 225), (20 + bar_max, 245), (50, 50, 50), 1)
        cv2.rectangle(canvas, (20, 225), (20 + bar_len, 245), color, -1)

    ok, buf = cv2.imencode(".jpg", canvas)
    return buf.tobytes() if ok else b""


def generate(state_key=None):
    while True:
        result = latest_results.get(state_key) if state_key else latest_result
        frame_bytes = _frame(result=result) if result else _frame()
        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        time.sleep(0.05)
