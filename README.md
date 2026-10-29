# Gemma 3 12B + LightRAG 한국어 실습

Ollama의 `gemma3:12b`로 개체·관계를 추출하고 답변을 생성합니다.
검색용 임베딩 모델은 `bge-m3`입니다. Gemma 모델 자체는 임베딩용으로 사용하지 않습니다.
Neo4j, 외부 LLM API, API 키는 필요하지 않습니다. 최초 패키지·모델·토크나이저 다운로드에는 인터넷이 필요합니다.

## 1. 구성

| 파일 | 용도 |
|---|---|
| app.py | Ollama 연결, 문서 색인, 검색·답변, CLI, 웹 API |
| index.html | 질문 입력·모드 비교·검색 근거·개체/관계 목록 웹 화면 |
| graph.js | 개체·관계 SVG 시각화, 검색·확대·드래그·상세 설명 |
| docs/01_projects.txt | 프로젝트·책임자·운영 담당자 |
| docs/02_systems.txt | 시스템·공급사·DB·공유 스토리지 |
| docs/03_operations.txt | 기술지원 담당자·계약금액·백업·장애 대응 |
| questions.json | 테스트 질문 5개와 기대 답안·출처 |
| .env.example | Ollama 주소·모델·색인 저장 폴더 설정 |
| requirements.txt | Python 의존성. LightRAG는 1.5.7로 고정 |

문서와 질문의 회사·인물·계약정보는 모두 가상입니다.

## 2. 모델 준비 — Ollama가 실행되는 서버에서

```bash
ollama pull gemma3:12b
ollama pull bge-m3
ollama list
```

이미 설치되어 있으면 다시 받을 필요가 없습니다. Ollama가 실행 중이어야 합니다.
모델 두 개를 사용하는 이유는 역할이 다르기 때문입니다.

- `gemma3:12b`: 문서를 읽고 개체/관계 추출, 질의 키워드 추출, 답변 생성
- `bge-m3`: 문서·개체·관계·질문을 검색용 벡터로 변환

GPU 메모리 상황에 따라 두 모델의 로딩/교체가 발생할 수 있습니다. 최초 색인은 단순 질문보다 시간이 오래 걸립니다.

## 3. 설치 — Python 3.12 권장

ZIP을 풀고 `app.py`가 들어 있는 폴더에서 실행합니다.

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

가상환경 활성화가 차단되어도 위 방식은 실행할 수 있습니다. 아래 설명의 `python`은 Windows에서는
`.\.venv\Scripts\python.exe`로 바꾸거나, `.\.venv\Scripts\Activate.ps1`로 가상환경을 활성화한 뒤 사용하세요.

Ubuntu:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

`lightrag`라는 다른 패키지 대신 **lightrag-hku**를 설치합니다.

## 4. Ollama 주소 설정

같은 PC에 Ollama가 있다면 `.env` 기본값을 그대로 씁니다.

```dotenv
OLLAMA_BASE_URL=http://localhost:11434
LLM_MODEL=gemma3:12b
EMBED_MODEL=bge-m3
NUM_CTX=16384
OLLAMA_TIMEOUT=900
WORKING_DIR=./rag_storage
```

`OLLAMA_BASE_URL`에 `/api` 또는 `/v1`을 붙이지 않습니다.
현재 셸에 같은 이름의 환경변수가 있으면 `.env`보다 우선합니다.

Kubernetes의 Ollama에 PC에서 접속한다면 별도 터미널에서 다음을 계속 실행합니다.

```powershell
kubectl port-forward svc/ollama 11435:11434
```

이때 `.env`를 다음처럼 바꿉니다.

```dotenv
OLLAMA_BASE_URL=http://localhost:11435
```

Ollama가 다른 네임스페이스에 있으면 `kubectl -n 해당네임스페이스 port-forward ...`를 사용합니다.
모델 pull도 해당 Ollama가 실행되는 환경에서 해야 합니다. 예:

```powershell
kubectl exec deployment/ollama -- ollama pull gemma3:12b
kubectl exec deployment/ollama -- ollama pull bge-m3
```

실습 코드도 같은 Kubernetes 클러스터 내 Pod에서 실행한다면 주소는 보통
`http://ollama.default.svc.cluster.local:11434`입니다. PC에서는 이 내부 DNS 주소를 사용하지 않습니다.

## 5. 연결 검사 → 문서 색인

```powershell
python app.py check
python app.py ingest
```

`check`는 모델 존재와 실제 임베딩 호출을 검사합니다. Gemma 생성 자체의 실행은 `ingest`에서 확인됩니다.
`ingest`는 문서마다 청킹 → 개체/관계 추출 → 그래프·벡터 저장을 수행합니다.
성공하면 문서 처리 상태에 `processed: 3`이 표시됩니다. 실패 상태가 있으면 종료코드 1로 끝납니다.

`rag_storage`는 생성된 색인·그래프·LLM 캐시를 보관합니다. 종료 후에도 유지되며 다음 실행에서 재사용됩니다.
동일 문서를 다시 ingest하면 중복 등록을 피합니다.
문서 추가는 `docs`에 UTF-8 `.txt`를 넣고 다시 ingest하면 됩니다.
기존 파일을 수정하면 이 실습 코드는 변경을 감지하고 재색인을 안내합니다. 문서 내용을 변경하거나
모델·임베딩·청킹 설정을 바꿨다면 `WORKING_DIR=./rag_storage_v2`처럼 새 폴더로 바꾸고 전체 색인을 다시 만드세요.
실패 후 재시도도 새 WORKING_DIR로 실행하면 기존 실패 상태와 분리할 수 있습니다.

## 6. 웹에서 질문

색인 명령이 끝난 뒤 실행합니다.

```powershell
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

브라우저: http://127.0.0.1:8000

1. 테스트 질문을 선택하거나 직접 입력합니다.
2. `질문 실행` 또는 `naive / hybrid / mix 비교`를 누릅니다.
3. `검색 근거만 보기`를 선택하면 답변 생성 대신 실제 검색 문맥을 확인할 수 있습니다.
4. 하단 `추출된 지식 그래프의 개체·관계 확인`에서 관계 목록을 확인합니다.

비교는 GPU 부하를 줄이기 위해 순차 실행합니다. 관계 목록과 노드·연결선 그래프를 함께 보여줍니다.
그래프에서 개체명 검색, 확대·축소, 노드 이동, 개체·관계 설명 및 출처 확인이 가능합니다.
이 서버는 로컬 실습용이며 인증 기능은 없습니다.

**같은 WORKING_DIR을 쓰는 웹 서버와 별도 CLI를 동시에 실행하지 마세요.**
기본 파일 저장소를 사용하는 실습이므로 웹 서버는 `--workers 1` 기본값으로 사용하고,
`--reload`도 사용하지 마세요. 문서를 추가할 때는 웹 서버를 종료하고 ingest한 다음 다시 시작합니다.

## 7. CLI로도 실습 가능

```powershell
python app.py ask "김민수가 책임자인 프로젝트에서 사용하는 시스템의 공급사와 그 공급사의 기술지원 담당자는 누구인가?" --mode mix
python app.py compare "은하스토리지에 장애가 발생하면 어떤 프로젝트의 운영 담당자에게 통보해야 하는가?"
python app.py ask "김민수가 담당하는 시스템의 공급사는?" --mode hybrid --context
python app.py graph
```

| 모드 | 검색 방식 |
|---|---|
| naive | 문서 청크 벡터 검색. 그래프 관계 검색은 사용하지 않음 |
| local | 개체 중심 그래프 검색 |
| global | 관계 중심 그래프 검색 |
| hybrid | local + global |
| mix | 그래프 검색 + 문서 청크 벡터 검색 |

이 실습은 재순위화 모델을 설치하지 않으므로 `enable_rerank=False`로 설정했습니다.
`global`은 여기서 관계 중심 검색을 의미하며 Microsoft GraphRAG의 커뮤니티 요약 검색과 동일한 구현은 아닙니다.

## 8. 테스트 질문과 정답

### 질문 1 — 세 문서 연결

김민수가 책임자인 프로젝트에서 사용하는 시스템의 공급사와 그 공급사의 기술지원 담당자는 누구인가?

기대 경로: 김민수 → 차세대 주문관리 프로젝트 → 오로라ERP → 새봄소프트 → 정하늘.

### 질문 2 — 관계를 찾고 계약금액 조회

박지영이 책임자인 프로젝트에서 사용하는 시스템의 공급사와 연간 유지보수 계약금액은?

기대 경로: 박지영 → 고객분석 프로젝트 → 루멘분석플랫폼 → 다온데이터. 연간 1800만 원.

### 질문 3 — 공통 서비스 장애의 영향 범위

은하스토리지에 장애가 발생하면 어떤 프로젝트가 영향을 받고, 각 프로젝트의 운영 담당자 중 누구에게 통보해야 하는가?

기대 답: 차세대 주문관리 프로젝트의 이서준, 고객분석 프로젝트의 최유진.
두 시스템이 은하스토리지를 공유한다. 책임자인 김민수·박지영과 운영 담당자를 구분해야 한다.

### 질문 4 — 데이터베이스와 운영정책 연결

김민수가 책임자인 프로젝트의 시스템이 사용하는 데이터베이스의 DBMS, 백업 시각, 백업 보관 기간은?

기대 답: 주문DB, MySQL, 매일 오전 2시, 30일.

### 질문 5 — 없는 정보에 대한 추측 방지

정하늘의 전화번호와 새봄소프트 계약 종료일은?

기대 답: 문서에 없어 확인할 수 없음.

## 9. 결과 해석

- 3개 문서는 작아서 naive도 모든 근거를 찾아 정답을 맞힐 수 있습니다. 그래프 모드의 우월성을 보장하는 벤치마크는 아닙니다.
- 그래프 RAG는 그래프만 읽는 고정 경로 질의가 아닙니다. 추출된 개체·관계 및 관련 원문을 검색해 LLM에 제공합니다.
- 답변이 맞는지뿐 아니라 검색 근거에 필요한 문서가 포함됐는지, 개체/관계가 정확한지 확인하세요.
- Gemma가 개체명을 다르게 표기하거나 관계를 누락하면 답변 정확도가 낮아질 수 있습니다.
- 처음에는 같은 질문을 여러 모드로 비교하고, 이후 관련 없는 문서를 추가해 차이를 관찰하세요.
- 그래프 추출 비용은 색인 때 발생합니다. 그래프를 쓴다고 검색과 답변이 항상 빨라지는 것은 아닙니다.
- 같은 질문 재실행은 캐시·모델 워밍업 영향을 받으므로 화면의 소요시간은 엄밀한 성능 벤치마크가 아닙니다.

## 10. 오류 해결

- 연결 거부: Ollama 실행 여부, 포트포워딩 유지 여부, `.env` 주소 확인.
- 모델 없음: `ollama list`를 확인한 뒤 **서버 쪽**에서 필요한 모델 pull.
- 컨텍스트 오류: NUM_CTX를 줄이지 말고 우선 동시 실행 작업을 중지. 메모리 상황에 맞춰 새 실험 설정을 사용하세요.
- 시간이 오래 걸림: 최초 모델 로딩 및 관계 추출은 질문 한 번보다 비쌉니다. 코드의 병렬 호출 수는 1입니다.
- 인증서/프록시 환경의 SOCKS 오류: 필요할 경우 `python -m pip install "httpx[socks]"` 실행.
- 색인 실패: 터미널의 LightRAG 원인 로그 확인. 실패 문서가 있어도 겉으로 완료된 것처럼 보이지 않도록 상태를 검사합니다.

## 검증 범위

LightRAG 1.5.7 설치 후 실제 저장소·문서 3개 색인·그래프 생성·검색 모드(naive/hybrid/mix)·웹 경로 점검을 통과했습니다.
Ollama 모의 HTTP 서버를 통해 /api/tags, /api/embed, /api/chat 요청과 모델명 전달도 확인했습니다.
개발 환경에는 사용자의 Ollama/GPU 연결이 없어 실제 Gemma 답변의 품질이나 속도는 확인하지 못했습니다.
mock LLM/임베딩을 이용한 파이프라인 점검은 실제 모델 정확도 검증과 구분됩니다.

## 공식 참고 자료

- https://github.com/HKUDS/LightRAG
- https://github.com/HKUDS/LightRAG/blob/main/examples/lightrag_ollama_demo.py

제공된 예제 코드는 학습용이며 특정 조직의 실제 시스템·계약정보를 포함하지 않습니다.
