# RH-P12-RN(A) 1DOF 그리퍼 — 노드·토픽 메모

데이터 수집 전체 흐름은 수집 워크스페이스의 `~/data_collection_ur5_gripper/README.md` 를 참고한다
(이 repo 밖이라 링크가 아니다). 이 문서는 그리퍼 노드와 토픽만 다룬다.

## 파일

- `~/rh_gripper_ros2_ws/src/rh_p12_rn_ros2/rh_p12_rn_ros2/rh_gripper_node.py`
- `~/rh_gripper_ros2_ws/src/rh_p12_rn_ros2/rh_p12_rn_ros2/rh_gripper_teleop.py`

## 실행

```bash
# 터미널 3 — 그리퍼 노드 (goal_current 생략 시 기본 400mA, 최댓값 661mA)
ros2 run rh_p12_rn_ros2 rh_gripper_node --ros-args -p goal_current:=400

# 터미널 4 — teleop
ros2 run rh_p12_rn_ros2 rh_gripper_teleop
```

- 파지력을 바꾸려면 `goal_current` 값만 바꾼다. 예: `-p goal_current:=350`
- 데이터 수집 때는 `./3_gripper_node.sh`, `./4_gripper_teleop.sh` 로 실행한다 (기본값 400mA).

## 토픽 확인

```bash
ros2 topic list                        # /gripper/target 이 보이는지
ros2 topic hz /gripper/target          # 30Hz 로 나오는지
ros2 topic echo /gripper/target        # 키를 누르면 position 값이 0 / 1150 으로 바뀌는지
```

## 토픽 정리

| 토픽 | 타입 | 용도 | 주기 | 비고 |
|------|------|------|------|------|
| `/gripper/joint_states` | sensor_msgs/JointState | 그리퍼 observation (present) | 30Hz | `name=['rh_p12_rn']`, `position` = raw 0~1150 |
| `/gripper/target` | sensor_msgs/JointState | 그리퍼 action (goal) | 30Hz | 신규. present 와 같은 stamp |
| `/gripper/command` | std_msgs/Float64 | teleop → node 명령 전달 | 이벤트 | 변환에는 안 씀 (target 으로 대체됨) |

## 데이터 저장에 사용하는 것

- `/gripper/joint_states` → observation
- `/gripper/target` → action

## 그리퍼 구조

```text
┌────────────────────────────────────────────────────────────────────────┐
│                           rh_gripper_teleop                            │
│                       (키보드 입력 → 명령 발행)                        │
│                                                                        │
│  [키보드]   '0' → 열림 (raw 0)                                         │
│             '1' → 닫힘 (raw 1150)                                      │
│             'q' → 종료                                                 │
│             (100Hz 폴링, 키 눌림 시 1회 발행)                          │
│  시리얼 포트 사용 안 함                                                │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │
                        토픽: /gripper/command
                        타입: std_msgs/Float64
                        값  : raw 0 또는 1150 (이산, 이벤트성)
                        ※ 내부 통신용 — 변환에는 안 씀
                                     │
                                     ▼
┌────────────────────────────────────────────────────────────────────────┐
│                            rh_gripper_node                             │
│                    (포트 독점: 읽기 + 쓰기 + 발행)                     │
│                                                                        │
│   ┌────────────────────────────────────────────────────────────────┐   │
│   │ 초기화 순서                                                    │   │
│   │  1. Operating Mode = 5 (전류기반 위치 제어) 보장               │   │
│   │  2. Goal Current = 400mA (기본값, CLI로 조절, ≤661 clamp)      │   │
│   │  3. Profile Velocity = 1000, Acceleration = 300                │   │
│   │  4. Torque ON                                                  │   │
│   │  5. Goal Position ← 0 (열림), current_goal ← 0                 │   │
│   │     → 시작 시 항상 열림 상태 (데이터 시작점 일관성)            │   │
│   └────────────────────────────────────────────────────────────────┘   │
│                                                                        │
│   ┌───────────────────────────────┐┌───────────────────────────────┐   │
│   │ command_callback              ││ publish_tick (30Hz 타이머)    │   │
│   │ - /gripper/command 수신       ││ - present 읽기 (addr 580)     │   │
│   │ - Goal Position write         ││   signed 복원 + 0~1150 clamp  │   │
│   │   (addr 564, 0~1150 clamp)    ││ - present + goal 동시 발행    │   │
│   │ - current_goal ← 값 (latch)   ││   (같은 header.stamp)         │   │
│   └───────────────────────────────┘└───────────────────────────────┘   │
│                                                                        │
│   제어 모드: Current-based Position Control (mode 5)                   │
│   포트: /dev/ttyUSB0, 57600 bps, ID 1, DYNAMIXEL Protocol 2.0          │
└────┬────────────────────────────────────────────────────────┬──────────┘
     │                                                        ▲
     │  write                                     read        │
     │  Goal Position (addr 564)   Present Position (addr 580)│
     │  Goal Current  (addr 550)                              │
     │  0 (열림) ~ 1150 (닫힘)                                │
     ▼                                                        │
 ════════════════════════════════════════════════════════════════════════
                           RH-P12-RN(A) 그리퍼
          1DOF 적응형 · 힘 상한 400mA · Profile 로 부드러운 이동
        물체 접촉 시 goal 은 1150 그대로, present 는 중간에서 멈춤
 ════════════════════════════════════════════════════════════════════════

  rh_gripper_node 가 30Hz 로 발행 (같은 tick · 같은 header.stamp)
                │                                       │
           발행 (obs)                             발행 (action)
                ▼                                       ▼
┌────────────────────────────────┐      ┌────────────────────────────────┐
│ /gripper/joint_states          │      │ /gripper/target                │
│ sensor_msgs/JointState         │      │ sensor_msgs/JointState         │
│ name = ['rh_p12_rn']           │      │ name = ['rh_p12_rn']           │
│ position = [present 0~1150]    │      │ position = [goal 0 또는 1150]  │
│ 30Hz, header.stamp             │      │ 30Hz, header.stamp (동일)      │
│ → observation (실측, 연속)     │      │ → action (이산 {0, 1150})      │
└───────────────┬────────────────┘      └───────────────┬────────────────┘
                │                                       │
                └───────────────────┬───────────────────┘
                                    ▼
                    [외부 구독자 / ros2 bag record]
                    → LeRobot 변환 시:
                       obs    = /gripper/joint_states (present)
                       action = /gripper/target (goal)
                       값은 raw 0~1150 그대로 저장
                       · 정규화는 openpi norm stats 단계에서
                       · 25Hz 리샘플은 변환 1단계에서
```




## 참고

- [docs/norm_stats.md](norm_stats.md) — π0 액션 공간 정의, 사전학습 통계 재사용
- [docs/video_backend_ffmpeg.md](video_backend_ffmpeg.md) — AV1 영상 디코딩 백엔드 (torchcodec / pyav) 선택
- [examples/ur5/README.md](../examples/ur5/README.md) — UR5 transform / TrainConfig 작성법
- [examples/libero/convert_libero_data_to_lerobot.py](../examples/libero/convert_libero_data_to_lerobot.py) — 변환 스크립트 템플릿
- [examples/droid/main.py](../examples/droid/main.py) — 추론 시 그리퍼 이진화 예시
