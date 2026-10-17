# Spring 연동 명세 — Model H API v2

이 문서는 운영 주소·키·데이터를 제외한 공개 계약입니다. 실제 접속 설정은 승인된 운영 채널에서 전달받습니다. v2는 응답 계약 버전이며 경로는 `/health`, `/predict` 그대로입니다.

## 다음 구현자의 순서

1. 기존 Spring의 인증·스캔·품목 조회·저장 구조와 의존성 버전을 확인합니다.
2. 서버 측 설정으로 추론 base URL과 API 키를 공급합니다. 브라우저에서 추론 서버에 직접 연결하지 않습니다.
3. 현재 Spring 실행 환경에서 인증된 health 요청과 사진 업로드를 확인합니다.
4. 아래 JSON 계약에 맞는 DTO와 HTTP 클라이언트를 구현하고 정상·빈 결과·경고·오류를 테스트합니다.
5. 실제 Spring 애플리케이션의 사용자-facing API를 통해 호출·저장·응답을 검증합니다. 컨테이너에서 curl이 성공한 것만으로 Java 연동 완료로 판단하지 않습니다.

## 책임 경계

- 추론 서버: 사진 한 장에서 단일/다중 알약 인식, 검출별 Top-1·점수·품목 식별자·위치·통합 경고 반환.
- Spring: 사용자 인증, 요청 제어, 식약처/DB 조회, 품목 정보 연결과 비즈니스 처리.
- 프론트: 사진 입력과 결과·점수·태그 표시.

현재 추론 서버는 사진·크롭을 영구 보관하지 않으며 이미지 URL을 반환하지 않습니다. 원본 보존·대표 썸네일·사용자 결과 저장은 별도 작업입니다. 이 명세는 식약처 조회 위치를 변경하는 후속 제안을 구현한 상태가 아닙니다.

## 공통 인증

모든 요청에 `X-API-Key` 헤더를 보냅니다. base URL과 키는 서버 설정에서 공급하고 TLS를 정상 검증합니다. 실제 주소·키를 소스·URL 쿼리·명령행 인자·로그·프론트 응답에 기록하지 않습니다.

`/docs`, `/redoc`, `/openapi.json`은 비활성화돼 있습니다.

## GET /health

본문이 없는 인증 요청입니다. HTTP 200 응답 구조:

```json
{
  "status": "ready",
  "model": "H",
  "device": "cuda:0",
  "class_count": 150,
  "model_sha256": "<runtime SHA-256>",
  "mapping_sha256": "<runtime SHA-256>"
}
```

해시는 모델·매핑 버전 대조용입니다. health 성공은 실사진 인식 정확도나 GPU가 현재 비어 있다는 보장이 아닙니다.

## POST /predict

| 항목 | 계약 |
|---|---|
| 요청 Content-Type | multipart/form-data |
| 필수 필드 | `file`: JPEG/PNG 파일 한 장 |
| 파일 제한 | 10 MiB |
| 요청 전체 제한 | 11 MiB |
| 이미지 제한 | 20,000,000픽셀 |
| 미지원 입력 | JSON/Base64, 이미지 URL, 여러 사진 batch |

HTTP 클라이언트가 multipart boundary를 생성하게 하고 filename과 파일 MIME을 포함합니다. 파일 내용을 문자열 form field로 보내지 않습니다. JPEG/PNG 내용이 실제로 검사되며 애니메이션·손상 파일은 거절합니다.

요청 구조 예시:

```http
POST /predict HTTP/1.1
X-API-Key: <server-side secret>
Content-Type: multipart/form-data; boundary=example-boundary

--example-boundary
Content-Disposition: form-data; name="file"; filename="pill.jpg"
Content-Type: image/jpeg

<image bytes>
--example-boundary--
```

설명용 성공 응답입니다. 아래 식별자·점수·좌표는 가상 값이며 실제 품목 데이터가 아닙니다.

```json
{
  "model": "H",
  "model_sha256": "<runtime SHA-256>",
  "mapping_sha256": "<runtime SHA-256>",
  "image": {"width": 1200, "height": 1600},
  "predictions": [
    {
      "detection_id": 1,
      "class_id": 0,
      "item_seq": "000000001",
      "confidence": 0.95,
      "bbox_xyxy": [0.1, 0.1, 0.3, 0.3],
      "recognition_may_be_degraded": false
    },
    {
      "detection_id": 2,
      "class_id": 0,
      "item_seq": "000000001",
      "confidence": 0.64,
      "bbox_xyxy": [0.6, 0.6, 0.9, 0.9],
      "recognition_may_be_degraded": true
    }
  ]
}
```

단일 알약은 predictions에 한 항목, 다중 알약은 여러 항목이 들어갑니다. 미검출도 HTTP 200이며 predictions는 빈 배열입니다.

### DTO 매핑과 결과 의미

| 필드 | 타입 / 의미 |
|---|---|
| `model` | 문자열 H |
| `model_sha256`, `mapping_sha256` | 문자열; 실행 중인 모델과 매핑 버전 |
| `image.width`, `image.height` | 정수; EXIF 방향 보정 후 이미지 크기 |
| `predictions` | 검출 결과 배열 |
| `detection_id` | 1부터 시작하는 응답 내 순번; 영구 ID가 아님 |
| `class_id` | 정수 0~149; 모델 내부 클래스 |
| `item_seq` | 숫자 문자열; 식약처/DB 품목 연결 키 |
| `confidence` | 0~1 실수 모델 점수 |
| `bbox_xyxy` | 정규화 좌표 `[x1,y1,x2,y2]` |
| `recognition_may_be_degraded` | 인식 저하 가능성 boolean |

snake_case 이름을 DTO에 정확히 연결하고 item_seq를 문자열로 보존합니다. 같은 품목을 두 번 검출하면 동일 item_seq와 서로 다른 detection_id로 반환하므로 item_seq로 배열을 합치지 않습니다. 기존 모델 검출 순서를 유지하며, 검출 수가 실제 물리 알약 수와 항상 같지는 않습니다.

박스를 픽셀로 표시할 때 x는 image.width, y는 image.height를 곱합니다. 표시하는 원본도 EXIF 방향을 일치시킵니다. confidence를 퍼센트로 표시할 수 있지만 정답일 확률로 보장하지 않습니다.

구버전의 candidates, needs_review, review_reasons, conflict_group_id는 공개 응답에 없습니다. Top-3 후보를 DTO 필수 필드로 요구하지 않습니다.

### 통합 경고

다음 내부 조건 중 하나 이상이면 recognition_may_be_degraded가 true입니다.

- Top-1 < 0.90.
- Top-1과 Top-2 점수 차이 < 0.20.
- 다른 클래스 검출 박스와 IoU >= 0.50.

태그는 **인식 저하 가능성**으로 표시하고, 클릭/hover 시 공통 도움말을 제공할 수 있습니다. 검출별 상세 사유는 전달하지 않습니다. 낮은 점수나 태그 때문에 결과를 차단하거나 재촬영을 강제하지 않습니다.

공통 도움말 예시: “점수가 낮거나 비슷한 후보가 경합하거나 검출 영역이 겹치면 인식이 불확실할 수 있습니다. 흐림, 조명·반사, 작은 알약 크기, 가림, 촬영 각도, 학습하지 않은 품목도 결과에 영향을 줄 수 있습니다. 표시된 점수는 정답일 확률을 보장하지 않습니다.”

촬영 환경 요인은 일반적인 가능성 안내이며 서버가 각각 측정한 원인이 아닙니다. 모든 저하 요인을 탐지하는 필드가 아니며 false도 정확성 보장이 아닙니다. 현재 지원 범위는 학습한 150품목이고, 학습 외 품목을 자동 거절하는 기능은 없습니다.

검출 보존 임계값 0.25는 태그 기준과 별개입니다. 이번 계약은 기존 검출/NMS 설정을 변경하거나 겹친 결과를 추가 병합하지 않습니다.

## 오류와 동시 처리

| HTTP | 의미 / 처리 |
|---|---|
| 400 | 빈 이미지 등 잘못된 요청 |
| 401 | 키 누락/불일치; 사용자 로그인 오류와 구분 |
| 413 | 파일·전체 요청·픽셀 제한 초과 |
| 415 | 지원하지 않는 형식·손상·애니메이션 |
| 422 | 필수 file 필드 등 요청 형식 오류 |
| 503 | 준비되지 않음 또는 추론 중; busy는 Retry-After: 1 포함 |
| 500 | 내부 추론 실패; 정상 인식 결과로 처리하지 않음 |

일반 오류는 detail 필드를 포함하지만 요청 검증 오류의 detail은 문자열이 아니라 구조화된 배열일 수 있습니다. 이를 단일 문자열로 가정하지 않습니다.

모델 추론은 한 번에 한 요청만 실행하고 무제한 큐를 두지 않습니다. Spring의 연결/응답 timeout과 제한 재시도를 명시하고 Retry-After를 존중합니다. 4xx를 무조건 재시도하지 않습니다. timeout 이후 GPU 작업이 즉시 취소됐다고 가정하지 않으며, 결과 저장에는 중복 저장 방지 정책이 필요합니다.

## Spring 연동 완료 기준

- 실제 Spring 엔드포인트에서 multipart 업로드 → 추론 응답 → DTO → item_seq 품목 연결이 성공합니다.
- 단일/다중/동일 품목 여러 알/빈 결과/통합 경고를 보존합니다.
- 인증 실패, busy, timeout, 입력 오류, 내부 실패를 구분해 테스트합니다.
- 서버 API 키가 프론트·응답·로그·Git에 노출되지 않습니다.
- 원본 보존·사용자 결과 저장은 추론 API와 별도 책임으로 구현하고 실패 정책을 명시합니다.
- 현재 배포된 Spring 애플리케이션을 경유한 실제 요청으로 확인합니다. 과거 컨테이너 통신 검증은 당시의 네트워크 증거일 뿐 현재 기능 연동을 대신하지 않습니다.
