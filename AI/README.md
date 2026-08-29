# Spoti.py_AI — AI Server

간단한 소개
- 이 프로젝트는 Spoti.py_AI의 AI 서버입니다. FastAPI로 구현된 경량 마이크로서비스로, 비디오 프레임 스트리밍과 포즈(키포인트) 분석을 제공하여 모델 추론 파이프라인의 엔드포인트 역할을 합니다.

핵심 포인트
- 실시간 스트리밍: `/stream`에서 프레임을 multipart 스트림으로 전송합니다.
- 키포인트 처리: `/upload`(HTTP)와 `/ws/keypoints`(WebSocket)를 통해 키포인트 데이터를 받아 분석 결과를 반환합니다.
- 하품 감지: `/detect/yawn`(HTTP)와 `/ws/yawn`(WebSocket)를 통해 이미지 프레임을 YOLO 모델로 분석하고 하품 여부를 반환합니다.
- 단일 진입점: `main.py`가 FastAPI 앱을 노출합니다 — 배포 및 통합이 쉽습니다.

빠른 소개용 실행 예시
- 개발 환경에서 빠르게 띄우려면:

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

구성 및 위치
- `main.py`: FastAPI 엔트리포인트 (엔드포인트 정의 포함)
- `module/`: 프레임 전처리 및 스트리밍 로직 (`frameprocesser.py`, `streaming.py` 등)
- `models/bestM.pt`: 학습된 모델 파일(로컬에서 로드됨)
- `requirements.txt`: 필요한 Python 패키지 목록
- `Dockerfile`: 컨테이너 실행 구성



Swagger 문서
- 서버 실행 후 Swagger UI는 `http://localhost:8000/docs`에서 확인합니다.
- 로그인 후 Swagger UI 우측 상단 `Authorize` 버튼에 `access_token`을 넣으면 Bearer 인증 API를 바로 테스트할 수 있습니다.
- OpenAPI JSON은 `http://localhost:8000/openapi.json`에서 확인합니다.
- WebSocket 엔드포인트(`/ws/keypoints`, `/ws/yawn`)는 OpenAPI 표준상 Swagger UI에 자동 표시되지 않으므로 아래 사용 시나리오를 참고하세요.

로그인 API
- 회원가입: `POST /auth/signup`

```json
{
  "username": "user01",
  "nickname": "사용자",
  "password": "password123",
  "passwordConfirm": "password123"
}
```

- 로그인: `POST /auth/login`

```json
{
  "username": "user01",
  "password": "password123"
}
```

- 로그인 응답의 `access_token`은 이후 요청에서 `Authorization: Bearer <token>` 형식으로 보냅니다.
- 현재 사용자 확인: `GET /auth/me`
- 로그아웃: `POST /auth/logout`

MySQL 환경변수
- `.env` 또는 실행 환경에 아래 값을 설정하면 서버 시작 시 `users`, `auth_sessions` 테이블을 자동 생성합니다.

```bash
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=spotipy
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=spotipy
AUTH_TOKEN_EXPIRE_DAYS=7
CORS_ALLOWED_ORIGINS=https://your-frontend-domain.example,https://spoti.ingyuc.click
```

간단한 사용 시나리오
- 웹캠이나 비디오 소스에서 프레임을 스트리밍하고, 추출한 키포인트를 `/upload`로 제출하면 처리 결과(JSON)를 받습니다. 실시간 인터랙션이 필요하면 `/ws/keypoints`로 WebSocket 연결 후 JSON을 주고받으세요.
- 디바이스별 EAR 기준치를 다르게 쓰려면 키포인트 JSON에 `"device": "phone"` 또는 `"device": "laptop"`을 함께 보내세요. 직접 튜닝할 때는 `"earThreshold": 0.095`처럼 보내면 해당 요청에서 우선 적용됩니다.
- 카메라 프레임을 `/detect/yawn`에 multipart 이미지로 보내거나 `/ws/yawn`에 바이너리 이미지 프레임으로 보내면 `"yawning": true/false` 응답을 받습니다.
- 눈 감김 상태가 감지되면 응답에 `"alarm": true`가 포함됩니다. 프론트에서는 이 값을 보고 경고음을 켜고, `"alarm": false`가 오면 끄면 됩니다.

주의 및 참고사항
- 의존성(OpenCV, MediaPipe 등)은 `requirements.txt`를 확인하세요.
- MongoDB 연동 코드는 현재 주석 처리되어 있습니다. 필요 시 환경변수를 설정하고 관련 코드를 활성화하세요.
