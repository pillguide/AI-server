# 약학다식 · PillGuide AI-server

사진 한 장 속 단일·다중 알약을 인식하는 **약학다식 Model H 추론 서버**입니다. 로컬 데스크톱 GPU에서 실행되며, 검출된 알약마다 **Top-1 · confidence · item_seq · 위치 · 인식 저하 가능성**을 Spring에 반환합니다.

## 아키텍처와 책임

```text
Frontend → Spring (EC2 / K3s)
               ├─ 식약처 OpenAPI / DB → 품목 정보·사용자 데이터 처리
               └─ Tailscale / HTTPS → FastAPI (로컬 데스크톱)
                                         └─ Model H / GPU 추론
```

**식약처 조회는 Spring의 책임입니다.** 이 서버는 인식만 담당하며 사용자 사진 저장, 대표 이미지 생성, 병용 판단을 수행하지 않습니다. 브라우저 직접 호출 대신 서버 간 인증된 사설 연결을 사용합니다.

Python 3.12 · FastAPI · PyTorch / CUDA · Ultralytics 기반입니다. 기본 실행 장치는 `cuda:0`이며, GPU가 없다고 자동으로 CPU로 대체하지 않습니다.

## API 요약

모든 요청에 `X-API-Key`가 필요합니다. `/docs`, `/redoc`, `/openapi.json`은 비활성화돼 있습니다.

| API | 입력 / 출력 |
|---|---|
| `GET /health` | 모델·장치·클래스 수·모델/매핑 버전 확인 |
| `POST /predict` | multipart `file` 한 장 → 이미지 크기와 검출 결과 배열 |

- JPEG/PNG, 파일 10 MiB·전체 요청 11 MiB·20,000,000픽셀 제한.
- 각 결과: `detection_id`, `class_id`, `item_seq`, `confidence`, `bbox_xyxy`, `recognition_may_be_degraded`.
- 같은 품목이 여러 알이면 개별 결과로 유지합니다. 낮은 점수만으로 재촬영을 강제하지 않으며, 미검출은 빈 배열입니다.
- **[Spring 연동 명세](docs/SPRING_INTEGRATION.md)**에 입출력 예시, 필드 의미, 오류·동시 처리, 완료 기준을 정리했습니다.

## 공개 범위와 실행 준비

이 저장소는 **최소 소스 묶음**으로, clone만으로 실행되지 않습니다. 모델·품목 매핑·실제 설정·키·데이터셋·샘플·운영 스크립트·로컬 검증 자료는 공개하지 않습니다. `.gitignore`는 승인된 파일만 허용합니다.

1. Windows Python 3.12, NVIDIA GPU/드라이버와 전용 가상환경을 준비하고 두 requirements 파일의 의존성을 설치합니다. CUDA PyTorch 의존성을 먼저 설치합니다.
2. 승인된 비공개 경로에서 `model/final_H.pt`, `model/classes.json`을 공급합니다. 매핑은 클래스 0~149의 `class_id`, 모델과 일치하는 `product_code`, 고유한 숫자 문자열 `item_seq`를 포함합니다.
3. 실제 설정이 없는 새 환경에서만 [설정 템플릿](config/inference.example.json)을 `config/inference.json`으로 복사하고, 신뢰할 수 있는 모델·매핑 SHA-256을 채웁니다. 기존 자산을 덮어쓰거나 검증을 우회하지 않습니다.
4. 최소 32자의 무작위 `PILLGUIDE_API_KEY`를 서버 환경에 안전하게 주입하고 저장소 루트에서 실행합니다.

```text
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

API 키·실제 운영 주소는 별도 승인 채널로 전달합니다. 공용 포트 개방과 자동 시작 설정은 이 저장소가 수행하지 않습니다.

## 코드 구조

| 파일 | 역할 |
|---|---|
| `app/main.py` | 인증, 업로드 제한, 이미지 디코딩, API·동시 처리 |
| `app/engine.py` | 모델 로딩, 검출·후처리 |
| `app/contract.py` | 응답 모델, 품목 매핑 검증·변환 |
| `app/config.py` | 패키지 경로와 서버 설정 |

## 검증 범위와 한계

학습한 **150품목**만 지원하며, 학습 외 품목을 자동 거절하지 못합니다. confidence는 정답일 확률이 아니고, 경고가 false여도 정확성을 보장하지 않습니다.

2026-10-18 비공개 환경에서 단위 테스트 17개, GPU·HTTP 각각 기준 사진 6장, 실제 백엔드 컨테이너 두 개의 총 12건 요청을 확인했습니다. 이는 실촬영 정확도 평가·부하 시험 또는 Spring 애플리케이션 연동 완료를 뜻하지 않습니다.

## 연결 문서

- [Spring 연동 명세](docs/SPRING_INTEGRATION.md) · [의존성 고지](licenses/NOTICE.txt) · [Ultralytics AGPL-3.0](licenses/Ultralytics-AGPL-3.0.txt)
- [Backend — 비즈니스 처리](https://github.com/pillguide/Backend) · [Frontend — 사용자 화면](https://github.com/pillguide/Frontend) · [manifest — 배포 설정](https://github.com/pillguide/manifest)

의존성 고지는 별도의 프로젝트 라이선스를 새로 부여한다는 의미가 아닙니다.
