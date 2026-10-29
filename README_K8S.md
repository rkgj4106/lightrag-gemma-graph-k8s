# Kubernetes 실행 방법 — 여기부터 읽으세요

이 패키지는 기존 Gemma + LightRAG 실습에 Dockerfile과 Kubernetes YAML을 추가한 전체 코드입니다.
원래 README.md는 로컬 실행 설명이며, Kubernetes에서는 이 파일의 절차를 따릅니다.

## 실행 구조

| 구성요소 | 위치·역할 |
|---|---|
| LightRAG + FastAPI 웹 앱 | 새로 배포하는 lightrag Pod, CPU 사용 |
| 문서 색인 init container | 같은 Pod에서 웹 서버보다 먼저 실행, 종료 후 웹 시작 |
| gemma3:12b + bge-m3 | 이미 배포된 Ollama Pod가 실행 |
| 문서 3개 | 이미지 안 /app/docs |
| 그래프·벡터·문서 상태·캐시 | PVC /data/rag_storage |
| 실제 색인 파일 | 지정한 노드의 /var/lib/lightrag-lab/rag_storage |
| 웹 서비스 | NodePort 30120 또는 kubectl port-forward |

LightRAG는 이 앱에 포함된 Python 라이브러리로 Kubernetes에서 실행됩니다.
별도 LightRAG 공식 API 서버나 Neo4j 서버를 추가로 띄우는 구성은 아닙니다.
그래프 저장소는 LightRAG 기본 파일 저장소입니다. MinIO는 이 실습에 필요하지 않습니다.

## 1. 기존 Ollama 확인 및 모델 준비

아래는 Ollama가 default 네임스페이스의 deployment/ollama와 svc/ollama로 실행 중인 경우입니다.

```powershell
kubectl get deployment ollama -n default
kubectl get svc ollama -n default
kubectl exec -n default deployment/ollama -- ollama list
kubectl exec -n default deployment/ollama -- ollama pull gemma3:12b
kubectl exec -n default deployment/ollama -- ollama pull bge-m3
```

이미 모델이 있으면 pull은 생략합니다. Ollama 모델도 자체 영속 볼륨에 저장돼 있어야 Pod 교체 후 유지됩니다.
Ollama의 네임스페이스/서비스명이 다르면 k8s.yaml ConfigMap의 OLLAMA_BASE_URL을 수정하세요.

```yaml
OLLAMA_BASE_URL: "http://ollama.default.svc.cluster.local:11434"
```

클러스터 내부에서 연결하므로 Ollama의 NodePort나 PC 포트포워딩은 필요 없습니다.
이 패키지는 기존 Ollama Deployment의 GPU 설정을 변경하지 않습니다.

## 2. 노드와 YAML 수정

```powershell
kubectl get nodes -L kubernetes.io/hostname
```

k8s.yaml에서 다음 세 항목을 확인합니다.

1. `REPLACE_WITH_NODE_NAME`: 위 출력의 **kubernetes.io/hostname 라벨 값**으로 교체합니다.
   단일 GPU 서버의 값으로 지정하면 이 노드의 디스크에 색인이 저장됩니다.
2. `YOUR_DOCKERHUB_ID/lightrag-gemma:1.0`: 본인의 이미지 경로로 **두 군데 모두** 교체합니다.
3. `nodePort: 30120`: 사용 중이면 비어 있는 NodePort로 바꿉니다.

이 YAML은 단일 노드 실습용 hostPath PV를 사용하며 StorageClass 없이 명시적으로 PV/PVC를 연결합니다.
PV의 nodeAffinity가 데이터가 있는 노드로 Pod를 제한합니다. 그 노드가 장애 나면 다른 노드로 자동 복구되는 저장소는 아닙니다.
다중 노드 운영에서는 CSI 기반 영속 스토리지로 교체하세요.
5Gi는 PV/PVC의 용량 선언이며 hostPath에 디스크 사용량 제한을 강제하지는 않습니다.

단일 노드가 이미 워크로드를 실행하는 Ready 상태라는 전제입니다. Pod가 taint 때문에 Pending이면
`kubectl describe pod`의 Events를 보고 해당 클러스터의 스케줄링 정책을 확인하세요.

## 3. 이미지 빌드와 push

Dockerfile이 있는 폴더에서 실행합니다. Windows에서는 Docker Desktop을 실행하고 Linux containers 모드를 사용합니다.
아래 YOUR_DOCKERHUB_ID는 실제 계정으로 바꾸세요. 이 명령은 PowerShell과 Bash에서 같습니다.

```powershell
docker login
docker build --platform linux/amd64 -t YOUR_DOCKERHUB_ID/lightrag-gemma:1.0 .
docker push YOUR_DOCKERHUB_ID/lightrag-gemma:1.0
```

Dockerfile에는 CUDA나 Gemma 모델을 넣지 않습니다. 추론은 기존 Ollama가 수행합니다.
LightRAG와 Python 의존성, 테스트 문서, 웹 화면, 토크나이저 캐시는 이미지에 포함합니다.
토크나이저의 gpt-4o-mini 이름은 LightRAG 기본 청킹용 토큰 계산 설정이며 OpenAI API를 호출하지 않습니다.
이미지 빌드에는 인터넷이 필요합니다. 실행 시 앱은 Ollama에 접근하면 됩니다.

Kubernetes 노드는 Docker Desktop과 다른 이미지 저장소를 사용하므로 PC에서 build만 해서는 보이지 않습니다.
push한 이미지를 노드가 pull할 수 있어야 합니다.

비공개 저장소라면 먼저 자격증명을 등록합니다.

```powershell
kubectl create secret docker-registry dockerhub-secret --docker-server=https://index.docker.io/v1/ --docker-username=YOUR_DOCKERHUB_ID --docker-password=YOUR_ACCESS_TOKEN -n default
```

그런 다음 Deployment의 `spec.template.spec` 아래 `initContainers`와 같은 깊이에 추가합니다.

```yaml
imagePullSecrets:
  - name: dockerhub-secret
```

공개 저장소라면 이 설정은 필요 없습니다.

## 4. 배포

```powershell
kubectl apply -f k8s.yaml
kubectl get pv lightrag-lab-pv
kubectl get pvc lightrag-data -n default
kubectl get pods -l app=lightrag -n default -w
```

PVC가 Bound가 되고 Pod가 Init 단계에 들어가면 첫 색인이 진행 중입니다.
진행 로그는 다른 터미널에서 확인하세요.

```powershell
kubectl logs -n default deployment/lightrag -c index-documents -f
```

Gemma가 문서의 개체·관계를 추출하므로 첫 색인은 시간이 걸립니다.
init container가 성공해야 웹 컨테이너가 시작됩니다. 재시작 시 동일 문서는 처리 목록을 보고 건너뜁니다.
Ollama가 없거나 모델이 없거나 색인이 실패하면 init container 로그에 원인이 표시되고 재시도합니다.

웹 컨테이너 로그:

```powershell
kubectl logs -n default deployment/lightrag -c lightrag -f
```

## 5. 웹 접속

NodePort 접근이 가능한 망이면 다음으로 접속합니다.

```text
http://쿠버네티스_노드_IP:30120
```

외부에서 NodePort가 막혀 있거나 localhost로 쓰려면 PC에서 다음을 계속 실행합니다.

```powershell
kubectl port-forward -n default svc/lightrag 18000:8000
```

브라우저: http://127.0.0.1:18000

PC의 kubectl이 API 서버에 정상 연결돼 있어야 합니다. `kubectl get pods`부터 실패하면 기존 kubeconfig/SSH 터널 연결을 먼저 확인하세요.
NodePort 웹 앱에는 인증이 없습니다. 인터넷에 공개하기보다 실습망 또는 localhost 포트포워딩으로 사용하세요.

## 6. 질문 테스트

첫 질문:

> 김민수가 책임자인 프로젝트에서 사용하는 시스템의 공급사와 그 공급사의 기술지원 담당자는 누구인가?

기대 경로:

김민수 → 차세대 주문관리 프로젝트 → 오로라ERP → 새봄소프트 → 정하늘

웹의 `naive / hybrid / mix 비교` 버튼으로 결과를 비교합니다.
`검색 근거만 보기`와 `지식 그래프 → 그래프 불러오기`도 사용할 수 있습니다.
그래프는 SVG로 그리며 외부 CDN이나 Neo4j 설치가 필요 없습니다.

- 노드: 사람·조직·시스템 등 추출된 개체. 유형별 색상은 범례에 표시합니다.
- 관계선: 개체 사이의 관계. 간단한 키워드를 선 옆에 표시합니다.
- 노드/관계선 클릭: 상세 설명과 원문 파일명 확인.
- 노드 선택: 직접 연결된 주변 개체 강조.
- 노드 끌기: 위치 조정. 빈 공간 끌기: 전체 이동.
- 휠 또는 확대/축소 버튼: 화면 배율 조절. 전체 보기: 화면에 맞춤.
- 검색창: 개체명으로 강조. 텍스트 목록도 함께 제공합니다.

관계선에는 임의의 화살표를 붙이지 않습니다. 관계 설명을 클릭해 의미를 확인하세요.
그림은 실제 추출 결과이므로 정답 경로가 자동으로 완성된다고 보장하지 않습니다.
브라우저 응답성을 위해 그림은 최대 200개 개체로 제한하고, 전체 목록은 텍스트로 확인할 수 있습니다.

기존 배포에 그래프 기능을 추가하려면 새 이미지 태그로 빌드/push한 뒤 YAML의 이미지 두 군데를 바꿔 적용합니다.
Gemma/문서/청킹 설정이 같으면 WORKING_DIR은 유지합니다. 기존 PVC의 색인을 다시 쓸 수 있습니다.
질문 5개 및 기대 답안은 questions.json에 들어 있습니다.

## 7. 변경·재배포

앱 코드나 문서를 변경하면 새 태그로 build/push하고 k8s.yaml의 이미지 두 군데를 모두 변경한 뒤 apply하세요.

```powershell
docker build --platform linux/amd64 -t YOUR_DOCKERHUB_ID/lightrag-gemma:1.1 .
docker push YOUR_DOCKERHUB_ID/lightrag-gemma:1.1
kubectl apply -f k8s.yaml
```

위 apply 전 YAML의 두 이미지 태그도 1.1로 바꿔야 합니다. 고정 태그에 덮어쓰는 방식은 노드의 캐시 때문에 피하세요.

모델·기존 문서 내용·청킹 설정을 바꿨다면 ConfigMap의 저장 경로를 새 폴더로 변경하고 재배포합니다.

```yaml
WORKING_DIR: "/data/rag_storage_v2"
```

ConfigMap만 바꾼 경우 apply만으로 기존 Pod의 환경변수는 갱신되지 않으므로 재시작이 필요합니다.

```powershell
kubectl apply -f k8s.yaml
kubectl rollout restart deployment/lightrag -n default
```

이때도 init container가 먼저 실행되어 새 색인을 만듭니다. 이전 폴더는 보존됩니다.

**replicas는 1로 유지하세요.** 기본 파일 저장소를 공유하는 실습이므로 여러 Pod/worker의 동시 쓰기를 지원하도록 구성하지 않았습니다.
Deployment 전략은 Recreate여서 새 Pod 시작 전에 기존 Pod를 종료합니다. 업데이트 중에는 잠시 접속이 끊깁니다.
웹 컨테이너가 실행 중일 때 `kubectl exec ... python app.py ingest`를 별도로 실행하지 마세요.

## 8. 문제 확인

```powershell
kubectl describe pod -l app=lightrag -n default
kubectl get pvc lightrag-data -n default
kubectl get events -n default --sort-by=.metadata.creationTimestamp
```

| 상태 | 확인할 사항 |
|---|---|
| ImagePullBackOff | 이미지 경로 두 군데, push 완료, 공개/비공개 및 imagePullSecrets |
| Pending | PVC Bound 여부, hostname 라벨 값, 노드 자원·taint |
| Init:CrashLoopBackOff | index-documents 로그. Ollama 주소·모델·이전 색인 실패 상태 |
| CrashLoopBackOff | lightrag 컨테이너 로그, 메모리 제한, Ollama 연결 |
| Pod Running인데 접속 안 됨 | Ready 여부, Service, 방화벽. 우선 port-forward로 확인 |
| 색인 중 timeout | Ollama 로그/실행 중 다른 GPU 작업 확인. 필요하면 ConfigMap OLLAMA_TIMEOUT 증가 |
| 파일 권한 오류 | PV 디렉터리 권한, 클러스터의 컨테이너 사용자 정책 확인 |

현재 이미지는 단일 노드 실습을 간단히 하기 위해 기본 root 사용자로 실행합니다.
클러스터가 non-root 실행을 강제하면 PV 디렉터리 소유권과 컨테이너 사용자 설정을 맞춰야 합니다.
PV는 Retain 정책이며 리소스를 삭제해도 호스트 디스크의 실습 파일이 자동 삭제되지는 않습니다.

## 검증 범위

- Python 문법, 기존 LightRAG 색인/검색 파이프라인, 추가된 health/readiness 경로 점검
- YAML 파싱 및 PV/PVC 연결·이미지·볼륨·Service·Probe 참조 정합성 점검
- 그래프 API와 출처 보존, JS 문법, DOM 환경의 렌더링·선택·검색·확대·드래그·빈 그래프 처리 점검 통과
- 실제 브라우저의 배치·터치 동작은 이 작성 환경에서 검증하지 못함
- 이 작성 환경에는 Docker daemon, kubectl, 사용자 클러스터 연결이 없어 실제 이미지 빌드와 클러스터 배포는 수행하지 못함
