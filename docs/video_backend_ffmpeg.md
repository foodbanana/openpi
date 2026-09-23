# 영상 디코딩 백엔드 — torchcodec / pyav 선택 메모

A6000 공용 서버에서 `compute_norm_stats.py` / `train.py` 실행 시 영상 디코딩이 실패하는 문제와,
그 해결로 `video_backend="pyav"` 를 쓰기로 한 이유를 적는다.

데이터셋 구조는 [1DOF_gripper_data_collection.md](1DOF_gripper_data_collection.md), 통계는 [norm_stats.md](norm_stats.md) 참고.

## 증상

```
RuntimeError: Could not load libtorchcodec.
[start of libtorchcodec loading traceback]
FFmpeg version 7: libavutil.so.59: cannot open shared object file: No such file or directory
FFmpeg version 6: libavutil.so.58: cannot open shared object file: No such file or directory
FFmpeg version 5: libavutil.so.57: cannot open shared object file: No such file or directory
FFmpeg version 4: libavutil.so.56: cannot open shared object file: No such file or directory
[end of libtorchcodec loading traceback].
```

AV1 코덱 문제가 **아니다.** torchcodec 이라는 라이브러리 자체가 로드되지 않는 것이다.
서버(Ubuntu 20.04)에 FFmpeg 공유 라이브러리가 4·5·6·7 전부 없고, 공용 서버라 `sudo apt install` 이 불가능하다.

## FFmpeg major ↔ soname 대응

버전을 고를 때 이 표가 기준이 된다.

| FFmpeg | libavutil | libavcodec | torchcodec 0.4.0 지원 |
|--------|-----------|------------|----------------------|
| 4 | `.so.56` | `.so.58` | O |
| 5 | `.so.57` | `.so.59` | O |
| 6 | `.so.58` | `.so.60` | O |
| 7 | `.so.59` | `.so.61` | O |
| 8 | `.so.60` | `.so.62` | **X** |

torchcodec 0.4.0 이 가진 디코더는 4~7 뿐이다. `decoder8.so` 는 없다.

```bash
ls .venv/lib/python3.11/site-packages/torchcodec/libtorchcodec_decoder*.so
# decoder4 / decoder5 / decoder6 / decoder7  (8 없음)
```

## 시도했지만 안 되는 것

### patch-torchcodec (PyPI)

"PyAV 번들 FFmpeg 를 torchcodec 이 쓰도록 RPATH 패치" 하는 패키지. 시스템 설치가 필요 없어 매력적으로 보이지만
**이 스택에서는 불가능하다.**

```bash
uv run python -c "import av; print(av.__version__, av.library_versions)"
# 17.0.0  {'libavutil': (60, 8, 100), 'libavcodec': (62, 11, 100), ...}
```

PyAV 17.0.0 은 **FFmpeg 8** 을 번들한다. torchcodec 0.4.0 에는 FFmpeg 8 디코더가 없으므로
RPATH 를 어떻게 패치해도 없는 디코더는 만들어지지 않는다.
서버 에러 로그가 7→6→5→4 만 시도하고 끝나는 것이 같은 이야기다.

patch-torchcodec 이 다른 사람들에게 통하는 것은 PyAV 14.x 이하가 FFmpeg 7.1 을 번들하기 때문이다.
openpi 의 `uv.lock` 이 `av==17.0.0` 으로 고정돼 있어 해당하지 않는다.

우회로도 권하지 않는다.

- `av` 다운그레이드 → lerobot / torchvision 이 의존하므로 lock 이 깨진다
- `torchcodec` 업그레이드(0.5+ 가 FFmpeg 8 지원) → torch 2.8/2.9 가 필요해 환경 전체 재구성

### torch / torchcodec 버전 비호환?

에러 메시지가 "PyTorch 버전이 맞지 않을 수 있다" 고 안내하지만 **이 경우는 아니다.**
완전히 같은 `.venv` 내용물이 데스크탑에서는 정상 동작한다.

```
로컬 torchcodec 이 실제로 로드하는 것
  /usr/lib/x86_64-linux-gnu/libavutil.so.58.29.100   ← 시스템 FFmpeg 6
  /usr/lib/x86_64-linux-gnu/libavcodec.so.60.31.102
→ decoder OK, codec: av1
```

차이는 **시스템 FFmpeg 존재 여부 하나뿐**이다.

## 방안 비교

| | A. `video_backend="pyav"` | B. conda ffmpeg 7.1 + `LD_LIBRARY_PATH` |
|---|---|---|
| 설치 | 없음 | conda env 생성 |
| 공용 서버 영향 | 없음 | `~/taeunglee` 안에서만 (sudo 불필요) |
| 디코딩 속도 | 8.5 ms / random seek | 3.4 ms / random seek |
| 매 실행 시 | 불필요 | `LD_LIBRARY_PATH` 필요 |
| 적용 범위 | 코드 → push 로 서버 반영 | 서버 환경에만 |

출력은 두 백엔드가 **완전히 동일하다.** 같은 mp4 · 같은 timestamp 로 비교한 결과:

```
torchcodec: torch.Size([3, 3, 480, 640]) float32
pyav      : torch.Size([3, 3, 480, 640]) float32
max abs diff: 0.0
```

프레임 하나가 아니라 파이프라인 끝단에서도 같다. 백엔드만 바꿔 2868 프레임 전체로
norm stats 를 다시 계산하고 두 결과를 대조한 값이다.

```
key      field    max abs diff
actions  mean/std/q01/q99   0.00e+00
state    mean/std/q01/q99   0.00e+00
```

즉 백엔드를 바꿔도 학습 결과에 수치적 차이가 없다. 속도만 다르다.

## 현재 결정 — A (pyav)

리허설 데이터 3 에피소드 / 2868 프레임 단계에서는 배관을 뚫는 것이 목적이라 2.5배 속도차가 의미 없다
(로컬 norm stats 전체가 25초). A 는 설치가 없고 실패해도 되돌릴 것이 없다.

lerobot 이 `pyav` 백엔드를 이미 내장하고 있다. openpi 가 `LeRobotDataset` 에 이 인자를 넘기지 않아
기본값 torchcodec 이 쓰이던 것이다.

- `DataConfig.video_backend` (기본 `None`) — `src/openpi/training/config.py`
- `LeRobotDataset(..., video_backend=data_config.video_backend)` — `src/openpi/training/data_loader.py`
- `base_config=DataConfig(prompt_from_task=True, video_backend="pyav")` — `pi05_ur5_lora` TrainConfig

repo 안에서 `LeRobotDataset(` 호출은 한 곳뿐이고 `compute_norm_stats.py` 와 `train.py` 가 모두
`create_torch_dataset()` 을 거쳐 거기로 수렴하므로 빠지는 경로가 없다.

기본값이 `None` 이라 **다른 config 는 영향받지 않는다.** `None` 은 LeRobot 기본 동작(torchcodec 가능하면 torchcodec)과 같다.

### 되돌리기

값을 `LeRobotUR5DataConfig` 클래스 기본값이 아니라 **TrainConfig 의 `base_config` 호출 지점**에 둔 이유가 이것이다.

```python
base_config=DataConfig(prompt_from_task=True),   # video_backend="pyav" 만 지우면 torchcodec 복귀
```

한 곳에서 문자열 하나를 지우면 된다. `DataConfig` 필드와 `data_loader` 배관은 남겨둬도 무해하다.
클래스 기본값으로 뒀다면 이 클래스를 쓰는 앞으로의 모든 config 가 서버가 고쳐진 뒤에도 느린 경로에 묶인다.

## 나중에 B 로 가야 할 때

본격 파인튜닝에서 **GPU 가 데이터를 기다리며 노는 병목이 실측으로 확인되면** 전환한다.
추측으로 미리 하지 않는다.

순서대로 시도한다.

1. `num_workers` 증가 — 디코딩은 워커에서 일어나므로 이것으로 가려지는 경우가 많다
2. 그래도 부족하면 아래 conda FFmpeg

```bash
# 공용 conda base 를 건드리지 않도록 패키지 캐시도 자기 영역으로
export CONDA_PKGS_DIRS=~/taeunglee/conda_pkgs

conda create -p ~/taeunglee/envs/ffmpeg7 -c conda-forge 'ffmpeg=7.1.*' -y
ls ~/taeunglee/envs/ffmpeg7/lib/libavutil.so.59       # 59 가 보여야 성공
```

> **`'ffmpeg>=7.0'` 으로 쓰면 안 된다.** 현재 FFmpeg 최신은 8.x 이고 conda-forge 에도 올라와 있어서
> `>=7.0` 은 8.x 로 해석된다. `libavutil.so.60` 이 깔리고 위 표대로 똑같이 실패한다. 반드시 버전을 고정한다.

`LD_LIBRARY_PATH` 는 conda env 의 `lib/` 전체가 아니라 **FFmpeg 라이브러리만 담은 디렉터리**를 가리키게 한다.
conda env 의 `lib/` 에는 `libstdc++`, `libgcc` 도 있어 torch 가 쓰는 것과 충돌할 수 있다.

```bash
mkdir -p ~/taeunglee/ffmpeg_libs
cp -P ~/taeunglee/envs/ffmpeg7/lib/lib{av,sw}*.so* ~/taeunglee/ffmpeg_libs/

export LD_LIBRARY_PATH=~/taeunglee/ffmpeg_libs:$LD_LIBRARY_PATH
cd ~/taeunglee/openpi
uv run python -c "from torchcodec.decoders import VideoDecoder; print('torchcodec OK')"
```

동작을 확인한 뒤 config 에서 `video_backend="pyav"` 를 지운다. 매 셸에서 `LD_LIBRARY_PATH` 가 필요하므로
`~/taeunglee/env.sh` 같은 파일에 넣어 두고 `source` 하는 편이 낫다.

conda 를 쓰고 싶지 않으면 micromamba 로 같은 일을 할 수 있다.

## 확인용 명령

```bash
# 백엔드가 config 까지 전달되는지
uv run python -c "
import pathlib
from openpi.training import config
c = config.get_config('pi05_ur5_lora')
print(c.data.create(pathlib.Path('assets'), c.model).video_backend)"      # → pyav

# 현재 환경에서 torchcodec 이 로드되는지
uv run python -c "from torchcodec.decoders import VideoDecoder; print('OK')"

# 시스템에 FFmpeg 공유 라이브러리가 있는지
ldconfig -p | grep libavutil
```

파이프라인에서 종료 코드를 볼 때는 `$?` 가 아니라 `${PIPESTATUS[0]}` 를 써야 한다.
`| tee` 를 걸면 `$?` 는 tee 의 종료 코드라 항상 0 이다.

```bash
uv run scripts/compute_norm_stats.py --config-name pi05_ur5_lora 2>&1 | tee log.txt
echo "exit: ${PIPESTATUS[0]}"
```

## 참고

- [docs/1DOF_gripper_data_collection.md](1DOF_gripper_data_collection.md) — 그리퍼 토픽 / 데이터 수집
- [docs/norm_stats.md](norm_stats.md) — 정규화 통계, π0 액션 공간 정의
- [examples/ur5/README.md](../examples/ur5/README.md) — UR5 transform / TrainConfig 작성법
- [patch-torchcodec (PyPI)](https://pypi.org/project/patch-torchcodec/) — 이 스택에서는 불가
- [torchcodec releases](https://github.com/meta-pytorch/torchcodec/releases) — 버전별 지원 FFmpeg
- [conda-forge ffmpeg](https://anaconda.org/conda-forge/ffmpeg) — 버전 확인
