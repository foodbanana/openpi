# A6000 서버 학습 런북 — UR5 pi05 LoRA

새 데이터셋으로 학습을 돌릴 때 순서대로 따라가는 문서.
2026-09-23 리허설(3 에피소드)로 전 과정을 한 번 완주한 기준이다.

배경 문서: [1DOF_gripper_data_collection.md](1DOF_gripper_data_collection.md) (데이터 수집),
[video_backend_ffmpeg.md](video_backend_ffmpeg.md) (영상 디코딩), [norm_stats.md](norm_stats.md) (정규화)

## 공용 서버 원칙

연구실 전체가 `user` 계정 하나와 홈 디렉터리 하나를 공유한다. 이게 아래 여러 단계의 이유가 된다.

- 작업은 `~/taeunglee/` 안에서만. `sudo` 금지. 시스템 패키지 설치 금지.
- GPU 는 쓰기 전에 반드시 비어 있는지 확인하고 하나만 점유한다.
- wandb 는 `wandb login` 대신 환경변수. `login` 은 공유 `~/.netrc` 에 쓴다.
- `~/.cache/openpi` (pi05_base 11.6 GiB) 와 `~/.cache/huggingface/lerobot` 은 공유 캐시다. 지우지 않는다.

---

## 0. 환경 (최초 1회, 이미 되어 있음)

```bash
wget -qO- https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env

mkdir -p ~/taeunglee && cd ~/taeunglee
git clone --recurse-submodules https://github.com/foodbanana/openpi.git
cd openpi
GIT_LFS_SKIP_SMUDGE=1 uv sync
GIT_LFS_SKIP_SMUDGE=1 uv pip install -e .

uv run python -c "import jax; print(jax.devices())"   # CudaDevice 4장
```

## 1. 데이터셋을 서버로

scp 가 안 되므로 USB 로 옮긴 뒤 LeRobot 이 이름으로 찾는 위치에 둔다.
HuggingFace 에 올려서 쓰면 이 단계는 없어진다.

```bash
# 예: ur5_gripper_drone_v2
mkdir -p ~/.cache/huggingface/lerobot/foodbanana
cp -r ~/taeunglee/datasets/<데이터셋이름> ~/.cache/huggingface/lerobot/foodbanana/

ls ~/.cache/huggingface/lerobot/foodbanana/<데이터셋이름>/   # data meta videos
```

**수집 직후 확인** — 두 카메라에 드론과 그리퍼가 실제로 보이는지. 학습을 다 돌린 뒤 발견하는 것보다 훨씬 싸다.

```bash
cd ~/.cache/huggingface/lerobot/foodbanana/<데이터셋이름>
uv run --project ~/taeunglee/openpi python -c "
from torchcodec.decoders import VideoDecoder
from PIL import Image
for cam in ('third_view','head'):
    d = VideoDecoder(f'videos/chunk-000/observation.images.{cam}/episode_000000.mp4')
    Image.fromarray(d[len(d)//2].permute(1,2,0).numpy()).save(f'/tmp/check_{cam}.png')
"
```

## 2. config 에 데이터셋 이름 쓰기

> `--data.repo-id` CLI 인자는 `compute_norm_stats.py` 에 **전달되지 않는다.**
> 반드시 코드에 적어야 한다. (`train.py` 는 CLI 오버라이드가 먹는다. 스크립트마다 다르다.)

데스크탑에서 `src/openpi/training/config.py` 의 `pi05_ur5_lora` 를 고치고 push → 서버에서 pull.

```python
data=LeRobotUR5DataConfig(
    repo_id="foodbanana/<데이터셋이름>",
    ...
```

```bash
cd ~/taeunglee/openpi && git pull origin main
```

## 3. norm stats 계산

**데이터셋이 바뀌면 반드시 다시 계산한다.** `asset_id` 가 repo_id 에서 나오므로 새 데이터셋은 새 통계가 필요하다.

```bash
cd ~/taeunglee/openpi
uv run scripts/compute_norm_stats.py --config-name pi05_ur5_lora 2>&1 | tee norm_stats_log.txt
echo "exit: ${PIPESTATUS[0]}"
```

> `| tee` 를 걸면 `$?` 는 tee 의 종료 코드라 항상 0 이다. 반드시 `${PIPESTATUS[0]}` 로 본다.

결과를 눈으로 확인한다. 어떤 차원이든 `std` 나 `q99-q01` 이 0 에 가까우면 정규화 후 값이 폭발해 학습이 발산한다.

```bash
uv run python -c "
import json
d = json.load(open('assets/pi05_ur5_lora/foodbanana/<데이터셋이름>/norm_stats.json'))['norm_stats']
for k in ('state','actions'):
    print(k)
    print('  std', [round(v,4) for v in d[k]['std'][:7]])
    print('  q01', [round(v,3) for v in d[k]['q01'][:7]])
    print('  q99', [round(v,3) for v in d[k]['q99'][:7]])"
```

그리퍼(7번째)는 `std` 가 크게 나오는 것이 정상이다. action 이 `{0, 1150}` 이진값이기 때문.

## 4. GPU 와 환경변수

```bash
nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu --format=csv
```

**비어 있는 GPU 번호를 골라서** `CUDA_VISIBLE_DEVICES` 에 넣는다.
`XLA_PYTHON_CLIENT_MEM_FRACTION=0.9` 는 보이는 GPU 의 90% 를 선점하므로, 남이 쓰는 GPU 를 지정하면 그 작업을 방해한다.

wandb 는 환경변수로만 설정한다. `export` 앞에 공백 한 칸을 두면 bash 히스토리에 키가 남지 않는다.

```bash
 export WANDB_API_KEY=<키>
 export WANDB_ENTITY=<사용자명>
```

같은 UID 를 공유하므로 이 키를 다른 사용자로부터 숨길 방법은 없다. 서버 전용 키를 발급해 쓰고 끝나면 폐기하는 편이 낫다.

## 5. smoke test (짧게)

본 학습 전에 항상 100 step 만 돌려 본다. 설정을 바꿨을 때 15 분 만에 드러날 문제를 몇 시간 뒤에 발견하지 않기 위해서다.

```bash
cd ~/taeunglee/openpi
CUDA_VISIBLE_DEVICES=0 XLA_PYTHON_CLIENT_MEM_FRACTION=0.9 uv run scripts/train.py pi05_ur5_lora \
  --exp-name=smoke \
  --project-name=ur5_rehearsal \
  --num-train-steps=100 \
  --save-interval=50 \
  --log-interval=10 \
  --overwrite 2>&1 | tee train_smoke.log
echo "exit: ${PIPESTATUS[0]}"
```

볼 것:

| 항목 | 기준 |
|------|------|
| loss | 하강하고 NaN 이 아님 |
| `param_norm` | 거의 변하지 않음 — LoRA 가 걸렸다는 뜻. 크게 출렁이면 freeze filter 가 안 먹은 것 |
| 체크포인트 | `checkpoints/pi05_ur5_lora/smoke/` 에 저장됨 |
| wandb `camera_views` (step 0) | **왼쪽=외부, 가운데=손목, 오른쪽=검정**. 코드로 판별 불가능한 유일한 항목 |

동결 비율은 dtype 으로 확인한다. `bfloat16` = 동결, `float32` = 학습 대상.

```bash
uv run python - <<'PY'
import re
lines = open('train_smoke.log').read().splitlines()
start = next(i for i, l in enumerate(lines) if 'Initialized train state' in l)
tot = {}
for l in lines[start:]:
    m = re.search(r'\(([\d, ]*)\)@(\w+)', l)
    if not m:
        continue
    n = 1
    for d in (int(x) for x in m.group(1).split(',') if x.strip()):
        n *= d
    tot[m.group(2)] = tot.get(m.group(2), 0) + n
total = sum(tot.values())
for k, v in sorted(tot.items()):
    print(f'{k:>10}: {v:>15,}  ({v/total*100:6.3f}%)')
PY
```

리허설 기준값은 `bfloat16` 86.3% / `float32` 13.7% 였다. 동결되는 것은 `.*llm.*` 경로뿐이라
**SigLIP 비전 인코더(약 400M)는 학습 대상에 포함된다.** 소량 데이터에서는 이게 과적합의 주범이 될 수 있다.

## 6. 본 학습

`nohup` 으로 띄워 ssh/AnyDesk 가 끊겨도 살아남게 한다.

```bash
cd ~/taeunglee/openpi
CUDA_VISIBLE_DEVICES=0 XLA_PYTHON_CLIENT_MEM_FRACTION=0.9 nohup uv run scripts/train.py pi05_ur5_lora \
  --exp-name=<실험이름> \
  --project-name=ur5_pi05 \
  --num-train-steps=<step수> \
  --save-interval=1000 \
  --overwrite > train_<실험이름>.log 2>&1 &

tail -f train_<실험이름>.log
```

step 수는 데이터 양에 맞춘다. `프레임수 / batch_size` 가 1 에포크다.
리허설은 2868 프레임 / 32 = 89 step/epoch 였다. 30,000 step 이면 337 에포크로 과적합이 확실하다.

중단된 학습은 이어서 돌릴 수 있다. `--overwrite` 와 같이 쓰지 않는다.

```bash
... uv run scripts/train.py pi05_ur5_lora --exp-name=<실험이름> --resume
```

## 7. 느릴 때

GPU util 이 낮은데 step/sec 가 안 나오면 데이터 로딩 병목이다. 순서대로 시도한다.

1. `--num-workers=8` (기본 2). pyav 디코딩이 워커에서 일어나므로 대개 이걸로 가려진다
2. 그래도 부족하면 conda FFmpeg 7.1 로 torchcodec 을 살린다 → [video_backend_ffmpeg.md](video_backend_ffmpeg.md)

메모리가 부족하면 `--batch-size=16`, 그래도 안 되면 `--fsdp-devices=2` (GPU 2장을 `CUDA_VISIBLE_DEVICES` 에 넣어야 한다).

## 8. 추론

```bash
uv run scripts/serve_policy.py policy:checkpoint \
  --policy.config=pi05_ur5_lora \
  --policy.dir=checkpoints/pi05_ur5_lora/<실험이름>/<step>
```

8000 포트로 열린다. 로봇 쪽 클라이언트는 [remote_inference.md](remote_inference.md) 참고.
그리퍼는 학습 데이터에서 이진값이었으므로 추론 때도 이진화가 필요하다 — [examples/droid/main.py](../examples/droid/main.py) 에 예시가 있다.

---

## 겪었던 에러와 원인

리허설에서 나온 순서대로. 전부 고쳐져 커밋돼 있으니 다시 만나면 회귀를 의심한다.

| 증상 | 원인 | 조치 |
|------|------|------|
| 로그 없이 종료, `${PIPESTATUS[0]}` 가 139 | jax 가 pyarrow 보다 먼저 로드 (C++ 심볼 충돌) | 스크립트 맨 위 `import pyarrow as pa` |
| `KeyError: Column actions not in the dataset` | `LeRobotDataset` 이 repack 이전에 원본 컬럼명으로 읽음 | `action_sequence_keys=("action",)` |
| `RuntimeError: Could not load libtorchcodec` | 서버에 FFmpeg 4~7 공유 라이브러리 없음 | `video_backend="pyav"` |
| `ValueError: Prompt is required` | `RepackTransform` 이 나열되지 않은 키를 버림 | repack 에 `"prompt": "prompt"` |

norm stats 가 통과했다고 파이프라인이 안전한 것은 아니다.
`compute_norm_stats.py` 는 repack 과 data transform 까지만 적용하고 `model_transforms`
(토큰화 · 리사이즈 · 패딩) 는 실행하지 않는다. 그 단계는 `train.py` 가 처음으로 돌린다.
위 표의 네 번째 에러가 정확히 그래서 학습에서야 드러났다.
