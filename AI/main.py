import os
from typing import Any

from fastapi import Body, FastAPI, File, Query, Security, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from fastapi.security import HTTPAuthorizationCredentials
from auth.routes import bearer_scheme, current_user_from_token, optional_user_from_credentials, router as auth_router
from auth.storage import delete_expired_sessions, init_auth_storage, is_configured
from module.streaming import generate, make_state_key, process_keypoints
from module.yolo_detector import decode_base64_image, detect_yawn_bytes, detect_yawn_frame
# from pymongo import MongoClient
# import os

load_dotenv()


def _cors_origins() -> list[str]:
    origins = os.getenv("CORS_ALLOWED_ORIGINS")

    if origins:
        return [origin.strip() for origin in origins.split(",") if origin.strip()]

    return [
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "https://spoti.ingyuc.click",
    ]

OPENAPI_TAGS = [
    {"name": "health", "description": "서버 상태 확인 API"},
    {"name": "auth", "description": "회원가입, 로그인, 토큰 기반 사용자 확인 API"},
    {"name": "streaming", "description": "최근 EAR 결과를 multipart JPEG 스트림으로 제공"},
    {"name": "keypoints", "description": "얼굴 키포인트 기반 EAR 계산과 졸음 알람 판정"},
    {"name": "yawn", "description": "이미지 프레임 기반 YOLO 하품 감지"},
]

app = FastAPI(
    title="Spoti.py AI Server",
    description=(
        "Spoti.py의 AI 추론 서버입니다. "
        "로그인, 키포인트 기반 눈 감김 감지, YOLO 하품 감지, 결과 스트리밍을 제공합니다."
    ),
    version="0.1.0",
    openapi_tags=OPENAPI_TAGS,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_origin_regex=os.getenv("CORS_ALLOW_ORIGIN_REGEX"),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)


@app.on_event("startup")
async def startup():
    init_auth_storage()
    if is_configured():
        delete_expired_sessions()

# load_dotenv()
# MONGODB_URL = os.getenv("MONGODB_URL")
# client = MongoClient(MONGODB_URL, serverSelectionTimeoutMS=1000)
# db = client['spotipy']
# col = db['sleepy']

@app.get("/", tags=["health"], summary="서버 상태 확인")
async def root():
    return "ok"

@app.get(
    "/stream",
    tags=["streaming"],
    summary="최근 EAR 결과 스트리밍",
    description=(
        "multipart JPEG 스트림을 반환합니다. "
        "Authorization 헤더를 보내면 로그인 사용자와 device 기준으로 분리된 최근 결과를 보여줍니다."
    ),
)
async def stream(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
    device: str | None = Query(default=None, description="기기 구분값. 예: phone, laptop, browser UUID"),
):
    user = optional_user_from_credentials(credentials)
    state_key = make_state_key(user_id=user["id"], device=device) if user else None
    return StreamingResponse(generate(state_key), media_type="multipart/x-mixed-replace; boundary=frame")

@app.post(
    "/upload",
    tags=["keypoints"],
    summary="키포인트 업로드 및 EAR 분석",
    description=(
        "MediaPipe FaceMesh 키포인트 또는 양쪽 눈 6개 포인트를 받아 EAR, 눈 상태, 알람 여부를 반환합니다. "
        "Authorization 헤더를 보내면 사용자별로 EAR smoothing 상태가 분리됩니다."
    ),
)
async def upload(
    payload: Any = Body(
        ...,
        examples={
            "face_landmarks": {
                "summary": "FaceMesh 전체 키포인트",
                "value": {
                    "device": "phone",
                    "keypoints": {
                        "33": {"x": 0.35, "y": 0.42},
                        "160": {"x": 0.36, "y": 0.40},
                        "158": {"x": 0.38, "y": 0.40},
                        "133": {"x": 0.42, "y": 0.42},
                        "153": {"x": 0.38, "y": 0.44},
                        "144": {"x": 0.36, "y": 0.44},
                        "263": {"x": 0.58, "y": 0.42},
                        "387": {"x": 0.59, "y": 0.40},
                        "385": {"x": 0.61, "y": 0.40},
                        "362": {"x": 0.65, "y": 0.42},
                        "380": {"x": 0.61, "y": 0.44},
                        "373": {"x": 0.59, "y": 0.44}
                    }
                },
            }
        },
    ),
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
):
    try:
        user = optional_user_from_credentials(credentials)
        if user:
            payload = {"keypoints": payload, "_auth_user_id": user["id"]} if isinstance(payload, list) else {**payload, "_auth_user_id": user["id"]}
        result = process_keypoints(payload)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    return {"ok": True, **result}

@app.post(
    "/detect/yawn",
    tags=["yawn"],
    summary="이미지 업로드 및 하품 감지",
    description="multipart 이미지 파일을 YOLO 모델로 분석하고 하품 여부와 감지 박스를 반환합니다.",
)
async def detect_yawn(image: UploadFile = File(..., description="분석할 이미지 프레임")):
    try:
        image_bytes = await image.read()
        result = await run_in_threadpool(detect_yawn_bytes, image_bytes)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    return {"ok": True, **result}

@app.websocket("/ws/keypoints")
async def keypoints_ws(websocket: WebSocket):
    await websocket.accept()
    token = websocket.query_params.get("token")
    user = current_user_from_token(token) if token else None
    try:
        while True:
            try:
                payload = await websocket.receive_json()
                if user:
                    payload = {"keypoints": payload, "_auth_user_id": user["id"]} if isinstance(payload, list) else {**payload, "_auth_user_id": user["id"]}
                result = process_keypoints(payload)
                await websocket.send_json({"ok": True, **result})
            except ValueError as e:
                await websocket.send_json({"ok": False, "error": str(e)})
            except Exception as e:
                print(f"웹소켓 처리 오류남\n{e}")
                await websocket.send_json({"ok": False, "error": "internal server error"})
    except WebSocketDisconnect:
        pass

@app.websocket("/ws/yawn")
async def yawn_ws(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            try:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break
                if "bytes" in message and message["bytes"] is not None:
                    image_bytes = message["bytes"]
                    result = await run_in_threadpool(detect_yawn_bytes, image_bytes)
                elif "text" in message and message["text"] is not None:
                    frame = decode_base64_image(message["text"])
                    result = await run_in_threadpool(detect_yawn_frame, frame)
                else:
                    raise ValueError("empty frame")

                await websocket.send_json({"ok": True, **result})
            except ValueError as e:
                await websocket.send_json({"ok": False, "error": str(e)})
            except Exception as e:
                print(f"하품 웹소켓 처리 오류남\n{e}")
                await websocket.send_json({"ok": False, "error": "internal server error"})
    except WebSocketDisconnect:
        pass

# @app.post("/statistic")
# async def statistic():
#     doc = list(col.find().sort("timestamp", -1).limit(50))
#     for d in doc:
#         d["_id"] = str(d["_id"])
#     return {"data": doc}
