# CMU 모캡 동작 목록

[CMU Graphics Lab Motion Capture Database](http://mocap.cs.cmu.edu/)의 시도 번호와 설명입니다. CMU 파일을 고를 때 참고하세요(RetLens: 도움말 > CMU 동작 목록).

- **설명:** CMU가 붙인 영어 설명 그대로입니다(2548개 시도).
- **길이:** 실제 촬영 속도로 계산한 초입니다. 일부 피험자(예: 143번)는 파일에 120 fps로 적혀 있어도 60 Hz로 찍혔는데, RetLens는 실제 속도로 엽니다.
- **예제:** RetLens에 예제로 들어 있는 파일입니다(`samples\cmu_bvh`, `samples\cmu_c3d`). 다른 시도는 CMU 사이트나 공개 변환본(BVH, FBX)에서 받아 엽니다.
- **열기:** 프로젝트 패널의 검색 칸에 번호(예: `143_11`)나 설명(예: `dance`)을 넣고 파일을 두 번 누릅니다. 처음 여는 사람 모션은 리타게팅에 수십 초가 걸립니다.

목록 기준일: 2026-10-26

## 동작 종류별 대표 시도

가능하면 10초 안팎의 짧은 시도를 골랐습니다.

### 걷기

| 번호 | CMU 설명 | 메모 | 길이 (s) | 예제 |
|---|---|---|---|---|
| `02_01` | walk | 보통 걸음 | 2.9 | BVH, C3D |
| `91_57` | WalkForward |  | 9.8 |  |
| `132_46` | Walk Slow | 느리게 | 10.2 |  |
| `136_03` | Walk Backwards Bent Forward | 뒤로 걷기 | 10.0 |  |
| `120_08` | Mickey sneaky walk | 살금살금, 과장된 연기 | 10.0 |  |

### 달리기·조깅

| 번호 | CMU 설명 | 메모 | 길이 (s) | 예제 |
|---|---|---|---|---|
| `02_03` | run/jog | 짧은 조깅 | 1.4 | BVH, C3D |
| `111_23` | Run |  | 9.4 |  |
| `77_10` | careful run | 조심스럽게 | 11.5 |  |

### 점프·한 발 뛰기

| 번호 | CMU 설명 | 메모 | 길이 (s) | 예제 |
|---|---|---|---|---|
| `124_11` | 2 Foot Jump | 두 발 점프 | 8.3 |  |
| `141_06` | Jump Twist | 점프하며 비틀기 | 10.8 |  |
| `75_12` | box jump | 상자 위로 점프 | 7.7 |  |
| `131_03` | Start Hop Stop | 출발-한 발 뛰기-정지 | 9.2 |  |

### 방향 전환

| 번호 | CMU 설명 | 메모 | 길이 (s) | 예제 |
|---|---|---|---|---|
| `16_17` | walk, 90-degree left turn | 걷다 왼쪽 90° | 4.3 | BVH, C3D |
| `83_36` | walk forward turn 90 degrees left walk forward | 걷다 왼쪽 90° | 8.8 |  |
| `47_01` | walk forward, turn around, walk back | 걷다 뒤돌아 돌아옴 | 11.0 |  |

### 춤

| 번호 | CMU 설명 | 메모 | 길이 (s) | 예제 |
|---|---|---|---|---|
| `05_02` | dance - expressive arms, pirouette | 발레 | 9.4 |  |
| `93_08` | xtra fancY charleston | 찰스턴 | 9.3 |  |
| `60_10` | salsa dance | 살사(2인 중 1명) | 19.9 |  |
| `141_12` | Dance, Twist | 트위스트 | 9.5 |  |

### 스포츠

| 번호 | CMU 설명 | 메모 | 길이 (s) | 예제 |
|---|---|---|---|---|
| `06_12` | basketball - forward dribble, 90-degree right turns, crossover dribble | 농구 드리블 | 10.2 |  |
| `124_04` | Basketball Free Throw | 농구 자유투 | 6.0 |  |
| `124_07` | Baseball Swing | 야구 스윙 | 10.8 |  |
| `10_01` | soccer - kick ball | 축구 킥 | 6.7 |  |
| `79_92` | frisbee | 프리스비 | 10.6 |  |

### 격투·발차기

| 번호 | CMU 설명 | 메모 | 길이 (s) | 예제 |
|---|---|---|---|---|
| `141_14` | Punch and Kick | 펀치와 킥 | 9.6 |  |
| `135_04` | Front Kick | 앞차기 | 11.0 |  |

### 집안일·물체 다루기

집 안에서 움직이며 물건을 다루는 동작입니다

| 번호 | CMU 설명 | 메모 | 길이 (s) | 예제 |
|---|---|---|---|---|
| `143_11` | Walk And Pick up Box | 상자 들기 | 10.9 | BVH, C3D |
| `143_13` | Walk and Pick up Laundry Basket | 빨래바구니 들기 | 9.7 | BVH, C3D |
| `143_28` | Sweeping, Push Broom | 빗자루질 | 10.7 | BVH, C3D |
| `143_26` | Washing Window | 창문 닦기 | 10.6 |  |
| `82_07` | Pushing on heavy object | 무거운 물체 밀기 | 10.0 |  |
| `70_05` | carry 19.5lb suitcase | 여행가방 들고 걷기 | 7.5 |  |
| `113_26` | Walk and carry | 들고 걷기 | 11.0 |  |
| `106_25` | clean | 청소 | 10.2 |  |
| `13_09` | drink soda | 음료 마시기 | 9.2 |  |
| `143_20` | Catch And Throw | 받고 던지기 | 10.8 |  |

### 앉기·일어서기

| 번호 | CMU 설명 | 메모 | 길이 (s) | 예제 |
|---|---|---|---|---|
| `141_17` | Sit on Stool | 스툴에 앉기 | 9.3 |  |
| `113_15` | Sit in chair and get up | 의자에 앉았다 일어서기 | 7.9 |  |
| `143_18` | Sit Down And Get Up | 앉았다 일어서기 | 12.5 |  |

### 계단·사다리·기기

| 번호 | CMU 설명 | 메모 | 길이 (s) | 예제 |
|---|---|---|---|---|
| `83_32` | walk forward stepping up stairs | 계단 오르기 | 8.7 |  |
| `143_37` | Climb Up And Down Ladder | 사다리 오르내리기 | 9.2 |  |
| `133_01` | Walk Crawl | 걷다 기기 | 11.5 |  |

### 균형

| 번호 | CMU 설명 | 메모 | 길이 (s) | 예제 |
|---|---|---|---|---|
| `49_18` | balance on one leg, outstretched arms | 한 발로 서기 | 9.2 |  |
| `132_09` | Walk With Arms Out,  balancing | 팔 벌리고 균형 잡으며 걷기 | 9.8 |  |

### 운동·스트레칭

| 번호 | CMU 설명 | 메모 | 길이 (s) | 예제 |
|---|---|---|---|---|
| `13_30` | jumping jacks, side twists, squats, jog | 팔벌려뛰기·스쿼트·조깅 | 20.5 |  |
| `114_12` | Stretching | 스트레칭 | 9.3 |  |
| `111_38` | Yoga | 요가 | 22.0 |  |

### 흉내·제스처

| 번호 | CMU 설명 | 메모 | 길이 (s) | 예제 |
|---|---|---|---|---|
| `79_53` | dog | 개 흉내 | 12.4 |  |
| `143_34` | Chicken Dance | 치킨 댄스 | 13.1 |  |
| `141_16` | Wave Hello | 손 흔들기 | 5.0 |  |

### 바닥에서 일어나기

바닥에 눕거나 손을 짚는 동작이라 발만 지지로 보는 현재 균형·물리 판정에는 맞지 않습니다

| 번호 | CMU 설명 | 메모 | 길이 (s) | 예제 |
|---|---|---|---|---|
| `140_04` | Get Up Laying on Side | 옆으로 누웠다 일어나기 | 9.2 |  |
| `139_16` | Get Up From Ground | 바닥에서 일어나기 | 10.9 |  |

### 아크로바틱

구르기·손 짚기·공중 동작이라 G1 리타게팅과 물리 재생이 크게 어긋납니다

| 번호 | CMU 설명 | 메모 | 길이 (s) | 예제 |
|---|---|---|---|---|
| `90_03` | cartwheel | 옆돌기 | 7.4 |  |
| `90_15` | front hand flip | 앞 손짚고 돌기 | 9.9 |  |
| `90_28` | breakdance | 브레이크댄스 | 6.4 |  |

## 전체 목록 (피험자별)

### 피험자 01

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `01_01` | playground - forward jumps, turn around | 22.9 |  |
| `01_02` | playground - climb | 36.2 |  |
| `01_03` | playground - climb, hang, swing | 37.6 |  |
| `01_04` | playground - climb | - |  |
| `01_05` | playground - climb, go under | 36.5 |  |
| `01_06` | playground - climb, sit, dangle legs, descend | 42.8 |  |
| `01_07` | playground - climb, sit, dangle legs, jump down | 40.3 |  |
| `01_08` | playground - climb, sit, dangle legs, rock back, lower self to ground | 21.8 |  |
| `01_09` | playground - climb, hang, hold self up with arms straight, swing, drop, sit, dangle legs, go under | 35.4 |  |
| `01_10` | playground - climb, swing, lean back, drop | 27.2 |  |
| `01_11` | playground - climb, hang, lean over, jump down | 38.8 |  |
| `01_12` | playground - climb, pull up, dangle, sit, lower self to ground | - |  |
| `01_13` | playground - climb, go under, jump down | - |  |
| `01_14` | playground - climb, jump down, dangle, legs push off against | - |  |

### 피험자 02

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `02_01` | walk | 2.9 | BVH, C3D |
| `02_02` | walk | 2.5 |  |
| `02_03` | run/jog | 1.4 | BVH, C3D |
| `02_04` | jump, balance | 4.0 |  |
| `02_05` | punch/strike | 15.4 |  |
| `02_06` | bend over, scoop up, rise, lift arm | 18.6 |  |
| `02_07` | swordplay | 18.8 |  |
| `02_08` | swordplay | 12.5 |  |
| `02_09` | swordplay | 8.6 |  |
| `02_10` | wash self | 22.0 |  |

### 피험자 03

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `03_01` | walk on uneven terrain | - |  |
| `03_02` | walk on uneven terrain | - |  |
| `03_03` | walk on uneven terrain | - |  |
| `03_04` | walk on uneven terrain | - |  |

### 피험자 05

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `05_01` | walk | 5.0 |  |
| `05_02` | dance - expressive arms, pirouette | 9.4 |  |
| `05_03` | dance - sideways arabesque, turn step, folding arms | 3.6 |  |
| `05_04` | dance - sideways arabesque, folding arms, bending back | 10.0 |  |
| `05_05` | dance - quasi-cou-de-pied, raised leg above hip-height, jete en tourant | 7.6 |  |
| `05_06` | dance - cartwheel-like start, pirouettes, jete | 7.4 |  |
| `05_07` | dance - small jetes, attitude/arabesque, shifted-axis pirouette, turn | 9.9 |  |
| `05_08` | dance - rond de jambe in the air, jete, turn | 6.0 |  |
| `05_09` | dance - glissade devant, glissade derriere, attitude/arabesque | 9.5 |  |
| `05_10` | dance - glissade devant, glissade derriere, attitude/arabesque | 6.8 |  |
| `05_11` | dance - sideways steps, pirouette | 4.9 |  |
| `05_12` | dance - arms held high, pointe tendue a terre, upper body rotation | 11.3 |  |
| `05_13` | dance - small jetes, pirouette | 9.1 |  |
| `05_14` | dance - retire derriere, attitude/arabesque | 5.3 |  |
| `05_15` | dance - retire derriere, attitude/arabesque | 4.5 |  |
| `05_16` | dance - coupe dessous, jete en tourant | 4.4 |  |
| `05_17` | dance - coupe dessous, grand jete en tourant | 8.7 |  |
| `05_18` | dance - attitude/arabesque, jete en tourant, bending back | 15.2 |  |
| `05_19` | dance - attitude/arabesque, jete en tourant, bending back | 7.2 |  |
| `05_20` | dance - attitude/arabesque, jete en tourant, bending back | 9.1 |  |

### 피험자 06

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `06_01` | walk | 4.1 |  |
| `06_02` | basketball - forward dribble | - |  |
| `06_03` | basketball - forward dribble | 4.4 |  |
| `06_04` | basketball - forward dribble | 3.3 |  |
| `06_05` | basketball - forward dribble | 3.2 |  |
| `06_06` | basketball - backward dribble | 3.4 |  |
| `06_07` | basketball - backward dribble | 4.8 |  |
| `06_08` | basketball - sideways dribble | 2.9 |  |
| `06_09` | basketball - sideways dribble | 2.5 |  |
| `06_10` | basketball - forward dribble, 90-degree left turns | 9.3 |  |
| `06_11` | basketball - forward dribble, 90-degree right turns | 9.6 |  |
| `06_12` | basketball - forward dribble, 90-degree right turns, crossover dribble | 10.2 |  |
| `06_13` | basketball - low, fast free style dribble, dribble through legs | 40.9 |  |
| `06_14` | basketball - crossover dribble, shoot | 4.0 |  |
| `06_15` | basketball - dribble, shoot | 4.5 |  |

### 피험자 07

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `07_01` | walk | 2.6 |  |
| `07_02` | walk | 2.7 |  |
| `07_03` | walk | 3.5 |  |
| `07_04` | slow walk | 3.7 |  |
| `07_05` | slow walk | 4.3 |  |
| `07_06` | walk | 3.5 |  |
| `07_07` | walk | 3.2 |  |
| `07_08` | walk | 3.0 |  |
| `07_09` | walk | 2.5 |  |
| `07_10` | walk | 2.5 |  |
| `07_11` | walk | 2.6 |  |
| `07_12` | brisk walk | 2.2 |  |

### 피험자 08

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `08_01` | walk | 2.3 |  |
| `08_02` | walk | 2.6 |  |
| `08_03` | walk | 2.9 |  |
| `08_04` | slow walk | 4.0 |  |
| `08_05` | walk/stride | 2.5 |  |
| `08_06` | walk | 2.5 |  |
| `08_07` | walk, exaggerated stride | 2.5 |  |
| `08_08` | walk | 2.4 |  |
| `08_09` | walk | 2.4 |  |
| `08_10` | walk | - |  |
| `08_11` | slow walk/stride | 3.1 |  |

### 피험자 09

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `09_01` | run | 1.2 |  |
| `09_02` | run | 1.1 |  |
| `09_03` | run | 1.1 |  |
| `09_04` | run | 1.1 |  |
| `09_05` | run | 1.2 |  |
| `09_06` | run | 1.2 |  |
| `09_07` | run | 1.1 |  |
| `09_08` | run | 1.1 |  |
| `09_09` | run | 1.3 |  |
| `09_10` | run | 1.1 |  |
| `09_11` | run | 1.4 |  |
| `09_12` | navigate - walk forward, backward, sideways | 16.0 |  |

### 피험자 10

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `10_01` | soccer - kick ball | 6.7 |  |
| `10_02` | soccer - kick ball | 4.9 |  |
| `10_03` | soccer - kick ball | 3.0 |  |
| `10_04` | walk | 4.6 |  |
| `10_05` | soccer - kick ball | 3.6 |  |
| `10_06` | soccer - kick ball | - |  |

### 피험자 11

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `11_01` | soccer - kick ball | 5.0 |  |

### 피험자 12

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `12_01` | walk | 4.4 |  |
| `12_02` | walk | 5.6 |  |
| `12_03` | walk | 4.7 |  |
| `12_04` | tai chi | 148.3 |  |

### 피험자 13

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `13_01` | sit on high stool, stand up | 19.3 |  |
| `13_02` | sit on high stool, stand up | 29.0 |  |
| `13_03` | sit on high stool, stand up | 31.0 |  |
| `13_04` | sit on stepstool, chin in hand | 39.7 |  |
| `13_05` | sit on stepstool, hands against chin, fidget, stand up | 36.7 |  |
| `13_06` | sit on stepstool, hands against chin, elbow out, stand up | 36.8 |  |
| `13_07` | unscrew bottlecap, drink soda | 12.1 |  |
| `13_08` | unscrew bottlecap, drink soda, screw on bottlecap | 13.4 |  |
| `13_09` | drink soda | 9.2 |  |
| `13_10` | jump up to grab, reach for, tiptoe | 20.0 |  |
| `13_11` | forward jump | 3.5 |  |
| `13_12` | jump up to grab, reach for, tiptoe | 28.6 |  |
| `13_13` | forward jump | 3.7 |  |
| `13_14` | laugh | 20.2 |  |
| `13_15` | laugh | 19.9 |  |
| `13_16` | laugh | 19.0 |  |
| `13_17` | boxing | 40.3 |  |
| `13_18` | boxing | 25.0 |  |
| `13_19` | forward jump | 3.5 |  |
| `13_20` | wash windows | 47.7 |  |
| `13_21` | wash windows | 45.3 |  |
| `13_22` | wash windows | 41.4 |  |
| `13_23` | sweep floor | 33.5 |  |
| `13_24` | sweep floor | 33.6 |  |
| `13_25` | sweep floor | 33.4 |  |
| `13_26` | direct traffic, wave | 25.2 |  |
| `13_27` | direct traffic, wave, point | 34.7 |  |
| `13_28` | direct traffic, wave, point | 34.3 |  |
| `13_29` | jumping jacks, side twists, bend over, squats | 38.3 |  |
| `13_30` | jumping jacks, side twists, squats, jog | 20.5 |  |
| `13_31` | jumping jacks, side twists, bend over, jog | 25.1 |  |
| `13_32` | forward jump | 2.8 |  |
| `13_33` | climb ladder | 12.5 |  |
| `13_34` | climb ladder | 11.8 |  |
| `13_35` | climb 3 steps | 10.0 |  |
| `13_36` | climb 3 steps | 11.5 |  |
| `13_37` | climb 3 steps | 12.3 |  |
| `13_38` | climb 3 steps | 10.4 |  |
| `13_39` | jump | 2.9 |  |
| `13_40` | jump | 2.7 |  |
| `13_41` | jump | 3.1 |  |
| `13_42` | jump | 3.3 |  |

### 피험자 14

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `14_01` | boxing | - |  |
| `14_02` | boxing | - |  |
| `14_03` | boxing | - |  |
| `14_04` | drink soda, screw on bottlecap | - |  |
| `14_05` | unscrew bottlecap, drink soda | - |  |
| `14_06` | jumping jacks, jog, squats, side twists, stretches | - |  |
| `14_07` | jump up to grab, reach for, tiptoe | - |  |
| `14_08` | jump up to grab, reach for, tiptoe | - |  |
| `14_09` | jump up to grab, reach for, tiptoe | - |  |
| `14_10` | wash windows | - |  |
| `14_11` | wash windows | - |  |
| `14_12` | wash windows | - |  |
| `14_13` | mop floor | - |  |
| `14_14` | jumping jacks, jog, squats, side twists, stretches | - |  |
| `14_15` | mop floor | - |  |
| `14_16` | sweep floor | - |  |
| `14_17` | laugh | - |  |
| `14_18` | laugh | - |  |
| `14_19` | laugh | - |  |
| `14_20` | jumping jacks, side twists, reach up, bend over | - |  |
| `14_21` | climb 3 steps | - |  |
| `14_22` | climb 3 steps | - |  |
| `14_23` | climb 3 steps | - |  |
| `14_24` | direct traffic, wave, point | - |  |
| `14_25` | direct traffic, wave, point | - |  |
| `14_26` | direct traffic, wave, point | - |  |
| `14_27` | sit on high stool, stand up | - |  |
| `14_28` | sit on high stool, stand up | - |  |
| `14_29` | sit on stepstool, stand up, swing legs | - |  |
| `14_30` | sit on stepstool, ankle on other knee, hand on chin | - |  |
| `14_31` | sit on stepstool, stand up | - |  |
| `14_32` | sit on stepstool, stand up | - |  |
| `14_33` | climb ladder | - |  |
| `14_34` | climb ladder | - |  |
| `14_35` | climb ladder | - |  |
| `14_36` | sit on stepstool, stand up | - |  |
| `14_37` | drink soda | - |  |

### 피험자 15

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `15_01` | walk/wander | 46.0 |  |
| `15_02` | climb, step over, sit on, stand on stepstool | 183.0 |  |
| `15_03` | walk/wander | 104.6 |  |
| `15_04` | wash windows, paint; hand signals; dance - Egyptian walk, the Dive, the Twist, the Cabbage Patch; boxing | 187.9 |  |
| `15_05` | wash windows, paint; hand signals; dance - Egyptian walk, the Dive, the Twist, the Cabbage Patch; boxing | 191.2 |  |
| `15_06` | lean forward, reach for | 30.0 |  |
| `15_07` | lean forward, tiptoe, reach for | 45.8 |  |
| `15_08` | hand signals - horizontally revolve forearms | 32.2 |  |
| `15_09` | walk/wander | 65.6 |  |
| `15_10` | sit on high stool, stand up | 23.2 |  |
| `15_11` | wash windows, paint figure eights; hand signals | 78.3 |  |
| `15_12` | wash windows; basketball - dribble, lay-up shot, pass; throw ball; dance - Egyptian walk, the Dive, the Twist; strew | 75.7 |  |
| `15_13` | boxing | 77.8 |  |
| `15_14` | walk/wander | 74.9 |  |

### 피험자 16

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `16_01` | jump | - |  |
| `16_02` | jump | - |  |
| `16_03` | high jump | - |  |
| `16_04` | high jump | - |  |
| `16_05` | forward jump | - |  |
| `16_06` | forward jump | - |  |
| `16_07` | forward jump | - |  |
| `16_08` | run/jog, sudden stop | - |  |
| `16_09` | forward jump | - |  |
| `16_10` | forward jump | - |  |
| `16_11` | walk, veer left | - |  |
| `16_12` | walk, veer left | - |  |
| `16_13` | walk, veer right | - |  |
| `16_14` | walk, veer right | - |  |
| `16_15` | walk | - |  |
| `16_16` | walk | - |  |
| `16_17` | walk, 90-degree left turn | 4.3 | BVH, C3D |
| `16_18` | walk, 90-degree left turn | - |  |
| `16_19` | walk, 90-degree right turn | - |  |
| `16_20` | walk, 90-degree right turn | - |  |
| `16_21` | walk | - |  |
| `16_22` | walk | - |  |
| `16_23` | walk, veer left | - |  |
| `16_24` | walk, veer left | - |  |
| `16_25` | walk, veer right | - |  |
| `16_26` | walk, veer right | - |  |
| `16_27` | walk, 90-degree left turn | - |  |
| `16_28` | walk, 90-degree left turn | - |  |
| `16_29` | walk, 90-degree right turn | - |  |
| `16_30` | walk, 90-degree right turn | - |  |
| `16_31` | walk | - |  |
| `16_32` | walk | - |  |
| `16_33` | slow walk, stop | - |  |
| `16_34` | slow walk, stop | 2.9 |  |
| `16_35` | run/jog | 1.4 |  |
| `16_36` | run/jog | - |  |
| `16_37` | run/jog, veer left | - |  |
| `16_38` | run/jog, veer left | - |  |
| `16_39` | run/jog, veer right | - |  |
| `16_40` | run/jog, veer right | - |  |
| `16_41` | run/jog, 90-degree left turn | - |  |
| `16_42` | run/jog, 90-degree left turn | - |  |
| `16_43` | run/jog, 90-degree right turn | - |  |
| `16_44` | run/jog, 90-degree right turn | - |  |
| `16_45` | run/jog | - |  |
| `16_46` | run/jog | - |  |
| `16_47` | walk | - |  |
| `16_48` | run, veer left | - |  |
| `16_49` | run, veer right | - |  |
| `16_50` | run, veer right | - |  |
| `16_51` | run, 90-degree left turn | - |  |
| `16_52` | run, 90-degree left turn | - |  |
| `16_53` | run, 90-degree right turn | - |  |
| `16_54` | run, 90-degree right turn | - |  |
| `16_55` | run | - |  |
| `16_56` | run/jog | - |  |
| `16_57` | run/jog, sudden stop | - |  |
| `16_58` | walk | - |  |

### 피험자 17

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `17_01` | walk with anger, frustration | 52.5 |  |
| `17_02` | walk with anger, frustration | - |  |
| `17_03` | walk stealthily | 52.9 |  |
| `17_04` | walk stealthily | 53.2 |  |
| `17_05` | walk/hobble | 52.8 |  |
| `17_06` | whistle, walk jauntily | 51.7 |  |
| `17_07` | whistle, walk jauntily | 53.5 |  |
| `17_08` | muscular, heavyset person's walk | 51.5 |  |
| `17_09` | muscular, heavyset person's walk | 50.7 |  |
| `17_10` | boxing | 23.2 |  |

### 피험자 18

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `18_01` | walk, shake hands (2 subjects - subject A) | - |  |
| `18_02` | walk, shake hands (2 subjects - subject A) | - |  |
| `18_03` | A pulls B; B resists (2 subjects - subject A) | - |  |
| `18_04` | A pulls B; B resists (2 subjects - subject A) | - |  |
| `18_05` | A pulls B by the elbow; B resists (2 subjects - subject A) | - |  |
| `18_06` | A pulls B by the elbow; B resists (2 subjects - subject A) | - |  |
| `18_07` | navigate busy sidewalk; A leads the way, takes B by the arm (2 subjects - subject A) | - |  |
| `18_08` | conversation - explain with hand gestures (2 subjects - subject A) | - |  |
| `18_09` | conversation - explain with hand gestures, walk (2 subjects - subject A) | - |  |
| `18_10` | quarrel - angry hand gestures (2 subjects - subject A) | - |  |
| `18_11` | quarrel - angry hand gestures (2 subjects - subject A) | - |  |
| `18_12` | friends meet, hang out; A sits, B joins A (2 subjects - subject A) | - |  |
| `18_13` | run, scramble for last seat (2 subjects - subject A) | - |  |
| `18_14` | run, scramble for last seat (2 subjects - subject A) | - |  |
| `18_15` | chicken dance (2 subjects - subject A) | - |  |

### 피험자 19

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `19_01` | walk, shake hands (2 subjects - subject B) | - |  |
| `19_02` | walk, shake hands (2 subjects - subject B) | - |  |
| `19_03` | A pulls B; B resists (2 subjects - subject B) | - |  |
| `19_04` | A pulls B; B resists (2 subjects - subject B) | - |  |
| `19_05` | A pulls B by the elbow; B resists (2 subjects - subject B) | - |  |
| `19_06` | A pulls B by the elbow; B resists (2 subjects - subject B) | - |  |
| `19_07` | navigate busy sidewalk; A leads the way, takes B by the arm (2 subjects - subject B) | - |  |
| `19_08` | conversation - explain with hand gestures (2 subjects - subject B) | - |  |
| `19_09` | conversation - explain with hand gestures, walk (2 subjects - subject B) | - |  |
| `19_10` | quarrel - angry hand gestures (2 subjects - subject B) | - |  |
| `19_11` | quarrel - angry hand gestures (2 subjects - subject B) | - |  |
| `19_12` | friends meet, hang out; A sits, B joins A (2 subjects - subject B) | - |  |
| `19_13` | run, scramble for last seat (2 subjects - subject B) | - |  |
| `19_14` | run, scramble for last seat (2 subjects - subject B) | - |  |
| `19_15` | chicken dance (2 subjects - subject B) | - |  |

### 피험자 20

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `20_01` | chicken dance (2 subjects - subject A) | - |  |
| `20_02` | link arms, walk (2 subjects - subject A) | - |  |
| `20_03` | link arms, walk (2 subjects - subject A) | - |  |
| `20_04` | synchronized walk (2 subjects - subject A) | - |  |
| `20_05` | synchronized walk (2 subjects - subject A) | - |  |
| `20_06` | soldiers march (2 subjects - subject A) | - |  |
| `20_07` | soldiers march (2 subjects - subject A) | - |  |
| `20_08` | zombie march (2 subjects - subject A) | - |  |
| `20_09` | nursery rhyme - ring around the rosey (2 subjects - subject A) | - |  |
| `20_10` | 360-degree two-person whip (2 subjects - subject A) | - |  |
| `20_11` | high-five, walk (2 subjects - subject A) | - |  |
| `20_12` | low-five, walk (2 subjects - subject A) | - |  |
| `20_13` | blind man's bluff (blindfold tag) (2 subjects - subject A) | - |  |

### 피험자 21

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `21_01` | chicken dance (2 subjects - subject B) | - |  |
| `21_02` | link arms, walk (2 subjects - subject B) | - |  |
| `21_03` | link arms, walk (2 subjects - subject B) | - |  |
| `21_04` | synchronized walk (2 subjects - subject B) | - |  |
| `21_05` | synchronized walk (2 subjects - subject B) | - |  |
| `21_06` | soldiers march (2 subjects - subject B) | - |  |
| `21_07` | soldiers march (2 subjects - subject B) | - |  |
| `21_08` | zombie march (2 subjects - subject B) | - |  |
| `21_09` | nursery rhyme - ring around the rosey (2 subjects - subject B) | - |  |
| `21_10` | 360-degree two-person whip (2 subjects - subject B) | - |  |
| `21_11` | high-five, walk (2 subjects - subject B) | - |  |
| `21_12` | low-five, walk (2 subjects - subject B) | - |  |
| `21_13` | blind man's bluff (blindfold tag) (2 subjects - subject B) | - |  |

### 피험자 22

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `22_01` | B sits; A pulls up B (2 subjects - subject A) | - |  |
| `22_02` | A sits; B pulls up A (2 subjects - subject A) | - |  |
| `22_03` | A sits, holds face in hands; B kneels, comforts A (2 subjects - subject A) | - |  |
| `22_04` | B comforts A, puts one hand on A's shoulder (2 subjects - subject A) | - |  |
| `22_05` | A comforts B, puts both hands on B's shoulders (2 subjects - subject A) | - |  |
| `22_06` | B comforts A, puts both hands on A's shoulders (2 subjects - subject A) | - |  |
| `22_07` | A comforts B, puts one hand on B's shoulder (2 subjects - subject A) | - |  |
| `22_08` | hold hands, swing arms, walk (2 subjects - subject A) | - |  |
| `22_09` | A gives B a shoulder rub; B sits, A stands (2 subjects - subject A) | - |  |
| `22_10` | A shelters B, a younger child, from harm (2 subjects - subject A) | - |  |
| `22_11` | B shelters A, a younger child, from harm (2 subjects - subject A) | - |  |
| `22_12` | A stumbles into B (2 subjects - subject A) | - |  |
| `22_13` | A passes soda to B; both drink (2 subjects - subject A) | - |  |
| `22_14` | alternating squats (2 subjects - subject A) | - |  |
| `22_15` | alternating jumping jacks (2 subjects - subject A) | - |  |
| `22_16` | synchronized jumping jacks (2 subjects - subject A) | - |  |
| `22_17` | rush up, arm wrestle (2 subjects - subject A) | - |  |
| `22_18` | A stares down B, leans with hands on high stool (2 subjects - subject A) | - |  |
| `22_19` | B stares down A, leans with hands on high stool (2 subjects - subject A) | - |  |
| `22_20` | violence - A picks up high stool, threatens to strike B (2 subjects - subject A) | - |  |
| `22_21` | conversation - B pounds high stool, points at A (2 subjects - subject A) | - |  |
| `22_22` | walk; B catches keys thrown by A (2 subjects - subject A) | - |  |
| `22_23` | walk; A catches keys thrown by B (2 subjects - subject A) | - |  |
| `22_24` | walk; B catches wallet thrown by A (2 subjects - subject A) | - |  |
| `22_25` | walk; A catches wallet thrown by B (2 subjects - subject A) | - |  |

### 피험자 23

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `23_01` | B sits; A pulls up B (subjects - subject B) | - |  |
| `23_02` | A sits; B pulls up A (subjects - subject B) | - |  |
| `23_03` | A sits, holds face in hands; B kneels, comforts A (2 subjects - subject B) | - |  |
| `23_04` | B comforts A, puts one hand on A's shoulder (2 subjects - subject B) | - |  |
| `23_05` | A comforts B, puts both hands on B's shoulders (2 subjects - subject B) | - |  |
| `23_06` | B comforts A, puts both hands on A's shoulders (2 subjects - subject B) | - |  |
| `23_07` | A comforts B, puts one hand on B's shoulder (2 subjects - subject B) | - |  |
| `23_08` | hold hands, swing arms, walk (2 subjects - subject B) | - |  |
| `23_09` | A gives B a shoulder rub; B sits, A stands (subjects - subject B) | - |  |
| `23_10` | A shelters B, a younger child, from harm (2 subjects - subject B) | - |  |
| `23_11` | B shelters A, a younger child, from harm (2 subjects - subject B) | - |  |
| `23_12` | A stumbles into B (2 subjects - subject B) | - |  |
| `23_13` | A passes soda to B; both drink (2 subjects - subject B) | - |  |
| `23_14` | alternating squats (2 subjects - subject B) | - |  |
| `23_15` | alternating jumping jacks (2 subjects - subject B) | - |  |
| `23_16` | synchronized jumping jacks (2 subjects - subject B) | - |  |
| `23_17` | rush up, arm wrestle (2 subjects - subject B) | - |  |
| `23_18` | A stares down B, leans with hands on high stool (2 subjects - subject B) | - |  |
| `23_19` | B stares down A, leans with hands on high stool (2 subjects - subject B) | - |  |
| `23_20` | violence - A picks up high stool, threatens to strike B (2 subjects - subject B) | - |  |
| `23_21` | conversation - B pounds high stool, points at A (2 subjects - subject B) | - |  |
| `23_22` | walk; B catches keys thrown by A (2 subjects - subject B) | - |  |
| `23_23` | walk; A catches keys thrown by B (2 subjects - subject B) | - |  |
| `23_24` | walk; B catches wallet thrown by A (2 subjects - subject B) | - |  |
| `23_25` | walk; A catches wallet thrown by B (2 subjects - subject B) | - |  |

### 피험자 24

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `24_01` | nursery rhyme - "I'm a little teapot..." | 17.3 |  |

### 피험자 25

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `25_01` | nursery rhyme - "I'm a little teapot..." | 13.5 |  |

### 피험자 26

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `26_01` | walk | 7.4 |  |
| `26_02` | basketball signals | 50.5 |  |
| `26_03` | nursery rhyme - "I'm a little teapot..." | 18.6 |  |
| `26_04` | nursery rhyme - "I'm a little teapot..." | - |  |
| `26_05` | Alaska vacation | 30.3 |  |
| `26_06` | Alaska vacation | - |  |
| `26_07` | nursery rhyme - Cock Robin | - |  |
| `26_08` | nursery rhyme - Cock Robin | - |  |
| `26_09` | bend, pick up | - |  |
| `26_10` | bend, lift | 5.8 |  |
| `26_11` | bend, lift | - |  |

### 피험자 27

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `27_01` | walk | 8.6 |  |
| `27_02` | basketball signals | 29.7 |  |
| `27_03` | nursery rhyme - "I'm a little teapot..." | 17.9 |  |
| `27_04` | Alaskan vacation | 30.4 |  |
| `27_05` | nursery rhyme - Cock Robin | 64.3 |  |
| `27_06` | basketball signals | 23.9 |  |
| `27_07` | nursery rhyme - "I'm a little teapot..." | 14.9 |  |
| `27_08` | Alaskan vacation | 29.3 |  |
| `27_09` | Alaskan vacation | 31.5 |  |
| `27_10` | nursery rhyme - Cock Robin | 65.0 |  |
| `27_11` | prairie dog (human subject) | 16.1 |  |

### 피험자 28

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `28_01` | basketball signals | 26.1 |  |
| `28_02` | nursery rhyme - "I'm a little teapot..." | 17.1 |  |
| `28_03` | Alaskan vacation | 31.4 |  |
| `28_04` | nursery rhyme - Cock Robin | 65.8 |  |
| `28_05` | basketball signals | 27.0 |  |
| `28_06` | nursery rhyme - "I'm a little teapot..." | 18.4 |  |
| `28_07` | Alaskan vacation | 30.5 |  |
| `28_08` | nursery rhyme - Cock Robin | - |  |
| `28_09` | prairie dog (human subject) | 14.3 |  |
| `28_10` | whale (human subject) | 17.3 |  |
| `28_11` | bear (human subject) | 55.1 |  |
| `28_12` | dog (human subject) | 42.9 |  |
| `28_13` | snake (human subject) | 49.1 |  |
| `28_14` | chicken (human subject) | 31.2 |  |
| `28_15` | monkey (human subject) | 28.7 |  |
| `28_16` | mouse (human subject) | 46.7 |  |
| `28_17` | cat (human subject) | 44.5 |  |
| `28_18` | elephant (human subject) | - |  |
| `28_19` | dinosaur (human subject) | 37.7 |  |

### 피험자 29

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `29_01` | walk | 11.0 |  |
| `29_02` | basketball signals | 26.0 |  |
| `29_03` | nursery rhyme - "I'm a little teapot..." | 18.8 |  |
| `29_04` | Alaskan vacation | 31.9 |  |
| `29_05` | Alaskan vacation | 31.0 |  |
| `29_06` | nursery rhyme - Cock Robin | 67.0 |  |
| `29_07` | basketball signals | 26.2 |  |
| `29_08` | nursery rhyme - "I'm a little teapot..." | 19.0 |  |
| `29_09` | Alaskan vacation | 31.1 |  |
| `29_10` | nursery rhyme - Cock Robin | 66.3 |  |
| `29_11` | Alaskan vacation | 31.0 |  |
| `29_12` | Alaskan vacation | 125.2 |  |
| `29_13` | Alaskan vacation | 122.2 |  |
| `29_14` | prairie dog (human subject) | 28.1 |  |
| `29_15` | whale (human subject) | 36.9 |  |
| `29_16` | bear (human subject) | 36.9 |  |
| `29_17` | dog (human subject) | 35.9 |  |
| `29_18` | cat (human subject) | 49.7 |  |
| `29_19` | fish (human subject) | 29.7 |  |
| `29_20` | elephant (human subject) | 31.1 |  |
| `29_21` | mouse (human subject) | 33.3 |  |
| `29_22` | chicken (human subject) | 27.2 |  |
| `29_23` | dinosaur (human subject) | 38.2 |  |
| `29_24` | snake (human subject) | 35.4 |  |
| `29_25` | monkey (human subject) | 37.0 |  |

### 피험자 30

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `30_01` | basketball signals | 26.9 |  |
| `30_02` | nursery rhyme - "I'm a little teapot..." | 19.9 |  |
| `30_03` | Alaskan vacation | 34.8 |  |
| `30_04` | Alaskan vacation | 30.8 |  |
| `30_05` | nursery rhyme - Cock Robin | - |  |
| `30_06` | nursery rhyme - Cock Robin | 67.0 |  |
| `30_07` | basketball signals | 26.3 |  |
| `30_08` | nursery rhyme - "I'm a little teapot..." | 18.3 |  |
| `30_09` | Alaskan vacation | 31.3 |  |
| `30_10` | nursery rhyme - Cock Robin | 66.4 |  |
| `30_11` | Alaskan vacation | 124.2 |  |
| `30_12` | Alaskan vacation | 123.0 |  |
| `30_13` | prairie dog (human subject) | 16.4 |  |
| `30_14` | whale (human subject) | 21.5 |  |
| `30_15` | bear (human subject) | 26.8 |  |
| `30_16` | dog (human subject) | 30.2 |  |
| `30_17` | cat (human subject) | 24.2 |  |
| `30_18` | elephant (human subject) | 29.7 |  |
| `30_19` | mouse (human subject) | 34.1 |  |
| `30_20` | chicken (human subject) | 28.5 |  |
| `30_21` | snake (human subject) | 34.0 |  |
| `30_22` | Tyrannosaurus rex (human subject) | 27.4 |  |
| `30_23` | monkey (human subject) | 32.7 |  |

### 피험자 31

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `31_01` | basketball signals | 33.0 |  |
| `31_02` | nursery rhyme - "I'm a little teapot..." | 18.9 |  |
| `31_03` | Alaskan vacation | 30.8 |  |
| `31_04` | nursery rhyme - Cock Robin | - |  |
| `31_05` | basketball signals | 26.5 |  |
| `31_06` | nursery rhyme - "I'm a little teapot..." | 17.6 |  |
| `31_07` | Alaskan vacation | 30.8 |  |
| `31_08` | nursery rhyme - Cock Robin | 65.5 |  |
| `31_09` | Alaskan vacation | 122.1 |  |
| `31_10` | Alaskan vacation | 113.8 |  |
| `31_11` | prairie dog (human subject) | 32.3 |  |
| `31_12` | whale (human subject) | - |  |
| `31_13` | bear (human subject) | 32.4 |  |
| `31_14` | dog (human subject) | 31.6 |  |
| `31_15` | cat (human subject) | 30.9 |  |
| `31_16` | elephant (human subject) | 32.6 |  |
| `31_17` | Tyrannosaurus rex (human subject) | 33.3 |  |
| `31_18` | mouse (human subject) | 35.3 |  |
| `31_19` | chicken (human subject) | 33.3 |  |
| `31_20` | snake (human subject) | 32.9 |  |
| `31_21` | monkey (human subject) | 34.0 |  |

### 피험자 32

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `32_01` | walk | 4.0 |  |
| `32_02` | walk | 3.6 |  |
| `32_03` | basketball signals | 27.0 |  |
| `32_04` | nursery rhyme - "I'm a little teapot..." | 19.2 |  |
| `32_05` | Alaskan vacation | 30.4 |  |
| `32_06` | nursery rhyme - Cock Robin | 65.4 |  |
| `32_07` | basketball signals | 26.0 |  |
| `32_08` | nursery rhyme - "I'm a little teapot..." | 18.7 |  |
| `32_09` | Alaskan vacation | 31.1 |  |
| `32_10` | nursery rhyme - Cock Robin | 66.2 |  |
| `32_11` | Alaskan vacation | 122.4 |  |
| `32_12` | Alaskan vacation | 122.5 |  |
| `32_13` | prairie dog (human subject) | 26.9 |  |
| `32_14` | bear (human subject) | 22.2 |  |
| `32_15` | dog (human subject) | 30.2 |  |
| `32_16` | cat (human subject) | 36.6 |  |
| `32_17` | elephant (human subject) | 27.6 |  |
| `32_18` | mouse (human subject) | 25.3 |  |
| `32_19` | chicken (human subject) | 19.3 |  |
| `32_20` | Tyrannosaurus rex (human subject) | 29.6 |  |
| `32_21` | snake (human subject) | 17.0 |  |
| `32_22` | monkey (human subject) | 23.7 |  |

### 피험자 33

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `33_01` | football - throw, catch (2 subjects - subject A) | - |  |
| `33_02` | football - throw, catch, jump around (2 subjects - subject A) | - |  |

### 피험자 34

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `34_01` | football - throw, catch (2 subjects - subject B) | - |  |
| `34_02` | football - throw, catch, jump around (2 subjects - subject B) | - |  |

### 피험자 35

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `35_01` | walk | 3.0 |  |
| `35_02` | walk | 3.4 |  |
| `35_03` | walk | 3.6 |  |
| `35_04` | walk | 3.6 |  |
| `35_05` | walk | 3.6 |  |
| `35_06` | walk | 3.6 |  |
| `35_07` | walk | 3.0 |  |
| `35_08` | walk | 3.8 |  |
| `35_09` | walk | 3.2 |  |
| `35_10` | walk | 3.6 |  |
| `35_11` | walk | 3.2 |  |
| `35_12` | walk | 3.3 |  |
| `35_13` | walk | 3.8 |  |
| `35_14` | walk | 3.4 |  |
| `35_15` | walk | 3.4 |  |
| `35_16` | walk | 3.7 |  |
| `35_17` | run/jog | 1.4 |  |
| `35_18` | run/jog | 1.5 |  |
| `35_19` | run/jog | 1.3 |  |
| `35_20` | run/jog | 1.4 |  |
| `35_21` | run/jog | 1.3 |  |
| `35_22` | run/jog | 1.4 |  |
| `35_23` | run/jog | 1.4 |  |
| `35_24` | run/jog | 1.2 |  |
| `35_25` | run/jog | 1.4 |  |
| `35_26` | run/jog | 1.1 |  |
| `35_27` | navigate around obstacles | 81.7 |  |
| `35_28` | walk | 3.5 |  |
| `35_29` | walk | 4.1 |  |
| `35_30` | walk | 3.4 |  |
| `35_31` | walk | 3.5 |  |
| `35_32` | walk | 3.3 |  |
| `35_33` | walk | 3.5 |  |
| `35_34` | walk | 3.5 |  |

### 피험자 36

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `36_01` | walk on uneven terrain | 4.6 |  |
| `36_02` | walk forward, turn around, walk back | 35.6 |  |
| `36_03` | walk forward, turn around, walk back | 32.1 |  |
| `36_04` | walk on uneven terrain | 31.1 |  |
| `36_05` | walk on uneven terrain | 35.0 |  |
| `36_06` | walk on uneven terrain | 32.5 |  |
| `36_07` | walk on uneven terrain | 31.4 |  |
| `36_08` | walk on uneven terrain | 30.9 |  |
| `36_09` | walk forward, turn around, walk back | 32.4 |  |
| `36_10` | walk on uneven terrain | 31.9 |  |
| `36_11` | walk on uneven terrain | 34.7 |  |
| `36_12` | walk on uneven terrain | 38.2 |  |
| `36_13` | walk on uneven terrain | 35.4 |  |
| `36_14` | walk on uneven terrain | 34.5 |  |
| `36_15` | walk on uneven terrain | 34.7 |  |
| `36_16` | walk on uneven terrain | 36.6 |  |
| `36_17` | walk on uneven terrain | 36.3 |  |
| `36_18` | walk on uneven terrain | 35.9 |  |
| `36_19` | walk on uneven terrain | 34.9 |  |
| `36_20` | walk on uneven terrain | 34.1 |  |
| `36_21` | walk on uneven terrain | 33.6 |  |
| `36_22` | walk on uneven terrain | 35.9 |  |
| `36_23` | walk on uneven terrain | 36.6 |  |
| `36_24` | walk on uneven terrain | 34.6 |  |
| `36_25` | walk on uneven terrain | 39.0 |  |
| `36_26` | walk on uneven terrain | 35.3 |  |
| `36_27` | walk on uneven terrain | 35.4 |  |
| `36_28` | walk on uneven terrain | 19.9 |  |
| `36_29` | walk on uneven terrain | 37.2 |  |
| `36_30` | walk on uneven terrain | 36.8 |  |
| `36_31` | walk on uneven terrain | 31.1 |  |
| `36_32` | walk on uneven terrain | 37.2 |  |
| `36_33` | walk on uneven terrain | 35.9 |  |
| `36_34` | walk on uneven terrain | 36.1 |  |
| `36_35` | walk on uneven terrain | 36.2 |  |
| `36_36` | walk on uneven terrain | 39.9 |  |
| `36_37` | jump/hop on uneven terrain | - |  |

### 피험자 37

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `37_01` | slow walk | 4.3 |  |

### 피험자 38

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `38_01` | walk | 2.9 |  |
| `38_02` | walk | 3.5 |  |
| `38_03` | run around in a circle | 6.3 |  |
| `38_04` | walk around, frequent turns, cyclic walk along a line | 71.9 |  |

### 피험자 39

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `39_01` | walk | 3.1 |  |
| `39_02` | walk | 3.3 |  |
| `39_03` | walk | 3.4 |  |
| `39_04` | walk | 3.4 |  |
| `39_05` | walk | 3.3 |  |
| `39_06` | walk | 3.1 |  |
| `39_07` | walk | 3.1 |  |
| `39_08` | walk | 2.9 |  |
| `39_09` | walk | 3.3 |  |
| `39_10` | walk | 3.3 |  |
| `39_11` | walk forward, turn around, walk back | 7.5 |  |
| `39_12` | walk | 3.6 |  |
| `39_13` | walk | 3.1 |  |
| `39_14` | walk | 3.3 |  |

### 피험자 40

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `40_02` | navigate - walk forward, backward, on a diagonal | 41.6 |  |
| `40_03` | navigate - walk forward, backward, on a diagonal | 51.6 |  |
| `40_04` | navigate - walk forward, backward, on a diagonal | 49.1 |  |
| `40_05` | navigate - walk forward, backward, on a diagonal | 50.7 |  |
| `40_06` | climb, step over, sit on, jump over stepstool | 54.9 |  |
| `40_07` | climb, step over, jump over stepstool | 57.4 |  |
| `40_08` | climb, step over, jump over stepstool | 58.0 |  |
| `40_09` | climb, step over, jump over stepstool | 43.1 |  |
| `40_10` | wait for bus | 51.8 |  |
| `40_11` | wait for bus | 50.2 |  |
| `40_12` | basketball signals | 70.3 |  |

### 피험자 41

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `41_02` | navigate - walk forward, backward, sideways, on a diagonal | 36.6 |  |
| `41_03` | navigate - walk forward, backward, sideways, on a diagonal | 49.6 |  |
| `41_04` | navigate - walk forward, backward, on a diagonal | 58.9 |  |
| `41_05` | navigate - walk forward, backward, on a diagonal | 60.2 |  |
| `41_06` | navigate - walk forward, backward, on a diagonal | 59.2 |  |
| `41_07` | climb, step over, jump over, navigate around stepstool | 62.8 |  |
| `41_08` | climb, step over, jump over, navigate around stepstool | 66.2 |  |
| `41_09` | climb, step over, jump over, navigate around stepstool | 64.3 |  |
| `41_10` | basketball signals | 32.6 |  |
| `41_11` | basketball signals | 26.3 |  |

### 피험자 42

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `42_01` | stretch - rotate head, shoulders, arms, legs | - |  |

### 피험자 43

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `43_01` | walk | 3.5 |  |
| `43_02` | playground - grip bar, swing body | 7.5 |  |
| `43_03` | playground - grip bar, swing body | 7.0 |  |

### 피험자 45

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `45_01` | walk | 3.8 |  |

### 피험자 46

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `46_01` | walk | 5.1 |  |

### 피험자 47

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `47_01` | walk forward, turn around, walk back | 11.0 |  |

### 피험자 49

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `49_01` | walk | 5.4 |  |
| `49_02` | jump up and down, hop on one foot | 17.4 |  |
| `49_03` | jump up and down, hop on one foot | 12.5 |  |
| `49_04` | run, leap | 2.1 |  |
| `49_05` | run, leap | 1.4 |  |
| `49_06` | cartwheel | 4.0 |  |
| `49_07` | cartwheel | 3.9 |  |
| `49_08` | cartwheels | 4.8 |  |
| `49_09` | dance - arms held high, side arabesque | 16.0 |  |
| `49_10` | dance - fold in from side arabesque, curl inwards | 11.9 |  |
| `49_11` | dance - fold in from side arabesque, curl inwards | 10.0 |  |
| `49_12` | dance - lean forward, bring back leg forward, arching arms | 9.4 |  |
| `49_13` | dance - fold in from side arabesque, curl inwards | 4.4 |  |
| `49_14` | dance - lean forward, bring back leg forward, arching arms | 5.2 |  |
| `49_15` | static dance pose - folded in, head lowered, leg bent | 7.9 |  |
| `49_16` | dance - fold in from side arabesque, curl inwards | 9.5 |  |
| `49_17` | dance - lean forward, bring back leg forward, arching arms | 6.2 |  |
| `49_18` | balance on one leg, outstretched arms | 9.2 |  |
| `49_19` | balance on one leg, outstretched arms | 8.0 |  |
| `49_20` | balance on one leg, outstretched arms | 7.5 |  |
| `49_21` | acrobatics - spin/twirl, hang on ropes | 20.2 |  |
| `49_22` | dance - lean back on bent leg, balance, bend elbow by ear | 10.7 |  |

### 피험자 54

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `54_01` | monkey (human subject) | 16.0 |  |
| `54_02` | bear (human subject) | 25.1 |  |
| `54_03` | penguin (human subject) | 23.1 |  |
| `54_04` | pterosaur (human subject) | 38.4 |  |
| `54_05` | pterosaur (human subject) | 8.9 |  |
| `54_06` | pterosaur (human subject) | 65.7 |  |
| `54_07` | prairie dog (human subject) | 33.4 |  |
| `54_08` | roadrunner (human subject) | 35.3 |  |
| `54_09` | insect/praying mantis (human subject) | 16.1 |  |
| `54_10` | ghost (human subject) | 39.3 |  |
| `54_11` | penguin (human subject) | 28.4 |  |
| `54_12` | dragon (human subject) | 19.1 |  |
| `54_13` | dragon (human subject) | 13.6 |  |
| `54_14` | monkey (human subject) | 13.6 |  |
| `54_15` | prairie dog (human subject) | 34.4 |  |
| `54_16` | superhero | 34.4 |  |
| `54_17` | squirrel (human subject) | 23.5 |  |
| `54_18` | squirrel (human subject) | 16.9 |  |
| `54_19` | squirrel - robotic like motion (human subject) | 40.8 |  |
| `54_20` | follow path, walk around obstacles | 51.6 |  |
| `54_21` | follow path, walk around obstacles | 58.2 |  |
| `54_22` | follow path, walk around obstacles | 21.1 |  |
| `54_23` | monkey (human subject) | 35.8 |  |
| `54_24` | hummingbird (human subject) | 22.4 |  |
| `54_25` | chicken (human subject) | 37.9 |  |
| `54_26` | chicken (human subject) | 16.3 |  |
| `54_27` | chicken (human subject) | 28.7 |  |

### 피험자 55

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `55_01` | dance, whirl | 15.1 |  |
| `55_02` | lambada dance | 18.2 |  |
| `55_03` | genie (human subject) | 37.8 |  |
| `55_04` | walk | 4.4 |  |
| `55_05` | hummingbird (human subject) | 23.4 |  |
| `55_06` | chicken (human subject) | 77.3 |  |
| `55_07` | chicken (human subject) | 38.1 |  |
| `55_08` | monkey (human subject) | 44.5 |  |
| `55_09` | monkey (human subject) | 35.2 |  |
| `55_10` | hummingbird (human subject) | 11.3 |  |
| `55_11` | animal (human subject) | 36.4 |  |
| `55_12` | dancing bear (human subject) | 17.3 |  |
| `55_13` | insect/praying mantis (human subject) | 81.2 |  |
| `55_14` | prairie dog (human subject) | 43.4 |  |
| `55_15` | roadrunner (human subject) | 80.8 |  |
| `55_16` | panda (human subject) | 50.7 |  |
| `55_17` | ghost (human subject) | 51.5 |  |
| `55_18` | penguin (human subject) | 44.9 |  |
| `55_19` | dragon (human subject) | 39.5 |  |
| `55_20` | hippo ballerina (human subject) | 38.3 |  |
| `55_21` | pterosaur (human subject) | 29.2 |  |
| `55_22` | superhero | 54.5 |  |
| `55_23` | devil | 49.8 |  |
| `55_24` | various animals (human subject) | 79.3 |  |
| `55_25` | dancing animal (human subject) | 26.6 |  |
| `55_26` | monkey (human subject) | 34.2 |  |
| `55_27` | dancing ant (human subject) | 41.7 |  |
| `55_28` | monkey/bear (human subject) | 69.2 |  |

### 피험자 56

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `56_01` | walk around | 12.6 |  |
| `56_02` | vignettes - fists up, wipe window, yawn, stretch, angrily grab, smash against wall | 28.5 |  |
| `56_03` | vignettes - fists up, wipe window, yawn, stretch, angrily grab, smash against wall, lift open window, throw punches, skip | 51.8 |  |
| `56_04` | vignettes - fists up, wipe window, grab, lift open window, throw punches, yawn, stretch, walk, jump | 56.4 |  |
| `56_05` | vignettes - walk, drink water, run/jog, jump, wipe window, lift open window, throw punches, yawn, stretch | 61.3 |  |
| `56_06` | vignettes - throw punches, grab, skip, yawn, stretch, leap, lift open window, walk, jump/bound | 56.5 |  |
| `56_07` | vignettes - yawn, stretch, walk, run/jog, angrily grab, jump, skip, halt | 78.5 |  |
| `56_08` | vignettes - lift open window, smash against wall, hop, walk, run/jog, yawn, stretch | 34.8 |  |

### 피험자 60

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `60_01` | salsa dance | 37.4 |  |
| `60_02` | salsa dance | 35.0 |  |
| `60_03` | salsa dance | 30.5 |  |
| `60_04` | salsa dance | 31.2 |  |
| `60_05` | salsa dance | 28.0 |  |
| `60_06` | salsa dance | 29.5 |  |
| `60_07` | salsa dance | - |  |
| `60_08` | salsa dance | 57.0 |  |
| `60_09` | salsa dance | 42.9 |  |
| `60_10` | salsa dance | 19.9 |  |
| `60_11` | salsa dance | 35.1 |  |
| `60_12` | salsa dance | 28.2 |  |
| `60_13` | salsa dance | 37.9 |  |
| `60_14` | salsa dance | 32.5 |  |
| `60_15` | salsa dance | 35.7 |  |

### 피험자 61

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `61_01` | salsa dance | 37.4 |  |
| `61_02` | salsa dance | 35.0 |  |
| `61_03` | salsa dance | 30.5 |  |
| `61_04` | salsa dance | 31.2 |  |
| `61_05` | salsa dance | - |  |
| `61_06` | salsa dance | - |  |
| `61_07` | salsa dance | - |  |
| `61_08` | salsa dance | - |  |
| `61_09` | salsa dance | 42.9 |  |
| `61_10` | salsa dance | 19.9 |  |
| `61_11` | salsa dance | - |  |
| `61_12` | salsa dance | 28.2 |  |
| `61_13` | salsa dance | - |  |
| `61_14` | salsa dance | - |  |
| `61_15` | salsa dance | 35.7 |  |

### 피험자 62

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `62_01` | bolt loosening, wrench | 18.0 |  |
| `62_02` | bolt tightening, wrench | 17.3 |  |
| `62_03` | sawing, hand saw | 22.9 |  |
| `62_04` | screwing | 22.6 |  |
| `62_05` | screwing | 19.3 |  |
| `62_06` | unscrewing | 44.2 |  |
| `62_07` | hammering a nail | 18.6 |  |
| `62_08` | hammering a nail | 14.9 |  |
| `62_09` | pulling a nail | 19.0 |  |
| `62_10` | hammering sequence | 33.7 |  |
| `62_11` | cleaning up | 61.8 |  |
| `62_12` | hard days drink | 16.4 |  |
| `62_13` | moving a stool | 21.1 |  |
| `62_14` | opening umbrella | 11.2 |  |
| `62_15` | opening umbrella | 11.3 |  |
| `62_16` | closing umbrella | 10.5 |  |
| `62_17` | opening and closing umbrella | 12.0 |  |
| `62_18` | closing a box | 9.4 |  |
| `62_19` | opening a box | 11.0 |  |
| `62_20` | closing, moving and opening a box | 16.1 |  |
| `62_21` | coiling a rope | 57.5 |  |
| `62_22` | dynamic calibration | 17.6 |  |
| `62_23` | bolt tightening | 15.9 |  |
| `62_24` | bolt tightening, with putting bolt in | 48.1 |  |
| `62_25` | bolt loosening, wrench | 22.1 |  |

### 피험자 63

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `63_01` | Swing | 3.7 |  |
| `63_02` | Unknown | 4.1 |  |
| `63_03` | Unknown | 3.7 |  |
| `63_04` | Unknown | 3.4 |  |
| `63_05` | Unknown | 3.2 |  |
| `63_06` | Unknown | 4.4 |  |
| `63_07` | Unknown | 3.1 |  |
| `63_08` | Unknown | 3.0 |  |
| `63_09` | Unknown | 3.8 |  |
| `63_10` | Unknown | 4.7 |  |
| `63_11` | Unknown | 4.9 |  |
| `63_12` | Unknown | 4.2 |  |
| `63_13` | Unknown | 3.6 |  |
| `63_14` | Unknown | 4.7 |  |
| `63_15` | Unknown | 3.5 |  |
| `63_16` | Unknown | 5.2 |  |
| `63_17` | Unknown | 4.5 |  |
| `63_18` | Unknown | 4.0 |  |
| `63_19` | Unknown | 3.1 |  |
| `63_20` | Unknown | 4.9 |  |
| `63_21` | Unknown | 3.6 |  |
| `63_22` | Unknown | 4.4 |  |
| `63_23` | Unknown | 4.3 |  |
| `63_24` | Unknown | 4.8 |  |
| `63_25` | Unknown | 5.1 |  |
| `63_26` | Unknown | 4.7 |  |
| `63_27` | Unknown | 4.7 |  |
| `63_28` | Unknown | 4.3 |  |
| `63_29` | Unknown | 4.8 |  |
| `63_30` | Unknown | 5.1 |  |

### 피험자 64

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `64_01` | Swing | 3.7 |  |
| `64_02` | Swing | 4.1 |  |
| `64_03` | Swing | 3.7 |  |
| `64_04` | Swing | 3.4 |  |
| `64_05` | Swing | 3.2 |  |
| `64_06` | Swing | 4.4 |  |
| `64_07` | Swing | 3.1 |  |
| `64_08` | Swing | 3.0 |  |
| `64_09` | Swing | 3.8 |  |
| `64_10` | Swing | 4.7 |  |
| `64_11` | Putt | 4.9 |  |
| `64_12` | Putt | 4.2 |  |
| `64_13` | Putt | 3.6 |  |
| `64_14` | Putt | 4.7 |  |
| `64_15` | Putt | 3.5 |  |
| `64_16` | Placing Tee | 5.2 |  |
| `64_17` | Placing Tee | 4.5 |  |
| `64_18` | Placing Tee | 4.0 |  |
| `64_19` | Placing Tee | 3.1 |  |
| `64_20` | Placing Tee | 4.9 |  |
| `64_21` | Placing Ball | 3.6 |  |
| `64_22` | Placing Ball | 4.4 |  |
| `64_23` | Placing Ball | 4.3 |  |
| `64_24` | Placing Ball | 4.8 |  |
| `64_25` | Placing Ball | 5.1 |  |
| `64_26` | Picking up Ball | 4.7 |  |
| `64_27` | Picking up Ball | 4.7 |  |
| `64_28` | Picking up Ball | 4.3 |  |
| `64_29` | Picking up Ball | 4.8 |  |
| `64_30` | Picking up Ball | 5.1 |  |

### 피험자 69

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `69_01` | walk forward | - |  |
| `69_02` | walk forward | - |  |
| `69_03` | walk forward | - |  |
| `69_04` | walk forward | - |  |
| `69_05` | walk forward | - |  |
| `69_06` | walk and turn (repeated) | - |  |
| `69_07` | walk and turn (repeated) | - |  |
| `69_08` | walk and turn (repeated) | - |  |
| `69_09` | walk and turn (repeated) | - |  |
| `69_10` | walk and turn (repeated) | - |  |
| `69_11` | walk and turn (repeated) | - |  |
| `69_12` | walk and turn both directions (repeated) | - |  |
| `69_13` | walk, turn in place (repeated) | - |  |
| `69_14` | walk, turn in place (repeated) | - |  |
| `69_15` | walk, turn in place (repeated) | - |  |
| `69_16` | turn in place | - |  |
| `69_17` | turn in place | - |  |
| `69_18` | turn in place (opposite direction) | - |  |
| `69_19` | turn in place (opposite direction) | - |  |
| `69_20` | walk forward 90 degree right turn | - |  |
| `69_21` | walk forward 90 degree right turn | - |  |
| `69_22` | walk forward 90 degree right turn | - |  |
| `69_23` | walk forward 90 degree right turn | - |  |
| `69_24` | walk forward 90 degree left turn | - |  |
| `69_25` | walk forward 90 degree left turn | - |  |
| `69_26` | walk forward 90 degree left turn | - |  |
| `69_27` | walk forward 90 degree left turn | - |  |
| `69_28` | walk forward 90 degree smooth right turn | - |  |
| `69_29` | walk forward 90 degree smooth right turn | - |  |
| `69_30` | walk forward 90 degree smooth right turn | - |  |
| `69_31` | walk forward 90 degree smooth left turn | - |  |
| `69_32` | walk forward 90 degree smooth left turn | - |  |
| `69_33` | walk forward 90 degree smooth left turn | - |  |
| `69_34` | walk backwards and turn | - |  |
| `69_35` | walk backwards and turn | - |  |
| `69_36` | walk backwards and turn | - |  |
| `69_37` | walk backwards and turn | - |  |
| `69_38` | walk backwards and turn (repeated) | - |  |
| `69_39` | walk backward, turn in place | - |  |
| `69_40` | walk backward, turn in place | - |  |
| `69_41` | walk backward, turn in place | - |  |
| `69_42` | walk sideways and turn (repeated) | - |  |
| `69_43` | walk sideways and turn (repeated) | - |  |
| `69_44` | walk sideways and turn (repeated) | - |  |
| `69_45` | walk sideways and turn (repeated) | - |  |
| `69_46` | walk sideways and turn (repeated) | - |  |
| `69_47` | walk sideways and turn (repeated) | - |  |
| `69_48` | walk sideways and turn (opposite direction) | - |  |
| `69_49` | walk sideways and turn (opposite direction) | - |  |
| `69_50` | walk sideways and backwards | - |  |
| `69_51` | walk backwards and turn | - |  |
| `69_52` | walk backwards and turn | - |  |
| `69_53` | walk backwards and turn | - |  |
| `69_54` | walk backwards and turn | - |  |
| `69_55` | walk backwards and turn | - |  |
| `69_56` | walk sideways and turn (opposite direction) | - |  |
| `69_57` | walk sideways and turn (opposite direction) | - |  |
| `69_58` | walk sideways and turn (opposite direction) | - |  |
| `69_59` | walk sideways and turn | - |  |
| `69_60` | walk sideways and turn | - |  |
| `69_61` | walk sideways and turn | - |  |
| `69_62` | walk sideways and turn (opposite direction) | - |  |
| `69_63` | walk sideways and turn (opposite direction) | - |  |
| `69_64` | walk sideways and turn (opposite direction) | - |  |
| `69_65` | walk sideways and turn | - |  |
| `69_66` | walk sideways and turn | - |  |
| `69_67` | walk sideways and turn | - |  |
| `69_68` | walk forward and pick up object, set down object | - |  |
| `69_69` | walk forward and pick up object, carry back object | - |  |
| `69_70` | walk up to object, squat, pick up object, set down in another place. | - |  |
| `69_71` | walk up to object, squat, pick up object, set down in another place | - |  |
| `69_72` | walk up to object, pick up object, set down in another place | - |  |
| `69_73` | walk up to object, lean over, pick up object, set down in another place | - |  |
| `69_74` | walk up to object, lean over, pick up object, set down in another place | - |  |
| `69_75` | walk up to object, squat, pick up object, set down in another place | - |  |

### 피험자 70

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `70_01` | carry 5.5lb suitcase | 6.0 |  |
| `70_02` | carry 5.5lb suitcase | 6.3 |  |
| `70_03` | carry 19.5lb suitcase | 15.4 |  |
| `70_04` | carry 19.5lb suitcase | 13.9 |  |
| `70_05` | carry 19.5lb suitcase | 7.5 |  |
| `70_06` | carry 19.5lb suitcase | 7.0 |  |
| `70_07` | carry 19.5lb suitcase | - |  |
| `70_08` | carry 19.5lb suitcase | 7.1 |  |
| `70_09` | carry 19.5lb suitcase | 7.0 |  |
| `70_10` | carry 12.5lb suitcase | 6.7 |  |
| `70_11` | carry 12.5lb suitcase | - |  |
| `70_12` | carry 12.5lb suitcase | - |  |
| `70_13` | carry 12.5lb suitcase | - |  |

### 피험자 73

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `73_01` | Unknown | 6.0 |  |
| `73_02` | Unknown | 6.3 |  |
| `73_03` | Unknown | 15.4 |  |
| `73_04` | Unknown | 13.9 |  |
| `73_05` | Unknown | 7.5 |  |
| `73_06` | Unknown | 7.0 |  |
| `73_07` | Unknown | - |  |
| `73_08` | Unknown | 7.1 |  |
| `73_09` | Unknown | 7.0 |  |
| `73_10` | Unknown | 6.7 |  |
| `73_11` | Unknown | - |  |
| `73_12` | Unknown | - |  |
| `73_13` | Unknown | - |  |

### 피험자 74

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `74_01` | stiff walk | 7.7 |  |
| `74_02` | stiff walk | 4.4 |  |
| `74_03` | kick | 6.6 |  |
| `74_04` | kick | 5.2 |  |
| `74_05` | kick | 5.4 |  |
| `74_06` | kick | 5.4 |  |
| `74_07` | lifting up | 5.2 |  |
| `74_08` | lifting up | 2.8 |  |
| `74_09` | Unknown | 1.7 |  |
| `74_10` | peeping | 5.6 |  |
| `74_11` | peeping | 5.8 |  |
| `74_12` | thinker | 5.0 |  |
| `74_13` | Range of motion | 42.1 |  |
| `74_14` | slope 1 | 7.5 |  |
| `74_15` | slope1 | 7.3 |  |
| `74_16` | slope 2 | 8.2 |  |
| `74_17` | slope 2 | 8.7 |  |
| `74_18` | slope 3 | 8.2 |  |
| `74_19` | slope 3 | 8.1 |  |
| `74_20` | stiff walk | 9.6 |  |

### 피험자 75

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `75_01` | run jump | 6.3 |  |
| `75_02` | run jump | 4.0 |  |
| `75_03` | run jump | 3.5 |  |
| `75_04` | wide leg run | 4.8 |  |
| `75_05` | cross leg run | 5.0 |  |
| `75_06` | 180 jump | 12.2 |  |
| `75_07` | angle jumps | 18.6 |  |
| `75_08` | 360 jumps | 18.6 |  |
| `75_09` | 360 jump | 6.2 |  |
| `75_10` | 2 jump | - |  |
| `75_11` | 2 jump | 2.9 |  |
| `75_12` | box jump | 7.7 |  |
| `75_13` | hopscotch | 6.2 |  |
| `75_14` | hopscotch | 7.4 |  |
| `75_15` | long jumps | 29.1 |  |
| `75_16` | jump kick | 5.7 |  |
| `75_17` | medium sit | 5.4 |  |
| `75_18` | high sit | 5.0 |  |
| `75_19` | medium sit | 12.8 |  |
| `75_20` | low sit | 8.3 |  |

### 피험자 76

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `76_01` | walk backwards then attack with a punch | 7.8 |  |
| `76_02` | walk backwards, feign a few attacks, then attack | 9.7 |  |
| `76_03` | avoid attacker | 9.0 |  |
| `76_04` | defensive guard pose | 3.5 |  |
| `76_05` | swatting at pesky bug | 7.2 |  |
| `76_06` | avoid stepping on something | 5.6 |  |
| `76_07` | Unknown | 0.2 |  |
| `76_08` | careful stepping over things | 12.5 |  |
| `76_09` | walking backwards | 13.2 |  |
| `76_10` | turning | 11.4 |  |
| `76_11` | quick large steps backwards | 4.3 |  |

### 피험자 77

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `77_01` | looking around | 18.2 |  |
| `77_02` | standing | 15.6 |  |
| `77_03` | ready stance | 16.4 |  |
| `77_04` | Looking around | 14.7 |  |
| `77_05` | look around with flashlight | 8.5 |  |
| `77_06` | searching ground | 22.5 |  |
| `77_07` | poking ground | 8.4 |  |
| `77_08` | investigating thing on ground with two hands | 16.8 |  |
| `77_09` | duck to avoid flying object | 16.5 |  |
| `77_10` | careful run | 11.5 |  |
| `77_11` | careful run | 5.3 |  |
| `77_12` | careful run in circle | 16.3 |  |
| `77_13` | careful run in figure eight | 23.1 |  |
| `77_14` | careful creeping | 16.5 |  |
| `77_15` | careful creeping | 18.0 |  |
| `77_16` | laying down, getting up, careful ready pose | 10.9 |  |
| `77_17` | laying down, getting up, careful ready pose | 12.0 |  |
| `77_18` | laying down on back, getting up, careful ready pose | 14.2 |  |
| `77_19` | limping, hurt right leg | 16.7 |  |
| `77_20` | limping, hurt right leg | 26.2 |  |
| `77_21` | stretching | 10.9 |  |
| `77_22` | limping, hurt right leg | 23.8 |  |
| `77_23` | limping, hurt right leg | 26.5 |  |
| `77_24` | limping, hurt right leg | 11.9 |  |
| `77_25` | careful walk and search | 11.1 |  |
| `77_26` | careful walk and search | 10.8 |  |
| `77_27` | careful walk and search | 12.1 |  |
| `77_28` | careful walk | 24.8 |  |
| `77_29` | creeping walk | 35.1 |  |
| `77_30` | creeping walk | 21.0 |  |
| `77_31` | silent walk | 35.1 |  |
| `77_32` | creeping walk | 31.6 |  |
| `77_33` | creeping with limp | 50.0 |  |
| `77_34` | creep and pause, repeat | 18.7 |  |

### 피험자 78

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `78_01` | LeftTightTurn         CleanedGRS | - |  |
| `78_02` | RightWideTurn            CleanedGRS | 2.3 |  |
| `78_03` | LeftWideTurn     CleanedGRS | 1.4 |  |
| `78_04` | SuperTightLeft        CleanedGRS | - |  |
| `78_05` | SuperTightRight         CleanedGRS | 1.4 |  |
| `78_06` | RunningStraight       CleanedGRS | 0.9 |  |
| `78_07` | RunningWideRight       CleanedGRS | 1.2 |  |
| `78_08` | RunningWideLeft      CleanedGRS | 0.9 |  |
| `78_09` | RunningTigherLeft      CleanedGRS | - |  |
| `78_10` | RunningTighterRight      CleanedGRS | 1.2 |  |
| `78_11` | calibration | 0.4 |  |
| `78_12` | RunningNoBall     CleanedGRS | 0.8 |  |
| `78_13` | OffensiveMoveSpinLeft            CleanedGRS | 1.4 |  |
| `78_14` | OffensiveMoveSpinLeft      CleanedGRS | 1.4 |  |
| `78_15` | OffensiveMoveGoRight     CleanedGRS | 1.3 |  |
| `78_16` | OffensiveMoveGoLeft         CleanedGRs | 1.6 |  |
| `78_17` | OffensiveMoveSpinRight             CleanedGRS | 1.5 |  |
| `78_18` | WalkEvasiveLeft      CleanedGRS | 1.8 |  |
| `78_19` | WalkEvasiveRight              CleanedGRS | 1.5 |  |
| `78_20` | FeintLeftMoveRight            CleanedGRS | 1.9 |  |
| `78_21` | FeintRightMoveLeft      CleanedGRS | 1.9 |  |
| `78_22` | FakeShotBreakRight     CleanedGRs | 5.0 |  |
| `78_23` | FakeShotBreakLeft            CleanedGRS | 4.3 |  |
| `78_24` | DefensiveStraightNoStop          CleanedGRS | 2.0 |  |
| `78_25` | DefensiveStraightWithStop          CleanedGRS | 3.0 |  |
| `78_26` | DefensiveRightStopToStop           CleanedGRS | 2.7 |  |
| `78_27` | DefensiveLeftStopToStop              CleanedGRS | 2.5 |  |
| `78_28` | DefensiveMoveZigZag           CleanedGRS | 3.7 |  |
| `78_29` | DefensiveMoveSideToSide           CleanedGRS | 1.4 |  |
| `78_30` | DefensiveMoveSideToSide           CleanedGRS | 5.9 |  |
| `78_31` | Pivoting     CleanedGRS | 6.7 |  |
| `78_32` | SraightDriveFromStop          Cleaned GRS | 1.8 |  |
| `78_33` | RightDrive (left then right)    Cleaned GRS | 1.9 |  |
| `78_34` | LeftDrive (right then left)    Cleaned GRS | 2.5 |  |
| `78_35` | RightTightTurn    CleanedGRS | 1.8 |  |

### 피험자 79

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `79_01` | chopping wood | 9.8 |  |
| `79_02` | swimming | 12.9 |  |
| `79_03` | swimming | 14.1 |  |
| `79_04` | digging | 15.2 |  |
| `79_05` | sewing | 16.3 |  |
| `79_06` | hand shake | 9.8 |  |
| `79_07` | lost marker | 5.5 |  |
| `79_08` | boxing | 7.4 |  |
| `79_09` | slicing bread | 14.0 |  |
| `79_10` | chopping onions | 11.7 |  |
| `79_11` | Subject calibration | 2.2 |  |
| `79_12` | eating dinner | 17.1 |  |
| `79_13` | mixing batter | 11.1 |  |
| `79_14` | making dough | 12.2 |  |
| `79_15` | eating a sandwich | 14.6 |  |
| `79_16` | buying something | 12.0 |  |
| `79_17` | playing violin | 13.4 |  |
| `79_18` | playing drums | 13.4 |  |
| `79_19` | playing piano | 11.5 |  |
| `79_20` | hanging a picture | 12.4 |  |
| `79_21` | putting on a pull over | 13.6 |  |
| `79_22` | range of motion | 14.7 |  |
| `79_23` | putting on a jacket | 12.2 |  |
| `79_24` | putting on button up sweater | 12.4 |  |
| `79_25` | moving heavy box | 10.1 |  |
| `79_26` | planting a tree | 17.2 |  |
| `79_27` | planting a plant | 14.7 |  |
| `79_28` | putting on a ball cap | 6.8 |  |
| `79_29` | putting on a dress | 11.3 |  |
| `79_30` | pushing a swing | 13.3 |  |
| `79_31` | writing on a chalkboard | 9.6 |  |
| `79_32` | writing on a chalkboard | 16.1 |  |
| `79_33` | chug a beer | 9.7 |  |
| `79_34` | fishing | 12.5 |  |
| `79_35` | fishing | 19.9 |  |
| `79_36` | answering the phone | 8.6 |  |
| `79_37` | dialing phone | 10.0 |  |
| `79_38` | drinking water | 9.0 |  |
| `79_39` | sipping martinee | 13.5 |  |
| `79_40` | drinking a soda | 14.4 |  |
| `79_41` | sipping coffee | 18.5 |  |
| `79_42` | eating soup | 13.2 |  |
| `79_43` | painting | 16.4 |  |
| `79_44` | washing a window | 14.2 |  |
| `79_45` | bear | 14.4 |  |
| `79_46` | bear | 21.6 |  |
| `79_47` | chicken | 20.6 |  |
| `79_48` | elephant | 21.0 |  |
| `79_49` | monkey | 17.3 |  |
| `79_50` | mouse | 12.2 |  |
| `79_51` | chipmunk | 14.2 |  |
| `79_52` | prairie dog | 15.0 |  |
| `79_53` | dog | 12.4 |  |
| `79_54` | snake | 19.4 |  |
| `79_55` | sweeping | 10.7 |  |
| `79_56` | T-rex | 14.3 |  |
| `79_57` | fish | 16.1 |  |
| `79_58` | bird | 14.2 |  |
| `79_59` | cat | 14.2 |  |
| `79_60` | chicken | 13.3 |  |
| `79_61` | cow | 18.2 |  |
| `79_62` | chicken | 14.1 |  |
| `79_63` | tiger | 18.2 |  |
| `79_64` | penguin | 18.0 |  |
| `79_65` | horse | 10.9 |  |
| `79_66` | movie and trial dont match | 12.1 |  |
| `79_67` | no movie | 21.0 |  |
| `79_68` | cold | 19.7 |  |
| `79_69` | very happy | 13.6 |  |
| `79_70` | laughing | 12.7 |  |
| `79_71` | sad | 18.0 |  |
| `79_72` | crying | 15.9 |  |
| `79_73` | scared | 14.8 |  |
| `79_74` | upset | 15.4 |  |
| `79_75` | channel surfing | 21.5 |  |
| `79_76` | driving | 20.9 |  |
| `79_77` | vacuuming | 19.1 |  |
| `79_78` | taking a movie | 21.5 |  |
| `79_79` | putting on headphones | 14.0 |  |
| `79_80` | using a palm pilot | 16.4 |  |
| `79_81` | brushing teeth | 15.7 |  |
| `79_82` | putting on deoderant | 12.8 |  |
| `79_83` | shaving | 19.5 |  |
| `79_84` | combing hair | 14.6 |  |
| `79_85` | typing on a laptop | 17.5 |  |
| `79_86` | shooting bow and arrow | 11.3 |  |
| `79_87` | raking | 13.2 |  |
| `79_88` | swatting at a fly | 15.1 |  |
| `79_89` | holding a baby | 14.8 |  |
| `79_90` | washing | 22.6 |  |
| `79_91` | football | 8.3 |  |
| `79_92` | frisbee | 10.6 |  |
| `79_93` | weight lifting | 19.0 |  |
| `79_94` | flexing | 15.6 |  |
| `79_95` | rowing | 15.8 |  |
| `79_96` | shooting a gun | 9.3 |  |

### 피험자 80

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `80_01` | shaking hands | 14.2 |  |
| `80_02` | chopping onions | 11.7 |  |
| `80_03` | shooting a gun | 11.0 |  |
| `80_04` | sewing | 18.4 |  |
| `80_05` | digging a hole | 19.3 |  |
| `80_06` | paying for something | 16.0 |  |
| `80_07` | hanging picture | 26.0 |  |
| `80_08` | picking up something | 14.7 |  |
| `80_09` | planting a flower | 25.3 |  |
| `80_10` | boxing | 12.9 |  |
| `80_11` | putting on a sweater | 11.7 |  |
| `80_12` | fishing | 26.9 |  |
| `80_13` | drumming | 16.9 |  |
| `80_14` | teaching | 28.9 |  |
| `80_15` | putting on a coat | 20.6 |  |
| `80_16` | mixing batter | 21.0 |  |
| `80_17` | hand mixing dough | 24.0 |  |
| `80_18` | vacuuming | 25.2 |  |
| `80_19` | pushing broom | 30.4 |  |
| `80_20` | planting | 33.7 |  |
| `80_21` | pushing swing | 23.3 |  |
| `80_22` | putting on a hat | 17.6 |  |
| `80_23` | putting on a skirt | 17.0 |  |
| `80_24` | eating | 29.7 |  |
| `80_25` | answering a phone | 18.4 |  |
| `80_26` | dialing phone | 20.6 |  |
| `80_27` | setting glass of water | 18.1 |  |
| `80_28` | drinking and smoking | 20.4 |  |
| `80_29` | chugging | 18.8 |  |
| `80_30` | range of motion | 43.2 |  |
| `80_31` | making coffee | 26.0 |  |
| `80_32` | slicing | 26.9 |  |
| `80_33` | eating soup | 32.3 |  |
| `80_34` | rake leaves | 34.8 |  |
| `80_35` | putting on headphones | 32.4 |  |
| `80_36` | violin | 28.1 |  |
| `80_37` | TV | 44.9 |  |
| `80_38` | driving | 41.1 |  |
| `80_39` | Unknown | 30.4 |  |
| `80_40` | drinking from bottle | 15.2 |  |
| `80_41` | freezing | 17.8 |  |
| `80_42` | freezing | 20.6 |  |
| `80_43` | happy | 16.3 |  |
| `80_44` | laughing | 15.5 |  |
| `80_45` | crying | 26.8 |  |
| `80_46` | crying | 26.5 |  |
| `80_47` | Unknown | 16.7 |  |
| `80_48` | arguing | 19.2 |  |
| `80_49` | gorilla | 31.1 |  |
| `80_50` | cleaning window | 20.9 |  |
| `80_51` | chicken | 25.0 |  |
| `80_52` | dog | 26.2 |  |
| `80_53` | elephant | 30.1 |  |
| `80_54` | monkey | 27.1 |  |
| `80_55` | mouse | 22.9 |  |
| `80_56` | chip monk | 11.5 |  |
| `80_57` | prairie dog | 27.0 |  |
| `80_58` | snake | 39.2 |  |
| `80_59` | panther | 25.6 |  |
| `80_60` | Unknown | 34.3 |  |
| `80_61` | sweeping | 17.6 |  |
| `80_62` | bird | 38.1 |  |
| `80_63` | chicken | 37.9 |  |
| `80_64` | cat | 40.6 |  |
| `80_65` | fish | 30.3 |  |
| `80_66` | Unknown | 34.5 |  |
| `80_67` | Unknown | 35.9 |  |
| `80_68` | Unknown | 46.2 |  |
| `80_69` | painting | 71.3 |  |
| `80_70` | piano | 30.0 |  |
| `80_71` | chopping wood | 18.1 |  |
| `80_72` | swimming | 18.1 |  |
| `80_73` | shaking hands | 13.2 |  |

### 피험자 81

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `81_01` | fix hair and walk forward | - |  |
| `81_02` | walk forward | - |  |
| `81_03` | walk | - |  |
| `81_04` | walk at a brisk pace | - |  |
| `81_05` | push heavy object | - |  |
| `81_06` | push heavy box | - |  |
| `81_07` | pull heavy object | - |  |
| `81_08` | drag heavy object | - |  |
| `81_09` | drag heavy object | - |  |
| `81_10` | push object that is high in air | - |  |
| `81_11` | push object that is high in air | - |  |
| `81_12` | jump backwards off ledge | - |  |
| `81_13` | jump backwards off ledge | - |  |
| `81_14` | climb backwards off ledge | - |  |
| `81_15` | climb backwards off ledge | - |  |
| `81_16` | Unknown | - |  |
| `81_17` | walk forward | - |  |
| `81_18` | adjust hair walk forward | - |  |

### 피험자 82

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `82_01` | Static pose | 0.1 |  |
| `82_02` | Jump off ledge | 15.1 |  |
| `82_03` | Jump off ledge | 15.8 |  |
| `82_04` | Jump off ledge | 7.6 |  |
| `82_05` | sitting on ground relaxing | 18.7 |  |
| `82_06` | Pushing on heavy object | 9.1 |  |
| `82_07` | Pushing on heavy object | 10.0 |  |
| `82_08` | stand still; casual walk forward | 14.2 |  |
| `82_09` | confident walk forward | 10.8 |  |
| `82_10` | sad walk forward | 4.7 |  |
| `82_11` | normal walk forward | 5.8 |  |
| `82_12` | happy or fast walk forward | 3.4 |  |
| `82_13` | normal walk forward | 3.4 |  |
| `82_14` | walk forward and slow down | 7.6 |  |
| `82_15` | walk forward and turn sideways | 6.0 |  |
| `82_16` | bang on high object | 11.1 |  |
| `82_17` | bang on high object | 13.2 |  |
| `82_18` | static pose | 0.1 |  |

### 피험자 83

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `83_01` | large sidestep to right | 5.3 |  |
| `83_02` | sidestep to the right and up a ledge | 3.0 |  |
| `83_03` | large step to a short ledge | 5.6 |  |
| `83_04` | large sidestep to right | 3.9 |  |
| `83_05` | very large sidestep to right | 4.0 |  |
| `83_06` | very large sidestep to right and down | 3.3 |  |
| `83_07` | short sidestep to right and down | 3.5 |  |
| `83_08` | medium step forward and down | 3.9 |  |
| `83_09` | short step forward and down | 3.8 |  |
| `83_10` | medium step forward and down | 4.0 |  |
| `83_11` | static pose | 0.8 |  |
| `83_12` | medium sidestep to right and down | 4.2 |  |
| `83_13` | large sidestep to right | 4.2 |  |
| `83_14` | short sidestep to left and down | 3.6 |  |
| `83_15` | short step forward | 4.3 |  |
| `83_16` | medium sidestep to left and down | 4.2 |  |
| `83_17` | medium step to left and down | 4.4 |  |
| `83_18` | short step to left and forward | 3.9 |  |
| `83_19` | medium sidestep to left | 4.2 |  |
| `83_20` | medium step forward | 4.4 |  |
| `83_21` | large step to left and forward | 4.3 |  |
| `83_22` | stretching | 44.8 |  |
| `83_23` | short sidestep to left and up | 4.5 |  |
| `83_24` | medium step to left and up | 4.4 |  |
| `83_25` | short step forward and up | 4.5 |  |
| `83_26` | medium step to left, forward, and up | 4.3 |  |
| `83_27` | walk forward stepping up stairs | 8.2 |  |
| `83_28` | walk forward stepping up stairs | 7.8 |  |
| `83_29` | walk forward stepping up stairs | 7.9 |  |
| `83_30` | walk forward stepping up stairs | 8.4 |  |
| `83_31` | walk forward stepping up stairs | 7.8 |  |
| `83_32` | walk forward stepping up stairs | 8.7 |  |
| `83_33` | sidestep to right then back to left | 10.8 |  |
| `83_34` | walk forward and up stairs | 8.1 |  |
| `83_35` | walk forward and stepping up stairs | 8.7 |  |
| `83_36` | walk forward turn 90 degrees left walk forward | 8.8 |  |
| `83_37` | walk forward turn 90 degrees right walk forward | 8.0 |  |
| `83_38` | walk forward turn 90 degrees left walk forward | 8.4 |  |
| `83_39` | walk forward turn 90 degrees right walk forward | 8.1 |  |
| `83_40` | hop forward | 4.4 |  |
| `83_41` | hop forward | 3.9 |  |
| `83_42` | long jump forward | 4.5 |  |
| `83_43` | long jump forward | 5.0 |  |
| `83_44` | medium step forward | 5.5 |  |
| `83_45` | hop forward | 4.1 |  |
| `83_46` | medium hop forward | 4.2 |  |
| `83_47` | long jump forward | 5.2 |  |
| `83_48` | short hop forward | 3.7 |  |
| `83_49` | medium hop forward | 3.8 |  |
| `83_50` | long jump forward | 4.4 |  |
| `83_51` | hop turn 90 degrees left in air | 4.9 |  |
| `83_52` | hop turn 90 degrees left in air | 4.2 |  |
| `83_53` | hop turn 90 degrees left in air | 4.5 |  |
| `83_54` | hop turn 180 degrees left in air | 3.5 |  |
| `83_55` | medium sidestep to right | 6.1 |  |
| `83_56` | hop turn left 180 degrees in air | 4.2 |  |
| `83_57` | hop turn left 180 degrees in air | 3.4 |  |
| `83_58` | hop turn left 270 degrees in air | 3.0 |  |
| `83_59` | hop turn left 270 degrees in air | 5.0 |  |
| `83_60` | hop turn left 270 degrees in air | 3.4 |  |
| `83_61` | hop turn 360 degrees left in air | 4.2 |  |
| `83_62` | hop turn left 360 degrees in air | 4.0 |  |
| `83_63` | large sidestep to right and forward | 5.7 |  |
| `83_64` | hop and turn right 360 degrees in air | 4.8 |  |
| `83_65` | hop and turn right 360 degrees in air | 3.3 |  |
| `83_66` | short sidestep to right | 5.6 |  |
| `83_67` | short sidestep to the right | 5.6 |  |
| `83_68` | medium sidestep to right | 5.5 |  |

### 피험자 84

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `84_01` | Unknown | 7.7 |  |
| `84_02` | Unknown | 4.4 |  |
| `84_03` | Unknown | 6.6 |  |
| `84_04` | Unknown | 5.2 |  |
| `84_05` | Unknown | 5.4 |  |
| `84_06` | Unknown | 5.4 |  |
| `84_07` | Unknown | 5.2 |  |
| `84_08` | Unknown | 2.8 |  |
| `84_09` | Unknown | 1.7 |  |
| `84_10` | Unknown | 5.6 |  |
| `84_11` | Unknown | 5.8 |  |
| `84_12` | Unknown | 5.0 |  |
| `84_13` | Unknown | 42.1 |  |
| `84_14` | Unknown | 7.5 |  |
| `84_15` | Unknown | 7.3 |  |
| `84_16` | Unknown | 8.2 |  |
| `84_17` | Unknown | 8.7 |  |
| `84_18` | Unknown | 8.2 |  |
| `84_19` | Unknown | 8.1 |  |
| `84_20` | Unknown | 9.6 |  |

### 피험자 85

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `85_01` | JumpTwist | 8.3 |  |
| `85_02` | JumpTwist | 6.8 |  |
| `85_03` | UpRightSequence | 27.0 |  |
| `85_04` | FancyFootWork | 21.3 |  |
| `85_05` | HandStandKicks | 13.6 |  |
| `85_06` | KickFlip | 7.9 |  |
| `85_07` | KickFlipStumble | 8.0 |  |
| `85_08` | Helicopter | 8.5 |  |
| `85_09` | motorcycle pose | 2.1 |  |
| `85_10` | EndofBreakDance | 6.5 |  |
| `85_11` | UpRightSequence | 15.0 |  |
| `85_12` | LongSequenceGood | 37.5 |  |
| `85_13` | BadStartSequnce | 12.1 |  |
| `85_14` | BreakSequencewithFlips | 24.7 |  |
| `85_15` | 90TwistsFall | - |  |

### 피험자 86

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `86_01` | jumps kicks and punches | 38.2 |  |
| `86_02` | walk, squats, run, stretch, jumps, punches, and drinking | 88.5 |  |
| `86_03` | walking, running, jumping, kicking, and stretching | 70.0 |  |
| `86_04` | walking, stretching, punching, chopping, and drinking | 84.0 |  |
| `86_05` | walking, jumping, jumping jacks,  jumping on one foot, punching, chopping, | 69.5 |  |
| `86_06` | walking, running, kicking, punching, knee kicking, and stretching | 82.8 |  |
| `86_07` | walking, swinging arms, stretching, jumping on one leg, and jumping | 72.5 |  |
| `86_08` | walking, squats, stretching, kicking, and punching | 76.7 |  |
| `86_09` | walking, sitting, looking, stand up | 40.0 |  |
| `86_10` | walk around, sit, stand up, and running | 63.2 |  |
| `86_11` | walking, stretching, walking and turning | 47.3 |  |
| `86_12` | walking, dragging, sweeping, dustpan, wipe window, and wipe mirror | 73.8 |  |
| `86_13` | walking around, walk up ladder, step down ladder | 51.8 |  |
| `86_14` | bouncing basketball, shooting basketball, dribble basketball, two handed dribble | 54.5 |  |
| `86_15` | walking, sitting, hand motions | 59.1 |  |

### 피험자 87

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `87_01` | Jump with kick and spin | 5.1 |  |
| `87_02` | T-Pose | - |  |
| `87_03` | Backflip | - |  |
| `87_04` | backflip | - |  |
| `87_05` | cartwheels | - |  |

### 피험자 88

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `88_01` | backflip | - |  |
| `88_02` | backflips, jump onto platform, handstands, vertical pushups | - |  |
| `88_03` | motorcycle pose | 3.0 |  |
| `88_04` | stretches, cartwheels, flips, spin kicks, spins, and fall | - |  |
| `88_05` | cartwheel into backflip | 2.5 |  |
| `88_06` | jump and spin kick | 3.8 |  |
| `88_07` | cartwheel | 2.6 |  |
| `88_08` | crouch and flip backward on hands | 4.8 |  |
| `88_09` | stretch and cartwheel | 6.3 |  |
| `88_10` | stretch and spin | 7.8 |  |
| `88_11` | stretches and jumps | 33.8 |  |

### 피험자 89

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `89_01` | balance object on forehead | 38.9 |  |
| `89_02` | motorcycle pose | 3.0 |  |
| `89_03` | flip and stand on one hand | - |  |
| `89_04` | spins, flips, stand on one hand | - |  |
| `89_05` | spin upside down, handstand, flips | - |  |
| `89_06` | balance beam | - |  |

### 피험자 90

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `90_01` | bkwd summersult | 6.6 |  |
| `90_02` | cartwheel | 6.5 |  |
| `90_03` | cartwheel | 7.4 |  |
| `90_04` | cartwheel | 5.8 |  |
| `90_05` | jump kick | 4.3 |  |
| `90_06` | jump kick | 5.2 |  |
| `90_07` | jump kick | 7.5 |  |
| `90_08` | side flip | 5.6 |  |
| `90_09` | Flip forward onto hands and back again | - |  |
| `90_10` | 90_10.amc | - |  |
| `90_11` | hand spring | 3.0 |  |
| `90_12` | bck flp twst fall | 6.9 |  |
| `90_13` | bck flp twst fall | 7.7 |  |
| `90_14` | front hand flip | 7.0 |  |
| `90_15` | front hand flip | 9.9 |  |
| `90_16` | fall on face | 6.0 |  |
| `90_17` | BannanaPeelSlip | - |  |
| `90_18` | RugPullFall | 3.3 |  |
| `90_19` | monkey backflip | 8.7 |  |
| `90_20` | monkey sequence | - |  |
| `90_21` | monkey sequence | - |  |
| `90_22` | straight walk | 5.8 |  |
| `90_23` | straight walk | 9.9 |  |
| `90_24` | ball mount | 6.5 |  |
| `90_25` | fwd ball walk | 10.6 |  |
| `90_26` | fwd ball walk | 11.9 |  |
| `90_27` | bwk ball walk | 10.2 |  |
| `90_28` | breakdance | 6.4 |  |
| `90_29` | sequesnce | 12.3 |  |
| `90_30` | russian dance | 11.9 |  |
| `90_31` | russian dance | 8.2 |  |
| `90_32` | moonwalk | 6.0 |  |
| `90_33` | arm up wide leg roll | 7.5 |  |
| `90_34` | wide leg roll | 7.0 |  |
| `90_35` | wide leg roll | 5.8 |  |
| `90_36` | wide leg roll | 5.5 |  |

### 피험자 91

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `91_01` | Walk digital figure eight | 22.8 |  |
| `91_02` | WalkStraight | 14.6 |  |
| `91_03` | Walk figure eight | 15.5 |  |
| `91_04` | Walking | 18.0 |  |
| `91_05` | Mummy Walk | 22.5 |  |
| `91_06` | Motorcycle Pose | 1.1 |  |
| `91_07` | mummy8 | 21.5 |  |
| `91_08` | mummyDigital8 | 33.1 |  |
| `91_09` | DrunkWalk | 45.0 |  |
| `91_10` | SlowWalk | 26.5 |  |
| `91_11` | LavishWalk | 15.5 |  |
| `91_12` | TooCoolWalk | 18.5 |  |
| `91_13` | SadWalk | 24.7 |  |
| `91_14` | DepressedWalk | 23.1 |  |
| `91_15` | ClumsyWalk | 25.8 |  |
| `91_16` | Limp | 15.8 |  |
| `91_17` | QuickWalk | 12.7 |  |
| `91_18` | CarefulWalk LookingAround | 28.0 |  |
| `91_19` | March | 15.7 |  |
| `91_20` | ShyWalk | 23.1 |  |
| `91_21` | acheyWalk | 32.2 |  |
| `91_22` | CasualQuickWalk | 17.6 |  |
| `91_23` | CoolWalk | 22.2 |  |
| `91_24` | HurtLegWalk | 31.7 |  |
| `91_25` | DragBadLegWalk | 26.1 |  |
| `91_26` | HurtStomachWalk | 17.4 |  |
| `91_27` | SlowWalk | 24.1 |  |
| `91_28` | GhettoWalk | 27.6 |  |
| `91_29` | NormalWalk | 18.2 |  |
| `91_30` | SexyWalk | 26.2 |  |
| `91_31` | NormalWalk | 16.6 |  |
| `91_32` | ScaredWalk | 31.0 |  |
| `91_33` | MachoWalk | 22.5 |  |
| `91_34` | NormalWalk | 18.4 |  |
| `91_35` | TrafficWalk | 25.4 |  |
| `91_36` | WalkStraight | 7.4 |  |
| `91_37` | Forward | 2.6 |  |
| `91_38` | SmallForward | 3.8 |  |
| `91_39` | JumpForward | 3.7 |  |
| `91_40` | JumpForward | 3.9 |  |
| `91_41` | JumpForward | 4.2 |  |
| `91_42` | JumpForward | 4.7 |  |
| `91_43` | JumpSmallForward | 1.9 |  |
| `91_44` | JumpSmallForward | 2.8 |  |
| `91_45` | JumpForward | 3.1 |  |
| `91_46` | Jump Turn | 2.7 |  |
| `91_47` | Jump Turn | 3.9 |  |
| `91_48` | JumpTurn | 3.7 |  |
| `91_49` | Jump Turn | - |  |
| `91_50` | JumpTurn | 5.5 |  |
| `91_51` | FurtherJumpTurn | 4.0 |  |
| `91_52` | SmallJumpTurn | 4.2 |  |
| `91_53` | 180 degree jump | 4.6 |  |
| `91_54` | 180 | 5.7 |  |
| `91_55` | 180 | 3.9 |  |
| `91_56` | 90 | 4.2 |  |
| `91_57` | WalkForward | 9.8 |  |
| `91_58` | 270 | 4.1 |  |
| `91_59` | 360 smallStumble | 2.6 |  |
| `91_60` | 360 | 3.1 |  |
| `91_61` | 360 | 3.0 |  |
| `91_62` | walkFigure8 | 15.4 |  |

### 피험자 93

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `93_01` | Motorcycle Pose | 0.3 |  |
| `93_02` | rangeOfMotion | 24.9 |  |
| `93_03` | charleston_01 | 7.4 |  |
| `93_04` | charleston_side_by_side_female | 8.4 |  |
| `93_05` | charleston_side_by_side_male | 9.1 |  |
| `93_06` | lindyHop2 | 6.7 |  |
| `93_07` | Casual Walk | 3.9 |  |
| `93_08` | xtra fancY charleston | 9.3 |  |

### 피험자 94

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `94_01` | Unknown | 30.0 |  |
| `94_02` | Unknown | - |  |
| `94_03` | Unknown | 31.1 |  |
| `94_04` | Unknown | 26.2 |  |
| `94_05` | Unknown | 43.9 |  |
| `94_06` | Unknown | 20.9 |  |
| `94_07` | Unknown | 19.3 |  |
| `94_08` | Unknown | 22.9 |  |
| `94_09` | Unknown | 33.1 |  |
| `94_10` | Unknown | - |  |
| `94_11` | Unknown | - |  |
| `94_12` | Unknown | 37.5 |  |
| `94_13` | Unknown | 16.6 |  |
| `94_14` | Unknown | - |  |
| `94_15` | Unknown | 18.4 |  |
| `94_16` | Unknown | 16.9 |  |

### 피험자 102

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `102_01` | RightWideTurn | 2.3 |  |
| `102_02` | LeftWideTurn | 1.4 |  |
| `102_03` | SuperTightLeft | - |  |
| `102_04` | SuperTightRight | 1.4 |  |
| `102_05` | RunningStraight | 0.9 |  |
| `102_06` | RunningWideRight | 1.2 |  |
| `102_07` | RunningWideLeft | 0.9 |  |
| `102_08` | RunningTighterRight | 1.2 |  |
| `102_09` | calibration | 0.4 |  |
| `102_10` | RunningNoBall | 0.8 |  |
| `102_11` | OffensiveMoveSpinLeft | 1.4 |  |
| `102_12` | OffensiveMoveSpinLeft | 1.4 |  |
| `102_13` | OffensiveMoveGoRight | 1.3 |  |
| `102_14` | OffensiveMoveGoLeft | 1.6 |  |
| `102_15` | OffensiveMoveSpinRight | - |  |
| `102_16` | WalkEvasiveLeft | 1.8 |  |
| `102_17` | WalkEvasiveRight | 1.5 |  |
| `102_18` | FeintLeftMoveRight | 1.9 |  |
| `102_19` | FeintRightMoveLeft | 1.9 |  |
| `102_20` | FakeShotBreakRight | 5.0 |  |
| `102_21` | FakeShotBreakLeft | 4.3 |  |
| `102_22` | DefensiveStraightNoStop | 2.0 |  |
| `102_23` | DefensiveStraightWithStop | 3.0 |  |
| `102_24` | DefensiveRightStopToStop | 2.7 |  |
| `102_25` | DefensiveLeftStopToStop | 2.5 |  |
| `102_26` | DefensiveMoveZigZag | 3.7 |  |
| `102_27` | DefensiveMoveSideToSide | 1.4 |  |
| `102_28` | DefensiveMoveSideToSide | 5.9 |  |
| `102_29` | Pivoting | 6.7 |  |
| `102_30` | SraightDriveFromStop | 1.8 |  |
| `102_31` | RightDrive (left then right) | 1.9 |  |
| `102_32` | LeftDrive (right then left) | 2.5 |  |
| `102_33` | RightTightTurn | 1.8 |  |

### 피험자 103

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `103_01` | Unknown | 0.3 |  |
| `103_02` | rangeOfMotion_01 | 24.9 |  |
| `103_03` | charleston_01 | 7.4 |  |
| `103_04` | charleston_side_by_side_female | 8.4 |  |
| `103_05` | charleston_side_by_side_male | 9.1 |  |
| `103_06` | lindyHop2 | 6.7 |  |
| `103_07` | Casual Walk | 3.9 |  |
| `103_08` | xtra fancY charleston | 9.3 |  |

### 피험자 104

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `104_01` | JogThrough | - |  |
| `104_02` | neutral Male walk, exact footfalls | - |  |
| `104_03` | Frankenstein male walk, exact footfalls | - |  |
| `104_04` | JogThrough | - |  |
| `104_05` | Unknown | - |  |
| `104_06` | StartJog | - |  |
| `104_07` | Unknown | - |  |
| `104_08` | StartJog | - |  |
| `104_09` | JogStop | - |  |
| `104_10` | JogStop | - |  |
| `104_11` | HappyGoLuckWalk | - |  |
| `104_12` | ExcitedWalk | - |  |
| `104_13` | StumbleWalk | - |  |
| `104_14` | HappyStartWalk | - |  |
| `104_15` | Unknown | - |  |
| `104_16` | SpasticWalk | - |  |
| `104_17` | SpasticStop | - |  |
| `104_18` | SpasticStop | - |  |
| `104_19` | CasualWalk | - |  |
| `104_20` | Unknown | - |  |
| `104_21` | Unknown | - |  |
| `104_22` | RegularWalk8 | - |  |
| `104_23` | Unknown | - |  |
| `104_24` | Unknown | - |  |
| `104_25` | Unknown | - |  |
| `104_26` | Unknown | - |  |
| `104_27` | RegularWalkRightAngleTurns | - |  |
| `104_28` | SternWalk | - |  |
| `104_29` | SternWalk | - |  |
| `104_30` | SternWalk8 | - |  |
| `104_31` | Unknown | - |  |
| `104_32` | SternWalkRightAngleTurns | - |  |
| `104_33` | Unknown | - |  |
| `104_34` | Unknown | - |  |
| `104_35` | SlowWalk | - |  |
| `104_36` | SlowWalk8 | - |  |
| `104_37` | RunThrough | - |  |
| `104_38` | Unknown | - |  |
| `104_39` | SlowWalkRightAngleTurns | - |  |
| `104_40` | Unknown | - |  |
| `104_41` | ZombieWalk | - |  |
| `104_42` | ZombieWalk8 | - |  |
| `104_43` | ZombieWalkRightAngleTurns | - |  |
| `104_44` | AttitudeWalk | - |  |
| `104_45` | AttitudeWalk8 | - |  |
| `104_46` | AttitudeWalkRightAngleTurns | - |  |
| `104_47` | Unknown | - |  |
| `104_48` | RunThrough | - |  |
| `104_49` | Unknown | - |  |
| `104_50` | Unknown | - |  |
| `104_51` | Unknown | - |  |
| `104_52` | Unknown | - |  |
| `104_53` | StartRun | - |  |
| `104_54` | StartRun | - |  |
| `104_55` | StartRun | - |  |
| `104_56` | RunStop | - |  |
| `104_57` | RunStop | - |  |

### 피험자 105

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `105_01` | WalkDigital8 | 22.8 |  |
| `105_02` | WalkStraight | 14.6 |  |
| `105_03` | Walk8 | 15.5 |  |
| `105_04` | Digital8 | 18.0 |  |
| `105_05` | mummyWalk | 22.5 |  |
| `105_06` | MotorCyclePose | 1.1 |  |
| `105_07` | mummy8 | 21.5 |  |
| `105_08` | mummyDigital8 | 33.1 |  |
| `105_09` | DrunkWalk | 45.0 |  |
| `105_10` | SlowWalk | 26.5 |  |
| `105_11` | LavishWalk | 15.5 |  |
| `105_12` | TooCoolWalk | 18.5 |  |
| `105_13` | SadWalk | 24.7 |  |
| `105_14` | DepressedWalk | 23.1 |  |
| `105_15` | ClumsyWalk | 25.8 |  |
| `105_16` | Limp | 15.8 |  |
| `105_17` | QuickWalk | 12.7 |  |
| `105_18` | CarefulWalk LookingAround | 28.0 |  |
| `105_19` | March | 15.7 |  |
| `105_20` | ShyWalk | 23.1 |  |
| `105_21` | acheyWalk | 32.2 |  |
| `105_22` | CasualQuickWalk | 17.6 |  |
| `105_23` | CoolWalk | 22.2 |  |
| `105_24` | HurtLegWalk | 31.7 |  |
| `105_25` | DragBadLegWalk | 26.1 |  |
| `105_26` | HurtStomachWalk | 17.4 |  |
| `105_27` | SlowWalk | 24.1 |  |
| `105_28` | GhettoWalk | 27.6 |  |
| `105_29` | NormalWalk | 18.2 |  |
| `105_30` | SexyWalk | 26.2 |  |
| `105_31` | NormalWalk | 16.6 |  |
| `105_32` | ScaredWalk | - |  |
| `105_33` | MachoWalk | 22.5 |  |
| `105_34` | NormalWalk | 18.4 |  |
| `105_35` | TrafficWalk | 25.4 |  |
| `105_36` | WalkStraight | 7.4 |  |
| `105_37` | Forward | 2.6 |  |
| `105_38` | SmallForward | 3.8 |  |
| `105_39` | JumpForward | 3.7 |  |
| `105_40` | JumpForward | 3.9 |  |
| `105_41` | JumpForward | 4.2 |  |
| `105_42` | JumpForward | 4.7 |  |
| `105_43` | JumpSmallForward | 1.9 |  |
| `105_44` | JumpSmallForward | 2.8 |  |
| `105_45` | JumpForward | 3.1 |  |
| `105_46` | Jump Turn | 2.7 |  |
| `105_47` | Jump Turn | 3.9 |  |
| `105_48` | JumpTurn | 3.7 |  |
| `105_49` | Jump Turn | - |  |
| `105_50` | JumpTurn | 5.5 |  |
| `105_51` | FurtherJumpTurn | 4.0 |  |
| `105_52` | SmallJumpTurn | 4.2 |  |
| `105_53` | 180 | 4.6 |  |
| `105_54` | 180 | 5.7 |  |
| `105_55` | 180 | 3.9 |  |
| `105_56` | 90 | 4.2 |  |
| `105_57` | WalkForward | 9.8 |  |
| `105_58` | 270 | 4.1 |  |
| `105_59` | 360 smallStumble | 2.6 |  |
| `105_60` | 360 | 3.1 |  |
| `105_61` | 360 | 3.0 |  |
| `105_62` | walkFigure8 | 15.4 |  |

### 피험자 106

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `106_01` | clean | 1.2 |  |
| `106_02` | clean | 1.9 |  |
| `106_03` | clean | 3.8 |  |
| `106_04` | clean | 9.1 |  |
| `106_05` | clean | 3.8 |  |
| `106_06` | clean | 10.8 |  |
| `106_07` | clean | 5.0 |  |
| `106_08` | clean | 5.5 |  |
| `106_09` | clean | 3.9 |  |
| `106_10` | clean | 8.4 |  |
| `106_11` | clean | 11.4 |  |
| `106_12` | clean | 9.5 |  |
| `106_13` | clean | 6.1 |  |
| `106_14` | clean | 9.6 |  |
| `106_15` | 106_15.amc | 19.4 |  |
| `106_16` | clean | 5.0 |  |
| `106_17` | clean | 9.3 |  |
| `106_18` | clean | 6.5 |  |
| `106_19` | clean | 19.9 |  |
| `106_20` | clean | 12.7 |  |
| `106_21` | bad AMC | 4.5 |  |
| `106_22` | clean | 3.3 |  |
| `106_23` | clean | 4.3 |  |
| `106_24` | clean | 4.3 |  |
| `106_25` | clean | 10.2 |  |
| `106_26` | clean | 6.6 |  |
| `106_27` | clean | 9.2 |  |
| `106_28` | clean | 5.9 |  |
| `106_29` | clean | 19.4 |  |
| `106_30` | clean | 12.0 |  |
| `106_31` | clean | 11.2 |  |
| `106_32` | clean | 14.8 |  |
| `106_33` | clean | 17.6 |  |
| `106_34` | clean | 5.2 |  |

### 피험자 107

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `107_01` | Unknown | 8.8 |  |
| `107_02` | Unknown | 11.5 |  |
| `107_03` | Unknown | 8.6 |  |
| `107_04` | Unknown | 7.3 |  |
| `107_05` | Unknown | 7.2 |  |
| `107_06` | Unknown | 6.2 |  |
| `107_07` | Unknown | 8.6 |  |
| `107_08` | Unknown | 13.8 |  |
| `107_09` | Unknown | 10.4 |  |
| `107_10` | Unknown | 9.5 |  |
| `107_11` | Unknown | 10.0 |  |
| `107_12` | Unknown | 4.2 |  |
| `107_13` | Unknown | 3.6 |  |
| `107_14` | Unknown | 7.4 |  |

### 피험자 108

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `108_01` | Unknown | 6.0 |  |
| `108_02` | Unknown | 9.5 |  |
| `108_03` | Unknown | 10.2 |  |
| `108_04` | Unknown | 1.5 |  |
| `108_05` | Unknown | 1.5 |  |
| `108_06` | Unknown | 1.6 |  |
| `108_07` | Unknown | 1.9 |  |
| `108_08` | Unknown | 1.9 |  |
| `108_09` | Unknown | 2.1 |  |
| `108_10` | Unknown | 2.0 |  |
| `108_11` | Unknown | 2.0 |  |
| `108_12` | Unknown | 1.1 |  |
| `108_13` | Unknown | 1.3 |  |
| `108_14` | Unknown | 1.5 |  |
| `108_15` | Unknown | 3.0 |  |
| `108_16` | Unknown | 2.9 |  |
| `108_17` | Unknown | 1.9 |  |
| `108_18` | Unknown | 2.0 |  |
| `108_19` | Unknown | 2.1 |  |
| `108_20` | Unknown | 2.3 |  |
| `108_21` | Unknown | 4.1 |  |
| `108_22` | Unknown | 3.9 |  |
| `108_23` | Unknown | 5.5 |  |
| `108_24` | Unknown | 4.4 |  |
| `108_25` | Unknown | 5.1 |  |
| `108_26` | Unknown | 4.6 |  |
| `108_27` | Unknown | 3.5 |  |
| `108_28` | Unknown | 3.0 |  |

### 피험자 111

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `111_01` | Walk backwards | 8.3 |  |
| `111_02` | Bow | 3.5 |  |
| `111_03` | Crawling | 12.7 |  |
| `111_04` | Curtsey | 6.1 |  |
| `111_05` | Dance | 7.7 |  |
| `111_06` | Get up from floor | 12.7 |  |
| `111_07` | Get up from floor | 16.4 |  |
| `111_08` | Get up from floor | 12.8 |  |
| `111_09` | Get up from chair | 6.5 |  |
| `111_10` | get up from chair | 3.7 |  |
| `111_11` | get up from chair | 4.8 |  |
| `111_12` | Lay down | - |  |
| `111_13` | March | 10.7 |  |
| `111_14` | Mope | 10.7 |  |
| `111_15` | Motorcycle | 2.2 |  |
| `111_16` | Peekaboo | - |  |
| `111_17` | Pick up | 4.7 |  |
| `111_18` | Pick up | 4.5 |  |
| `111_19` | Punch Kick | 8.5 |  |
| `111_20` | Ring around the rosie | 8.8 |  |
| `111_21` | Roll over | 19.0 |  |
| `111_22` | Range of motion | - |  |
| `111_23` | Run | 9.4 |  |
| `111_24` | Run | 7.2 |  |
| `111_25` | Shrug | 2.4 |  |
| `111_26` | Walk sideways | 22.7 |  |
| `111_27` | Walking up stairs | 12.1 |  |
| `111_28` | Standing still | 15.9 |  |
| `111_29` | Stepping over | 4.5 |  |
| `111_30` | Stepping over | 3.9 |  |
| `111_31` | Stepping up / stepping down | 18.7 |  |
| `111_32` | Stretch and yawn | 6.2 |  |
| `111_33` | Throwing | 17.2 |  |
| `111_34` | Walk | 15.3 |  |
| `111_35` | Walk | 12.5 |  |
| `111_36` | Walk and carry | 12.2 |  |
| `111_37` | Wave | 2.7 |  |
| `111_38` | Yoga | 22.0 |  |
| `111_39` | Yoga | 34.1 |  |
| `111_40` | Yoga | 2.6 |  |
| `111_41` | Yoga | 30.8 |  |

### 피험자 113

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `113_01` | Walk backwards | 7.0 |  |
| `113_02` | Bow | 4.4 |  |
| `113_03` | Curtsey | 4.0 |  |
| `113_04` | Dance | 8.1 |  |
| `113_05` | Walk digital 8 | 22.2 |  |
| `113_06` | Walk figure 8 | 16.9 |  |
| `113_07` | Run | 4.8 |  |
| `113_08` | Lay down and get up | 15.4 |  |
| `113_09` | March | 10.0 |  |
| `113_10` | Walk, mope around | 11.1 |  |
| `113_11` | Motorcycle | 2.3 |  |
| `113_12` | Peekaboo | 3.3 |  |
| `113_13` | Punch and kick | 11.2 |  |
| `113_14` | Ring around the rosie | 8.4 |  |
| `113_15` | Sit in chair and get up | 7.9 |  |
| `113_16` | Shrug | 5.8 |  |
| `113_17` | Walk sideway | 15.4 |  |
| `113_18` | Walk sideways | 18.3 |  |
| `113_19` | Walking up and down stairs | 6.7 |  |
| `113_20` | Walk up and down stairs | 12.1 |  |
| `113_21` | Standing Still | 11.4 |  |
| `113_22` | Step over | 9.9 |  |
| `113_23` | Stretch and yawn | 8.4 |  |
| `113_24` | Throw | 9.2 |  |
| `113_25` | Walk | 5.7 |  |
| `113_26` | Walk and carry | 11.0 |  |
| `113_27` | Wave | 3.0 |  |
| `113_28` | Yoga | 42.9 |  |
| `113_29` | Yoga | 36.0 |  |

### 피험자 114

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `114_01` | Motorcycle | 2.7 |  |
| `114_02` | Getting up from laying down | 14.5 |  |
| `114_03` | Range of motion | 31.8 |  |
| `114_04` | Getting up from chair | 7.5 |  |
| `114_05` | Sitting in chair | 22.7 |  |
| `114_06` | Getting up from chair | 8.5 |  |
| `114_07` | Walking up and down stairs | 13.5 |  |
| `114_08` | Walking up and down stairs | 13.4 |  |
| `114_09` | Walking up and down stairs | 19.0 |  |
| `114_10` | Stretching | 67.2 |  |
| `114_11` | Laying down and getting up | 29.0 |  |
| `114_12` | Stretching | 9.3 |  |
| `114_13` | Walk | 26.1 |  |
| `114_14` | Walk | 48.8 |  |
| `114_15` | Walk | 11.5 |  |
| `114_16` | Sit down and stretch | 14.4 |  |

### 피험자 115

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `115_01` | Pick up box, bend from waist | 7.8 |  |
| `115_02` | Pick box up, bend from waist | 6.7 |  |
| `115_03` | Pick box up, bend from waist | 7.5 |  |
| `115_04` | Pick box up, bend from waist | 6.3 |  |
| `115_05` | Pick box up, bend from waist | 9.8 |  |
| `115_06` | Picking box up, bending knees | 6.0 |  |
| `115_07` | Picking box up, bending knees | 6.9 |  |
| `115_08` | Picking box up, bending knees | 8.1 |  |
| `115_09` | Picking box up, bending knees | 6.7 |  |
| `115_10` | Pick box up, bend from waist | 6.1 |  |

### 피험자 117

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `117_01` | Unknown | - |  |
| `117_02` | Unknown | - |  |
| `117_03` | Unknown | - |  |
| `117_04` | Unknown | - |  |
| `117_05` | Unknown | - |  |
| `117_06` | Unknown | - |  |
| `117_07` | Unknown | - |  |
| `117_08` | Unknown | - |  |
| `117_09` | Unknown | - |  |
| `117_10` | Unknown | - |  |
| `117_11` | Unknown | - |  |
| `117_12` | Unknown | - |  |
| `117_13` | Unknown | - |  |
| `117_14` | Unknown | - |  |
| `117_15` | Unknown | - |  |

### 피험자 118

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `118_01` | Jump | 6.0 |  |
| `118_02` | Jump | 5.7 |  |
| `118_03` | Jump | 4.1 |  |
| `118_04` | Jump | 5.4 |  |
| `118_05` | Jump | 5.9 |  |
| `118_06` | Jump | 4.5 |  |
| `118_07` | Jump | 5.8 |  |
| `118_08` | Jump | 5.4 |  |
| `118_09` | Jump | 4.0 |  |
| `118_10` | Jump | 4.4 |  |
| `118_11` | Jump | 5.8 |  |
| `118_12` | Jump | 5.9 |  |
| `118_13` | Jump | 5.7 |  |
| `118_14` | Jump | 6.4 |  |
| `118_15` | Jump | 5.3 |  |
| `118_16` | Jump | 5.5 |  |
| `118_17` | Jump | 5.4 |  |
| `118_18` | Jump | 4.9 |  |
| `118_19` | Jump | 5.1 |  |
| `118_20` | Jump | 4.7 |  |
| `118_21` | Jump | 6.3 |  |
| `118_22` | Jump | 5.4 |  |
| `118_23` | Jump | 5.5 |  |
| `118_24` | Jump | 5.9 |  |
| `118_25` | Jump | 4.9 |  |
| `118_26` | Jump | 5.4 |  |
| `118_27` | Jump | 5.4 |  |
| `118_28` | Jump | 5.8 |  |
| `118_29` | Jump | 4.9 |  |
| `118_30` | Jump | 6.9 |  |
| `118_31` | Motorcycle | 1.7 |  |
| `118_32` | Range of motion | 15.6 |  |

### 피험자 120

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `120_01` | Alien Turn | 10.2 |  |
| `120_02` | Gorilla | 11.9 |  |
| `120_03` | Mickey cast spell | 12.6 |  |
| `120_04` | Mickey Conducting | 54.2 |  |
| `120_05` | Mickey Dance | 11.3 |  |
| `120_06` | Mickey Dance | 11.9 |  |
| `120_07` | Mickey Dance | 9.3 |  |
| `120_08` | Mickey sneaky walk | 10.0 |  |
| `120_09` | Mickey sneaking walk | 10.6 |  |
| `120_10` | Mickey sneaking walk | - |  |
| `120_11` | Mickey sneaking walk | 10.3 |  |
| `120_12` | Mickey sneaking walk | 8.7 |  |
| `120_13` | Mickey sneaking walk | 8.3 |  |
| `120_14` | Mickey sneaking walk | 10.7 |  |
| `120_15` | Mickey Surprised | 12.2 |  |
| `120_16` | Mickey Surprised | 12.6 |  |
| `120_17` | Mickey Walk | - |  |
| `120_18` | Mickey Walk | 11.4 |  |
| `120_19` | Walk slow | 106.6 |  |
| `120_20` | Walk | 89.5 |  |
| `120_21` | Robot | 25.9 |  |
| `120_22` | Zombie | 11.0 |  |

### 피험자 121

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `121_01` | Unknown | - |  |
| `121_02` | Unknown | - |  |
| `121_03` | Unknown | - |  |
| `121_04` | Unknown | - |  |
| `121_05` | Unknown | - |  |
| `121_06` | Unknown | - |  |
| `121_07` | Unknown | - |  |
| `121_08` | Unknown | - |  |
| `121_09` | Unknown | - |  |
| `121_10` | Unknown | - |  |
| `121_11` | Unknown | - |  |
| `121_12` | Unknown | - |  |
| `121_13` | Unknown | - |  |
| `121_14` | Unknown | - |  |
| `121_15` | Unknown | - |  |
| `121_16` | Unknown | - |  |
| `121_17` | Unknown | - |  |
| `121_18` | Unknown | - |  |
| `121_19` | Unknown | - |  |
| `121_20` | Unknown | - |  |
| `121_21` | Unknown | - |  |
| `121_22` | Unknown | - |  |
| `121_23` | Unknown | - |  |
| `121_24` | Unknown | - |  |
| `121_25` | Unknown | - |  |
| `121_26` | Unknown | - |  |
| `121_27` | Unknown | - |  |
| `121_28` | Unknown | - |  |
| `121_29` | Unknown | - |  |
| `121_30` | Unknown | - |  |
| `121_31` | Unknown | - |  |
| `121_32` | Unknown | - |  |
| `121_33` | Unknown | - |  |
| `121_34` | Unknown | - |  |
| `121_35` | Unknown | - |  |
| `121_36` | Unknown | - |  |

### 피험자 122

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `122_01` | clean | 5.3 |  |
| `122_02` | clean | 3.0 |  |
| `122_03` | clean | 5.6 |  |
| `122_04` | clean | 3.9 |  |
| `122_05` | clean | 4.0 |  |
| `122_06` | clean | 3.3 |  |
| `122_07` | clean | 3.5 |  |
| `122_08` | clean | 3.9 |  |
| `122_09` | clean | 3.8 |  |
| `122_10` | clean | 4.0 |  |
| `122_11` | Unknown | 0.8 |  |
| `122_12` | clean | 4.2 |  |
| `122_13` | clean | 4.2 |  |
| `122_14` | clean | 3.6 |  |
| `122_15` | clean | 4.3 |  |
| `122_16` | clean | 4.2 |  |
| `122_17` | clean | 4.4 |  |
| `122_18` | clean | 3.9 |  |
| `122_19` | clean | 4.2 |  |
| `122_20` | clean | 4.4 |  |
| `122_21` | clean | 4.3 |  |
| `122_22` | clean | 44.8 |  |
| `122_23` | clean | 4.5 |  |
| `122_24` | clean | 4.4 |  |
| `122_25` | clean | 4.5 |  |
| `122_26` | clean | 4.3 |  |
| `122_27` | clean | 8.2 |  |
| `122_28` | clean | 7.8 |  |
| `122_29` | clean | 7.9 |  |
| `122_30` | clean | 8.4 |  |
| `122_31` | clean | 7.8 |  |
| `122_32` | clean | 8.7 |  |
| `122_33` | clean | 10.8 |  |
| `122_34` | clean | 8.1 |  |
| `122_35` | clean | 8.7 |  |
| `122_36` | clean | 8.8 |  |
| `122_37` | clean | 8.0 |  |
| `122_38` | clean | 8.4 |  |
| `122_39` | clean | 8.1 |  |
| `122_40` | clean | 4.4 |  |
| `122_41` | clean | 3.9 |  |
| `122_42` | clean | 4.5 |  |
| `122_43` | clean | 5.0 |  |
| `122_44` | clean | 5.5 |  |
| `122_45` | clean | 4.1 |  |
| `122_46` | clean | 4.2 |  |
| `122_47` | clean | 5.2 |  |
| `122_48` | clean | 3.7 |  |
| `122_49` | clean | 3.8 |  |
| `122_50` | clean | 4.4 |  |
| `122_51` | clean | 4.9 |  |
| `122_52` | clean | 4.2 |  |
| `122_53` | clean | 4.5 |  |
| `122_54` | clean | 3.5 |  |
| `122_55` | clean | 6.1 |  |
| `122_56` | clean | 4.2 |  |
| `122_57` | clean | 3.4 |  |
| `122_58` | cleaned | 3.0 |  |
| `122_59` | clean | 5.0 |  |
| `122_60` | clean | 3.4 |  |
| `122_61` | clean | 4.2 |  |
| `122_62` | clean | 4.0 |  |
| `122_63` | clean | 5.7 |  |
| `122_64` | clean | 4.8 |  |
| `122_65` | clean | 3.3 |  |
| `122_66` | clean | 5.6 |  |
| `122_67` | clean | 5.6 |  |
| `122_68` | clean | 5.5 |  |

### 피험자 123

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `123_01` | 15.5 lbs | 6.0 |  |
| `123_02` | 15.5 lbs | 6.3 |  |
| `123_03` | 19.5lb | 15.4 |  |
| `123_04` | 19.5 lbs | 13.9 |  |
| `123_05` | 19.5 lbs | 7.5 |  |
| `123_06` | 19.5 lbs | 7.0 |  |
| `123_07` | 12.5lb | 13.0 |  |
| `123_08` | 12.5 lbs | 7.1 |  |
| `123_09` | 12.5 lbs | 7.0 |  |
| `123_10` | 12.5lb | 6.7 |  |
| `123_11` | 15.5 lbs | 5.2 |  |
| `123_12` | 15.5 lbs | 6.6 |  |
| `123_13` | 15.5 lbs | 5.6 |  |

### 피험자 124

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `124_01` | Baseball Pitch | 5.4 |  |
| `124_02` | Baseball Pitch | - |  |
| `124_03` | Basketball Shoot | 8.0 |  |
| `124_04` | Basketball Free Throw | 6.0 |  |
| `124_05` | Basketball Jump Shot | - |  |
| `124_06` | Basketball Lay Up | 5.8 |  |
| `124_07` | Baseball Swing | 10.8 |  |
| `124_08` | Baseball Bunt | 6.5 |  |
| `124_09` | Frisbee | - |  |
| `124_10` | Motorcycle | 2.1 |  |
| `124_11` | 2 Foot Jump | 8.3 |  |
| `124_12` | Underhand Toss | 12.4 |  |
| `124_13` | Underhand Fast Pitch | 7.2 |  |

### 피험자 125

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `125_01` | Breast Stroke | 35.5 |  |
| `125_02` | Breast Stroke | 35.6 |  |
| `125_03` | Break Stroke | 36.7 |  |
| `125_04` | Breast Stroke | - |  |
| `125_05` | Butterfly | 22.3 |  |
| `125_06` | Free Style | 40.7 |  |
| `125_07` | Motorcycle | - |  |

### 피험자 126

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `126_01` | Back Stroke | 21.6 |  |
| `126_02` | Back Stroke | 14.7 |  |
| `126_03` | Breast Stroke | 21.5 |  |
| `126_04` | Breast Stroke | 13.8 |  |
| `126_05` | Breast Stroke | 13.0 |  |
| `126_06` | Fly Stroke | 20.9 |  |
| `126_07` | Fly Stroke | 21.0 |  |
| `126_08` | Fly Stroke | 12.8 |  |
| `126_09` | Fly Stroke | 14.8 |  |
| `126_10` | Free Style | 10.4 |  |
| `126_11` | Free Style | 15.2 |  |
| `126_12` | Free Style | 20.1 |  |
| `126_13` | Motorcycle | 1.0 |  |
| `126_14` | Range of Motion | 56.3 |  |

### 피험자 127

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `127_01` | Motorcycle | 2.1 |  |
| `127_02` | Range of Motion | 14.7 |  |
| `127_03` | Run | 2.8 |  |
| `127_04` | Walk to Run | 3.7 |  |
| `127_05` | Run to Quick Stop | 3.2 |  |
| `127_06` | Run | 1.4 |  |
| `127_07` | Run | 1.2 |  |
| `127_08` | Run | 1.2 |  |
| `127_09` | Run Right | 1.6 |  |
| `127_10` | Run Right | 1.4 |  |
| `127_11` | Run Left | 1.7 |  |
| `127_12` | Run Left | 1.5 |  |
| `127_13` | Run Side Step Left | 1.5 |  |
| `127_14` | Run Side Step Right | 1.3 |  |
| `127_15` | Run Turn Left | 1.4 |  |
| `127_16` | Run Turn Right | 2.1 |  |
| `127_17` | Run Stop Run | 3.2 |  |
| `127_18` | Run Stop Run | 3.3 |  |
| `127_19` | Run Quick Stop Run | 3.7 |  |
| `127_20` | Run Quick Stop Run | 3.0 |  |
| `127_21` | Run Jump Stop Run | 3.0 |  |
| `127_22` | Run Jump Stop Run | 3.0 |  |
| `127_23` | Run Dive Over Roll Run | 2.9 |  |
| `127_24` | Run Dive Over Roll Run | 2.8 |  |
| `127_25` | Run Jump Over | 1.9 |  |
| `127_26` | Run Jump Over | 2.0 |  |
| `127_27` | Run Jump Over | - |  |
| `127_28` | Run Jump Over | 1.8 |  |
| `127_29` | Run Duck Underneath | 1.7 |  |
| `127_30` | Run Duck Underneath | 2.0 |  |
| `127_31` | Run Duck Underneath | 4.3 |  |
| `127_32` | Run Duck Underneath | - |  |
| `127_33` | Run Over | 1.7 |  |
| `127_34` | Run Over | 1.7 |  |
| `127_35` | Run Over | 2.0 |  |
| `127_36` | Run Over | 1.8 |  |
| `127_37` | Run Duck Underneath | 2.9 |  |
| `127_38` | Run Duck Underneath | 1.6 |  |

### 피험자 128

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `128_01` | Motorcycle | 2.7 |  |
| `128_02` | Run Left | 1.4 |  |
| `128_03` | Run Right | 1.4 |  |
| `128_04` | Run Duck Underneath | 1.1 |  |
| `128_05` | Run Stop Run | 1.7 |  |
| `128_06` | Run Stop Run | 1.6 |  |
| `128_07` | Run Stop Run | 2.9 |  |
| `128_08` | Run Stop Run | 2.8 |  |
| `128_09` | Run Roll Underneath | 1.4 |  |
| `128_10` | Run Dive Over Roll Run | 3.6 |  |
| `128_11` | Run Dive Over Roll Run | 3.1 |  |

### 피험자 131

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `131_01` | Start Walk Stop | 8.3 |  |
| `131_02` | Start Walk Stop | 10.4 |  |
| `131_03` | Start Hop Stop | 9.2 |  |
| `131_04` | Start Hop Stop | 9.1 |  |
| `131_05` | Start Duck Underneath Stop | 10.5 |  |
| `131_06` | Start Duck Underneath Stop | 9.9 |  |
| `131_07` | Jump Stop | 5.8 |  |
| `131_08` | Jump Stop | 6.5 |  |
| `131_09` | Start Walk Left | 19.1 |  |
| `131_10` | Start Walk Left | 14.8 |  |
| `131_11` | Start Walk Left | 9.7 |  |
| `131_12` | Start Walk Right | 6.4 |  |
| `131_13` | Start Walk Right | 11.0 |  |
| `131_14` | Start Walk Right | 16.1 |  |

### 피험자 132

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `132_01` | Walk With Arms Out,  balancing | 11.8 |  |
| `132_02` | Walk With Arms Out,  balancing | 9.5 |  |
| `132_03` | Walk With Arms Out,  balancing | 12.3 |  |
| `132_04` | Walk With Arms Out,  balancing | 11.2 |  |
| `132_05` | Walk With Arms Out,  balancing | 11.0 |  |
| `132_06` | Walk With Arms Out,  balancing | 11.1 |  |
| `132_07` | Walk With Arms Out,  balancing | 7.5 |  |
| `132_08` | Walk With Arms Out,  balancing | 12.1 |  |
| `132_09` | Walk With Arms Out,  balancing | 9.8 |  |
| `132_10` | Walk With Arms Out,  balancing | 13.5 |  |
| `132_11` | Walk With Arms Out,  balancing | 13.4 |  |
| `132_12` | Walk With Arms Out,  balancing | 13.2 |  |
| `132_13` | Walk Backwards | - |  |
| `132_14` | Walk Duck Footed | - |  |
| `132_15` | Walk With Knees Bent | 54.5 |  |
| `132_16` | Walk Crossover | - |  |
| `132_17` | Walk Fast | 2.2 |  |
| `132_18` | Walk Fast | 3.5 |  |
| `132_19` | Walk Fast | 2.3 |  |
| `132_20` | Walk Fast | 2.9 |  |
| `132_21` | Walk Fast | 3.0 |  |
| `132_22` | Walk Fast | 3.1 |  |
| `132_23` | Hop on left foot | - |  |
| `132_24` | Hop on left foot | 6.2 |  |
| `132_25` | Hop on left foot | 4.6 |  |
| `132_26` | Hop on left foot | - |  |
| `132_27` | Hop on left foot | 6.1 |  |
| `132_28` | Hop on left foot | 6.0 |  |
| `132_29` | Bouncy Walk | 6.5 |  |
| `132_30` | Bouncy Walk | 6.5 |  |
| `132_31` | Bouncy Walk | 6.0 |  |
| `132_32` | Bouncy Walk | 5.4 |  |
| `132_33` | Bouncy Walk | 3.4 |  |
| `132_34` | Bouncy Walk | 4.3 |  |
| `132_35` | Walk Leaning To The Right | 10.5 |  |
| `132_36` | Walk Leaning To The Right | 32.5 |  |
| `132_37` | Marching | 56.1 |  |
| `132_38` | Motorcycle | 1.5 |  |
| `132_39` | Pigeon Toed Walking | 52.1 |  |
| `132_40` | Walk With Stiff Arms | 7.1 |  |
| `132_41` | Walk With Stiff Arms | 53.0 |  |
| `132_42` | Walk Swinging Shoulders | 5.8 |  |
| `132_43` | Walk Swinging Shoulders | 6.7 |  |
| `132_44` | Walk Swinging Shoulders | 43.4 |  |
| `132_45` | Walk Slow | 12.8 |  |
| `132_46` | Walk Slow | 10.2 |  |
| `132_47` | Walk Slow | 12.6 |  |
| `132_48` | Walk Slow | 13.5 |  |
| `132_49` | Walk Slow | - |  |
| `132_50` | Walk Slow | 17.8 |  |
| `132_51` | Tpose | 1.4 |  |
| `132_52` | Range of Motion | 11.1 |  |
| `132_53` | Walk With Legs Apart | 54.2 |  |
| `132_54` | Walk With Wild Arms | 50.2 |  |
| `132_55` | Walk With Wild Legs | 25.8 |  |
| `132_56` | Walk With Wild Legs | - |  |

### 피험자 133

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `133_01` | Walk Crawl | 11.5 |  |
| `133_02` | Walk Crawl | 11.9 |  |
| `133_03` | Walk Jump | 10.5 |  |
| `133_04` | Walk Jump | 6.5 |  |
| `133_05` | Walk Jump | 8.1 |  |
| `133_06` | Walk Jump | 7.3 |  |
| `133_07` | Walk Jump | 8.2 |  |
| `133_08` | Stretch Walk | 10.3 |  |
| `133_09` | Stretch Walk | 14.4 |  |
| `133_10` | Stretch Walk | 11.0 |  |
| `133_11` | Walk Stop Walk | 8.8 |  |
| `133_12` | Walk Stop Walk | 8.1 |  |
| `133_13` | Walk Stop Walk | 9.5 |  |
| `133_14` | Walk Left | 7.4 |  |
| `133_15` | Walk Left | 7.4 |  |
| `133_16` | Walk Left | 4.2 |  |
| `133_17` | Walk Right | 4.8 |  |
| `133_18` | Walk Right | 3.9 |  |
| `133_19` | Walk Right | 7.0 |  |
| `133_20` | Walk Right | 9.1 |  |
| `133_21` | Walk | 6.5 |  |
| `133_22` | Walk | 6.3 |  |
| `133_23` | Walk | 7.1 |  |
| `133_24` | Walk ZigZag | 7.9 |  |
| `133_25` | Motorcycle | 3.4 |  |
| `133_26` | Range of Motion | 10.3 |  |

### 피험자 134

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `134_01` | Duck Under | - |  |
| `134_02` | Go Forward | - |  |
| `134_03` | Lean Turn Right | - |  |
| `134_04` | Motorcycle | - |  |
| `134_05` | Pump Jump | - |  |
| `134_06` | Push Turn Left | - |  |
| `134_07` | Push Turn Left | - |  |
| `134_08` | Push Turn Right | - |  |
| `134_09` | Push Turn Right | - |  |
| `134_10` | Start | - |  |
| `134_11` | Start | - |  |
| `134_12` | Stop and Go | - |  |
| `134_13` | Stop and Go | - |  |
| `134_14` | Stop ang Go | - |  |
| `134_15` | Lean Turn Left | - |  |

### 피험자 135

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `135_01` | Bassai | - |  |
| `135_02` | Empi | 43.4 |  |
| `135_03` | Empi | 22.9 |  |
| `135_04` | Front Kick | 11.0 |  |
| `135_05` | Gedanbarai | 20.5 |  |
| `135_06` | Heiansyodan | 27.2 |  |
| `135_07` | Mawashigeri | 12.3 |  |
| `135_08` | Motorcycle | 2.4 |  |
| `135_09` | Oiduki | 17.9 |  |
| `135_10` | Syutouuke | 16.7 |  |
| `135_11` | Yokogeri | 20.4 |  |

### 피험자 136

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `136_01` | Walk Bent Forward | 7.3 |  |
| `136_02` | Walk Bent Forward | 7.2 |  |
| `136_03` | Walk Backwards Bent Forward | 10.0 |  |
| `136_04` | Walk Backwards Bent Forward | 10.6 |  |
| `136_05` | Walk on Toes Bent Forward | 8.5 |  |
| `136_06` | Walk on Toes Bent Forward | 7.9 |  |
| `136_07` | Walk Backward on Toes Bent Forward | 9.2 |  |
| `136_08` | Walk Backward on Toes Bent Forward | 11.1 |  |
| `136_09` | Walk Crouched | 9.4 |  |
| `136_10` | Walk Crouched | - |  |
| `136_11` | Walk Backwards Crouched | 12.0 |  |
| `136_12` | Walk Backwards Crouched | 10.9 |  |
| `136_13` | Walk on Toes Crouched | 10.4 |  |
| `136_14` | Walk on Toes Crouched | 8.9 |  |
| `136_15` | Walk Backwards on Toes Crouched | 11.2 |  |
| `136_16` | Walk Backwards on Toes Crouched | 10.5 |  |
| `136_17` | Flamingo, lift legs high | 17.7 |  |
| `136_18` | Flamingo, lift legs high | 12.4 |  |
| `136_19` | Motorcycle | - |  |
| `136_20` | Normal Walk | 8.3 |  |
| `136_21` | Normal Walk | 5.0 |  |
| `136_22` | Normal Walk | 7.0 |  |
| `136_23` | Normal Walk | 6.2 |  |
| `136_24` | Normal Walk | 9.0 |  |
| `136_25` | Normal Walk Backwards | 14.9 |  |
| `136_26` | Normal Walk Backwards | 11.8 |  |
| `136_27` | Walk on Toes | 9.1 |  |
| `136_28` | Walk on Toes | - |  |
| `136_29` | Walk Backwards on Toes | 9.8 |  |
| `136_30` | Walk Backwards on Toes | 10.6 |  |
| `136_31` | Quail, quick little steps | 12.0 |  |
| `136_32` | Quail, quick little steps | 12.0 |  |
| `136_33` | Range of Motion | 8.2 |  |

### 피험자 137

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `137_01` | Cat Coffee Mug | 18.0 |  |
| `137_02` | Cat Pick Up | 18.1 |  |
| `137_03` | Cat Wait | 54.5 |  |
| `137_04` | Cat Walk | 16.1 |  |
| `137_05` | Chicken Coffee Mug | 14.7 |  |
| `137_06` | Chicken Pick Up | 13.6 |  |
| `137_07` | Chicken Wait | 39.8 |  |
| `137_08` | Chicken Walk | 16.1 |  |
| `137_09` | Dinosaur Coffee Mug | 20.6 |  |
| `137_10` | Dinosaur Pick Up | 18.7 |  |
| `137_11` | Dinosaur Wait | 41.1 |  |
| `137_12` | Dinosaur Walk | 16.4 |  |
| `137_13` | Drunk Coffee Mug | 24.7 |  |
| `137_14` | Drunk Pick Up | 18.9 |  |
| `137_15` | Drunk Wait | 44.9 |  |
| `137_16` | Drunk Walk | 12.8 |  |
| `137_17` | Gangly Teen Coffee Mug | 16.2 |  |
| `137_18` | Gangly Teen Pick Up | 11.6 |  |
| `137_19` | Gangly Teen Wait | 44.3 |  |
| `137_20` | Gangly Teen Walk | 13.4 |  |
| `137_21` | Graceful Lady Coffee Mug | 15.9 |  |
| `137_22` | Graceful Lady Pick Up | 13.7 |  |
| `137_23` | Graceful Lady Wait | 37.9 |  |
| `137_24` | Graceful Lady Walk | 9.9 |  |
| `137_25` | Motorcycle | 1.3 |  |
| `137_26` | Normal Coffee Mug | 13.1 |  |
| `137_27` | Normal Pick Up | 9.7 |  |
| `137_28` | Normal Wait | 31.0 |  |
| `137_29` | Normal Walk | 9.4 |  |
| `137_30` | Old Man Coffee Mug | - |  |
| `137_31` | Old Man Pick Up | 28.1 |  |
| `137_32` | Old Man Wait | 41.8 |  |
| `137_33` | Old Man Walk | 25.5 |  |
| `137_34` | Range of Motion | 7.5 |  |
| `137_35` | Sexy Lady Coffee Mug | 20.8 |  |
| `137_36` | Sexy Lady Pick Up | 21.3 |  |
| `137_37` | Sexy Lady Wait | 42.6 |  |
| `137_38` | Sexy Lady Walk | 16.8 |  |
| `137_39` | Strong Man Coffee Mug | 24.4 |  |
| `137_40` | Strong Man Pick Up | 17.0 |  |
| `137_41` | Strong Man Wait | 43.3 |  |
| `137_42` | Strong Man Walk | 18.2 |  |

### 피험자 138

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `138_01` | Marching | 6.7 |  |
| `138_02` | Marching | - |  |
| `138_03` | Marching | 5.7 |  |
| `138_04` | Marching | 5.8 |  |
| `138_05` | Marching | - |  |
| `138_06` | Marching | 3.3 |  |
| `138_07` | Marching | - |  |
| `138_08` | Marching | - |  |
| `138_09` | Marching | 3.6 |  |
| `138_10` | Marching | 3.6 |  |
| `138_11` | Story | 3.7 |  |
| `138_12` | Story | 2.7 |  |
| `138_13` | Story | - |  |
| `138_14` | Story | - |  |
| `138_15` | Story | - |  |
| `138_16` | Story | - |  |
| `138_17` | Story | 3.7 |  |
| `138_18` | Story | 3.2 |  |
| `138_19` | Story | 3.8 |  |
| `138_20` | Story | 3.8 |  |
| `138_21` | Story | 3.3 |  |
| `138_22` | Story | - |  |
| `138_23` | Story | 3.8 |  |
| `138_24` | Story | 4.2 |  |
| `138_25` | Story | 3.0 |  |
| `138_26` | Story | - |  |
| `138_27` | Story | - |  |
| `138_28` | Story | - |  |
| `138_29` | Story | - |  |
| `138_30` | Story | - |  |
| `138_31` | Story | - |  |
| `138_32` | Story | - |  |
| `138_33` | Story | - |  |
| `138_34` | Story | - |  |
| `138_35` | Story | - |  |
| `138_36` | Story | - |  |
| `138_37` | Story | - |  |
| `138_38` | Story | - |  |
| `138_39` | Story | - |  |
| `138_40` | Story | - |  |
| `138_41` | Story | - |  |
| `138_42` | Story | - |  |
| `138_43` | Story | - |  |
| `138_44` | Story | - |  |
| `138_45` | Story | - |  |
| `138_46` | Story | - |  |
| `138_47` | Story | - |  |
| `138_48` | Story | 5.2 |  |
| `138_49` | Story | - |  |
| `138_50` | Story | - |  |
| `138_51` | Story | - |  |
| `138_52` | Story | - |  |
| `138_53` | Story | - |  |
| `138_54` | Story | - |  |
| `138_55` | Story | - |  |

### 피험자 139

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `139_01` | Looking Around | 18.2 |  |
| `139_02` | Shifting Weight | 15.6 |  |
| `139_03` | Looking Around | 16.4 |  |
| `139_04` | Looking Around | 14.7 |  |
| `139_05` | Pulling a Gun | 8.5 |  |
| `139_06` | Poking Around On The Ground | 22.5 |  |
| `139_07` | Poking Around On The Ground | 8.4 |  |
| `139_08` | Poking Around On The Ground | 16.8 |  |
| `139_09` | Ducking | 16.5 |  |
| `139_10` | Run | 11.5 |  |
| `139_11` | Run To Sneak | 5.3 |  |
| `139_12` | Run in Circles | 16.3 |  |
| `139_13` | Run in Circles | 23.1 |  |
| `139_14` | Sneak Sideways | 16.5 |  |
| `139_15` | Sneak Sideways | 18.0 |  |
| `139_16` | Get Up From Ground | 10.9 |  |
| `139_17` | Get Up From Ground | 12.0 |  |
| `139_18` | Get Up From Ground Laying on Back | 14.2 |  |
| `139_19` | Walk Wounded Leg | 16.7 |  |
| `139_20` | Walk Wounded Leg | - |  |
| `139_21` | Range Of Motion | 10.9 |  |
| `139_22` | Walk Wounded Leg | 23.8 |  |
| `139_23` | Walk Wounded Leg | 26.5 |  |
| `139_24` | Walk Wounded Leg | 11.9 |  |
| `139_25` | Giving Directions | 11.1 |  |
| `139_26` | Looking Around | 10.8 |  |
| `139_27` | Looking Around | 12.1 |  |
| `139_28` | Walking | - |  |
| `139_29` | Sneaking | 35.1 |  |
| `139_30` | Walking | 21.0 |  |
| `139_31` | Sneaking | 35.1 |  |
| `139_32` | Sneaking | 31.6 |  |
| `139_33` | Sneaking | 50.0 |  |
| `139_34` | Sneaking | 18.7 |  |

### 피험자 140

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `140_01` | Get Up Face Down | 6.9 |  |
| `140_02` | Get Up Face Down | 7.8 |  |
| `140_03` | Get Up Laying on Side | - |  |
| `140_04` | Get Up Laying on Side | 9.2 |  |
| `140_05` | Motorcycle | - |  |
| `140_06` | Idle | 29.7 |  |
| `140_07` | Idle | 10.3 |  |
| `140_08` | Get Up From Ground Laying on Back | 7.5 |  |
| `140_09` | Get Up From Ground Laying on Back | 6.8 |  |

### 피험자 141

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `141_01` | Run | 1.2 |  |
| `141_02` | Run | 1.9 |  |
| `141_03` | Run | 3.8 |  |
| `141_04` | Jump Distances | 9.1 |  |
| `141_05` | Jump Sideways | 3.8 |  |
| `141_06` | Jump Twist | 10.8 |  |
| `141_07` | Walk Up and Over | 5.0 |  |
| `141_08` | Steop On Walk Down | 5.5 |  |
| `141_09` | Step Over | 3.9 |  |
| `141_10` | Toss and Catch | 8.4 |  |
| `141_11` | Throw and Catch | 11.4 |  |
| `141_12` | Dance, Twist | 9.5 |  |
| `141_13` | Stretch and Yawn | 6.1 |  |
| `141_14` | Punch and Kick | 9.6 |  |
| `141_15` | Range of Motion | 19.4 |  |
| `141_16` | Wave Hello | 5.0 |  |
| `141_17` | Sit on Stool | 9.3 |  |
| `141_18` | Peek a Boo | 6.5 |  |
| `141_19` | Walk | 19.9 |  |
| `141_20` | Waiting | 12.7 |  |
| `141_21` | Shrug | 4.5 |  |
| `141_22` | High Five | 3.3 |  |
| `141_23` | Shake Hands | 4.3 |  |
| `141_24` | Around the world High Five Low | 4.3 |  |
| `141_25` | Walk | 10.2 |  |
| `141_26` | Curtsey | 6.6 |  |
| `141_27` | Mope | 9.2 |  |
| `141_28` | Slap Hands, Throw it Back | 5.9 |  |
| `141_29` | Random Walk | 19.4 |  |
| `141_30` | Random Walk | 12.0 |  |
| `141_31` | Walk Backwards | 11.2 |  |
| `141_32` | Walk Sideways, Cross Legs | 14.8 |  |
| `141_33` | Walk Sideways, Foot to Foot | 17.6 |  |
| `141_34` | Run | 5.2 |  |

### 피험자 142

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `142_01` | Childish | 43.7 |  |
| `142_02` | Clumsy | 15.7 |  |
| `142_03` | Clumsy | - |  |
| `142_04` | Cool | 31.1 |  |
| `142_05` | Depressed | - |  |
| `142_06` | Elated | 22.0 |  |
| `142_07` | Elderlyman | - |  |
| `142_08` | Happy | 25.3 |  |
| `142_09` | Joy | 22.2 |  |
| `142_10` | Lavish | - |  |
| `142_11` | Marching | 27.3 |  |
| `142_12` | Painfulleftknee | 39.2 |  |
| `142_13` | Relaxed | 43.0 |  |
| `142_14` | Rushed | 13.9 |  |
| `142_15` | Sad | 44.8 |  |
| `142_16` | Scared | 48.5 |  |
| `142_17` | Scared | 36.9 |  |
| `142_18` | Sexy | 40.8 |  |
| `142_19` | Shy | 37.4 |  |
| `142_20` | Singing in the rain jump | 12.8 |  |
| `142_21` | Singing in the rain jump | 11.8 |  |
| `142_22` | Sneaky | 43.5 |  |

### 피험자 143

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `143_01` | Run | 1.7 |  |
| `143_02` | Run to Stop | 3.5 |  |
| `143_03` | Start to Run | 4.0 |  |
| `143_04` | Run Figure 8 | 18.1 |  |
| `143_05` | Jumping Distances | 5.6 |  |
| `143_06` | Jumping Heights | 6.5 |  |
| `143_07` | Jumping Sideways | 9.3 |  |
| `143_08` | Jumping Twists | 6.5 |  |
| `143_09` | Jumping Twists | 9.1 |  |
| `143_10` | Walk And Pick up Tool Box | 9.6 |  |
| `143_11` | Walk And Pick up Box | 10.9 | BVH, C3D |
| `143_12` | Walk And Pick up Toolbox | 9.8 |  |
| `143_13` | Walk and Pick up Laundry Basket | 9.7 | BVH, C3D |
| `143_14` | Walk And Step Over | 12.1 |  |
| `143_15` | Walk And Step Over | 11.8 |  |
| `143_16` | Walk And Step Over | 10.2 |  |
| `143_17` | Walk Up Stairs And Over | 10.5 |  |
| `143_18` | Sit Down And Get Up | 12.5 |  |
| `143_19` | Sit On Stool And Get Up | 14.0 |  |
| `143_20` | Catch And Throw | 10.8 |  |
| `143_21` | Range Of Motion | - |  |
| `143_22` | Catch And Throw Football | 18.2 |  |
| `143_23` | Punching | 13.6 |  |
| `143_24` | Kicking | 16.8 |  |
| `143_25` | Waving | 11.0 |  |
| `143_26` | Washing Window | 10.6 |  |
| `143_27` | Washing Window | 11.7 |  |
| `143_28` | Sweeping, Push Broom | 10.7 | BVH, C3D |
| `143_29` | Pacing | 18.0 |  |
| `143_30` | Stretch And Yawn | 6.2 |  |
| `143_31` | Hopscotch | 7.0 |  |
| `143_32` | Walk | 13.0 |  |
| `143_33` | Peek A Boo | 6.0 |  |
| `143_34` | Chicken Dance | 13.1 |  |
| `143_35` | Macarena Dance | 21.3 |  |
| `143_36` | Airplane | 12.7 |  |
| `143_37` | Climb Up And Down Ladder | 9.2 |  |
| `143_38` | Walk Digital 8 | 21.9 |  |
| `143_39` | Walk Backwards | 18.1 |  |
| `143_40` | Walk Sideways | 16.1 |  |
| `143_41` | Sneak | 19.4 |  |
| `143_42` | Run | 8.9 |  |

### 피험자 144

| 번호 | CMU 설명 | 길이 (s) | 예제 |
|---|---|---|---|
| `144_01` | Cartwheels | 20.5 |  |
| `144_02` | Cartwheels001 | 19.4 |  |
| `144_03` | Figure8s | 37.3 |  |
| `144_04` | Figure8s001 | 32.3 |  |
| `144_05` | Front_Kicking | 23.2 |  |
| `144_06` | Front_Kicking001 | 30.3 |  |
| `144_07` | Left_Blocks | 20.4 |  |
| `144_08` | Left_Blocks001 | 25.0 |  |
| `144_09` | Left_Front_Kicking | 28.2 |  |
| `144_10` | Left_Front_Kicking001 | 29.1 |  |
| `144_11` | Left_Lunges | 28.6 |  |
| `144_12` | Left_Lunges001 | 27.7 |  |
| `144_13` | Left_Punch_Sequence001 | 16.2 |  |
| `144_14` | Left_Punch_Sequence002 | 17.1 |  |
| `144_15` | Left_Spin_reach001 | 27.5 |  |
| `144_16` | Left_Spin_reach002 | 25.7 |  |
| `144_17` | Lunges | 23.5 |  |
| `144_18` | Lunges001 | 25.8 |  |
| `144_19` | motorcycle pose | 2.9 |  |
| `144_20` | Punch_Sequence | 18.9 |  |
| `144_21` | Punch_Sequence001 | 16.1 |  |
| `144_22` | Reach_Left001 | 27.8 |  |
| `144_23` | Reach_Left002 | 28.4 |  |
| `144_24` | Reach_Right | 39.2 |  |
| `144_25` | Reach_Right001 | - |  |
| `144_26` | Right_Blocks | 27.9 |  |
| `144_27` | Right_Blocks001 | 22.1 |  |
| `144_28` | Right_Spin_reach | 19.1 |  |
| `144_29` | Right_Spin_reach001 | 25.7 |  |
| `144_30` | Sun Salutation | - |  |
| `144_31` | Sun Salutation001 | - |  |
| `144_32` | Sun Salutation002 | 43.4 |  |
| `144_33` | Walking | - |  |
| `144_34` | Walking001 | 39.1 |  |
