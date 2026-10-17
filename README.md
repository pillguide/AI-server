# PillGuide Model H inference API

사진 한 장 속 단일/다중 알약을 인식하는 FastAPI 서버의 최소 소스 저장소입니다. 검출마다 Top-1 품목 식별자, 모델 점수, 위치와 인식 저하 가능성을 반환합니다.

## Spring 연동

요청·응답 형식, 예제, DTO 매핑, 오류 처리와 완료 기준은 [Spring 연동 명세](docs/SPRING_INTEGRATION.md)를 참고하세요. 실제 운영 주소와 API 키는 이 저장소에 포함하지 않습니다.

## 공개 범위

이 저장소는 실행 가능한 전체 배포 묶음이 아닙니다. 모델 가중치, 품목 매핑, 실제 설정, 키, 데이터셋, 샘플 사진, 실행/운영 스크립트, 검증 출력과 로컬 테스트는 별도로 보관합니다. 모델 자산 없이 clone만으로 서버를 기동할 수 없습니다.

`.gitignore`는 기본적으로 모든 파일을 제외하고 승인된 파일명만 허용합니다. 새 공개 파일을 추가할 때는 내용 검토 후 allowlist를 함께 수정하세요. 강제 추가는 사용하지 않으며, 커밋 전 실제 staged diff를 확인합니다. 이미 추적된 파일은 `.gitignore`만으로 보호되지 않습니다.

## 코드 구성

| 파일 | 역할 |
|---|---|
| `app/main.py` | 인증, 업로드 제한, 이미지 디코딩, API 및 단일 추론 처리 |
| `app/engine.py` | 모델 로딩, 기존 검출·후처리 |
| `app/contract.py` | 품목 식별자 검증·매핑, 공개 응답 모델 |
| `app/config.py` | 패키지 경로와 서버 환경 설정 |
| `config/inference.example.json` | 실제 파일 해시가 없는 설정 템플릿 |
| `requirements-*.txt` | 검증 환경의 Python 의존성 |

## 로컬 자산을 가진 운영자의 준비 절차

1. Windows Python 3.12와 CUDA를 사용할 수 있는 NVIDIA GPU/드라이버를 준비합니다. 기본 추론 장치는 `cuda:0`이며 CPU로 조용히 대체하지 않습니다.
2. 프로젝트 전용 가상환경에서 `requirements-torch-windows.txt`, `requirements-windows.txt` 순서로 의존성을 설치합니다.
3. 승인된 비공개 경로에서 `model/final_H.pt`, `model/classes.json`을 공급합니다. 기존 로컬 자산은 덮어쓰지 않습니다.
4. `config/inference.json`이 없는 새 환경에서만 `config/inference.example.json`을 복사합니다. 두 해시 placeholder를 신뢰할 수 있는 모델 패키지의 SHA-256으로 바꿉니다. 검증 실패를 통과시키기 위해 임의 파일의 해시로 바꾸지 않습니다.
5. `PILLGUIDE_API_KEY`에 최소 32자의 무작위 비밀 키를 안전하게 주입합니다. 저장소·명령행 인자·로그·프론트에 키를 넣지 않습니다.
6. 해당 가상환경과 프로젝트 루트에서 다음 명령으로 실행합니다.

```text
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

네트워크 연결은 인증된 사설 경로와 TLS를 사용합니다. 공용 포트 개방이나 자동 시작 설정은 이 저장소가 수행하지 않습니다. `/health`와 `/predict` 모두 API 키가 필요하며 `/docs`, `/redoc`, `/openapi.json`은 비활성화돼 있습니다.

품목 매핑은 클래스 0~149의 고유한 `class_id`, 모델과 일치하는 `product_code`, 고유한 숫자 문자열 `item_seq`를 포함해야 합니다. 실제 매핑 내용은 공개하지 않습니다.

## 검증 범위와 한계

2026-10-18 로컬 비공개 검증 환경에서 단위 테스트 17개, GPU 및 HTTP 각각 기준 사진 6장, 실제 백엔드 컨테이너 두 개에서 총 12건의 사진 요청을 확인했습니다. 검증 데이터·운영 로그는 공개 묶음에서 제외했습니다. 이는 새 실촬영 정확도 평가나 부하 시험, Spring 애플리케이션 연동 완료를 뜻하지 않습니다.

현재 모델의 지원 범위는 학습한 150품목입니다. 지원 외 품목을 자동으로 거절하지 못하며, confidence는 검증된 정답 확률이 아닙니다. 서버는 식약처 조회, 사용자 사진 저장, 품목 대표 이미지 생성, 병용 판단을 수행하지 않습니다.

기존 의존성 고지는 [NOTICE](licenses/NOTICE.txt)와 [Ultralytics 라이선스](licenses/Ultralytics-AGPL-3.0.txt)를 참고하세요. 의존성 고지는 별도의 프로젝트 라이선스를 새로 부여한다는 의미가 아닙니다.
