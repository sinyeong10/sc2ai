
### 7. [진행중] 2023년 스타크래프트2 build 강화학습
#### 목표 : 스타크래프트2 빌드를 강화학습을 통해서 최적화
[관련 코드](https://github.com/sinyeong10/sc2ai)

#### 느낀점
1. 스타크래프트2의 라이브러리를 활용하여 먼저 if문으로 강화학습으로 들어갈 명령을 구현하였다.

이 과정 속에서 ASSIMILATOR에 들어간 workers의 정보가 누락된다는 것과 자원 최적화하는 distribute_workers 함수의 문제점을 찾을 수 있었다.

운영체제 수업에서 배운 여러 lock 개념을 통해서 시도하며 가스에 일꾼을 이동시키는 것과 가장 가까운 일꾼이 넥서스 인접 지역에 가스를 건설하게 하였다.

2. 특정 빌드의 최적화를 목표로 spinlock처럼 매 프레임마다 상태, 액션을 처리하는 환경을 구성하여 강화학습을 하고자 하였다.

하지만 매 프레임마다 액션을 계산할 때 실행되지 않는 명령이 더 많아 제대로 학습이 되었는 지 평가하기 어려워 현재 액션이 끝나고 난 후에 다음 액션을 받는 형태로 처리하였다.

모델 학습에서 cpu가 100%라.. 지인의 노트북 환경에서 학습을 진행하였다..

복잡한 상태를 분석하는 것이 어려워 먼저 쉬운 문제부터 해결해보고자 하였다.

3. grid search보다 더 효율적으로 최적화된 빌드를 찾아야 하기에 back-tracking으로 가능한 모든 경우를 생성하여 기록을 저장하였다.

질럿 5기의 모든 경우 : 1014784가지, 질럿 생산 이후 일꾼 생산 x, 현재 생산 위치 기준 파일런 필요한 경우에 짓는 경우 : 4801가지

4. 이후 노트북 2대를 활용하여 간단한 socket 통신을 통해서 강화학습 모델과 강화학습 환경을 따로 돌리게 하였다.

5. 연속적으로 모델 학습 가능한 환경을 구축하였다.

이 과정 속에서 불가능한 경우를 환경에 대한 액션을 줄 때 계산하여 처리하게 하였다.

불가능한 액션을 선택할 때 대부분 현재 위치 그대로 오게 하여 액션 수를 늘려 감가율을 통해 더 짧은 액션을 주게 한다.

하지만 여기에서는 액션이 긴 경우가 더 빨리 끝나는 경우도 존재하여 감가율을 사용하지 못한다.

6. 강화학습 책을 토대로 라이브러리를 가져와 맞추는 것이 아닌 필요한 기능을 가진 코드를 구현하였다.

프레임이 빠를 수록 더 큰 보상을 주기 위해 지수함수를 최종 보상으로 주었다.

최종 완료 시점을 기준으로 중간 명령을 프레임의 비율로 보상을 줄 경우를 주고자 하였다.

이 경우 일꾼을 생성하는 경우는 바로 실행되어 0,1 프레임에 계산된다. 1을 일괄적으로 가산하여 처리할 수 있다.

하지만 더 긴 최종 프레임에서 중간 과정의 보상이 더 큰 경우가 존재하여 해당 방법은 제대로 학습되지 않는다.

7. 질럿 2기를 생성하는 경우를 학습할 때 상태와 액션에 대한 가치를 분석하기 위해 시각화하였다.

질럿 2기의 모든 경우 : 318가지, 질럿 생산 이후 일꾼 생산 x, 현재 생산 위치 기준 파일런 필요한 경우에 짓는 경우 : 177가지

잘못된 액션의 경우 바로 끝나기 때문에 -보상을 주지 않으면 목표까지 잘 찾아가지 못한다.

하지만 -보상의 영향을 바로 직전 상태에만 주지 않고 이전 찾아간 상태에 주는 경우 이전 지식을 바탕으로 환경을 제한한 영향을 크게 받는다.

환경의 끄트머리에 있을수록 더 빠른 경로가 있음에도 불구하고 해당 경로로 잘 가지 않는다.

8. imitation learning

이미 알고 있는 정보를 기반으로 초기 경로를 1 or 2번 주었을 경우 해당 경로를 중심으로 가지치기 하듯이 퍼져나간다.

정확한 정답을 줬을 경우와 근사한 경우, 잘못된 경우를 줬을 때 영향을 분석 중...

[강화학습 환경 체크1](https://www.youtube.com/watch?v=tk_b-34Y7To)
[강화학습 환경 체크2](https://www.youtube.com/watch?v=OtZJ-FVxorc)
[socket 통신 환경 체크](https://youtu.be/zsYEaa6q-fQ)
[PPO 학습](https://youtu.be/jJ6S70AD5BM)

학습 결과 시각화 예시

<img src="https://github.com/user-attachments/assets/c4e87482-2654-4153-b210-73d4ed3d9d6b" height="250"/>
<img src="https://github.com/user-attachments/assets/69f179ff-dde0-43fb-9799-9281b67c1a8c" height="250"/>



<br>

<br>

## 1. burnysc2 라이브러리로 환경 구성
### 1-1. 가스와 관련된 문제 해결
일꾼 수 인식 문제, 가스 짓는 중을 일하고 있는 것으로 인식한 문제, 가스로 채취를 안하는 문제

## 2. 프레임 단위로 PPO 알고리즘으로 학습
하지만 여러 프레임에서 실행되지 않는 명령이 많아 제대로 학습되었다고 판단하기 어려움!

## 3. 명령 단위로 학습 시도
### 3-0. 환경의 종료 조건
1. 테크수준 0인데 2,3을 하는 경우
2. 테크 수준 1인데 3을 하는 경우
3. 인구수가 부족한데 0,3을 하는 경우
4. 일꾼 수 제한 16의 2배를 넘는 데 0을 하는 경우
5. 앞서 명령 3이 목표 횟수만큼 나오지 않았는데 9를 하는 경우

1. action 0 : 인구수가 부족한 경우, 과충족인경우
2. action 2 : 테크수준 0인 경우
3. action 3 : 테크수준 1이하인 경우

### 3-1. Q-learning, 사전에 연구된 방식을 먼저 가이드라인으로 활용
질럿 2 목표 등 한 경우만 가능 (질럿 3 목표를 질럿 2 목표로 학습시켰을 때 효율 감소)
딥러닝으로 한 모델에서 여러 경우를 다 처리할 수 있게 시도

### 3-2. 다음 프레임의 예상 채취량 다변량 회귀분석으로 계산
강화학습의 입력 값의 차원을 축소

## 4. 중간 시점에서 새로운 명령을 기준으로 탐색 시도
첫 번째 명령 달성 후 다음 명령을 사용자가 할당하였을 때 현재 상태를 기반으로 탐색해 감

## * 감가율은 최종 보상을 4000(최종 iteration이 대체로 다름)으로 나눈 값에 현재 iteration을 곱한 값으로 가정!
