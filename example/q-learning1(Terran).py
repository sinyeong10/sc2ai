# 1. Create the Agent
import random
import math

# 배열(array) 및 행렬(matrix) 연산에 특화된 라이브러리
import numpy as np
# 데이터 분석에 널리 사용되는 라이브러리로, 테이블 형태의 데이터를 쉽게 다룰 수 있게
import pandas as pd

# base_agent 모듈은 StarCraft II 에이전트를 구현할 때 기본이 되는 클래스를 제공
from pysc2.agents import base_agent
# StarCraft II 게임 내에서 수행할 수 있는 다양한 액션들을 정의하고 있는 actions 모듈
from pysc2.lib import actions
# features 모듈은 StarCraft II 게임 환경에서의 다양한 특성(features)을 정의
from pysc2.lib import features

# 각 상수는 게임 내에서의 특정 행동을 나타내는 함수의 ID를 참조
# 에이전트가 특정 턴에서 아무런 액션도 취하지 않도록 함
_NO_OP = actions.FUNCTIONS.no_op.id
# 화면상의 특정 좌표에 있는 유닛이나 건물을 선택하는 액션을 통해 특정 유닛이나 건물에 명령을 내릴 수 있음
_SELECT_POINT = actions.FUNCTIONS.select_point.id
# Supply Depot라는 테란 건물을 지을 때 사용
_BUILD_SUPPLY_DEPOT = actions.FUNCTIONS.Build_SupplyDepot_screen.id
# Barracks"라는 테란 건물을 지을 때 사용
_BUILD_BARRACKS = actions.FUNCTIONS.Build_Barracks_screen.id
# Barracks에서 "Marine"이라는 유닛을 생산할 때 사용
_TRAIN_MARINE = actions.FUNCTIONS.Train_Marine_quick.id
# 화면상에 있는 모든 군대 유닛을 한 번에 선택하는 액션
_SELECT_ARMY = actions.FUNCTIONS.select_army.id
# 선택된 유닛들에게 미니맵의 특정 위치로 공격하라는 명령을 내리는 액션, 특히 먼 거리의 목표물을 공격할 때 유용
_ATTACK_MINIMAP = actions.FUNCTIONS.Attack_minimap.id

# 화면상의 각 셀(cell)이 어떤 플레이어에게 속하는지를 나타내는 값을 제공
# 이 값을 통해 유닛이나 건물이 자신의 것인지, 아군인지, 적군인지 또는 중립인지를 판별
# 반환되는 값은 보통 숫자로, 예를 들어 1이면 자신의 것, 2는 적군, 3은 아군 등으로 나타낼 수 있음
_PLAYER_RELATIVE = features.SCREEN_FEATURES.player_relative.index
# 화면상의 각 셀에 있는 유닛이나 건물의 타입을 나타내는 값을 제공
# 예를 들어, 테란의 SCV, 마린, 벌처 등 각 유닛과 건물은 고유의 타입 ID를 가짐
# 이 값을 통해 특정 위치에 어떤 유닛이나 건물이 있는지 확인
_UNIT_TYPE = features.SCREEN_FEATURES.unit_type.index
# 화면상의 각 셀이 어떤 플레이어의 ID에 해당하는지를 나타내는 값을 제공
# 여러 플레이어가 게임에 참여할 경우, 각 플레이어는 고유의 ID를 가지게 됨
# 이 값을 통해 특정 유닛이나 건물이 어떤 플레이어에게 속하는지를 정확하게 알 수 있음
_PLAYER_ID = features.SCREEN_FEATURES.player_id.index

# 상수는 플레이어 자신을 나타냄
_PLAYER_SELF = 1

# 테란 종족의 유닛 및 건물 유형의 ID를 정의
# 테란 종족의 특정 유닛 또는 건물을 나타내는 ID를 참조
_TERRAN_COMMANDCENTER = 18
_TERRAN_SCV = 45
_TERRAN_SUPPLY_DEPOT = 19
_TERRAN_BARRACKS = 21

# 두 상수는 액션(예: 유닛 생산)이 큐에 들어갔는지의 여부를 나타냄
_NOT_QUEUED = [0]
_QUEUED = [1]

# Skip
class SmartAgent(base_agent.BaseAgent):
    def transformLocation(self, x, x_distance, y, y_distance):
        if not self.base_top_left:
            return [x - x_distance, y - y_distance]

        return [x + x_distance, y + y_distance]

    def step(self, obs):
        super(SmartAgent, self).step(obs)

        player_y, player_x = (obs.observation['minimap'][_PLAYER_RELATIVE] == _PLAYER_SELF).nonzero()
        self.base_top_left = 1 if player_y.any() and player_y.mean() <= 31 else 0

        return actions.FunctionCall(_NO_OP, [])

    # add the Q-Learning table class
    # Stolen from https://github.com/MorvanZhou/Reinforcement-learning-with-tensorflow

# 클래스는 Q-러닝 알고리즘을 구현
class QLearningTable:
    # 초기화 함수를 정의()
    def __init__(self, actions, learning_rate=0.01, reward_decay=0.9, e_greedy=0.9):
        # 가능한 행동의 목록: 게임에서 움직일 수 있는 방향이나 취할 수 있는 행동 등
        self.actions = actions
        # Q 값의 업데이트에 사용되는 학습률, 이 값은 0과 1 사이에 있으며, 업데이트 시 얼마나 크게 값을 변경할지를 결정
        self.lr = learning_rate
        # 감쇠율(또는 할인율), 미래의 보상을 현재의 Q 값에 얼마나 큰 가중치로 반영할지 결정하는 값
        self.gamma = reward_decay
        # 입실론 그리디 정책에서 사용되는 입실론 값, 값은 0과 1 사이에 있으며, 에이전트가 탐험을 할 확률을 나타냄
        self.epsilon = e_greedy
        # Q 테이블을 pandas DataFrame으로 초기화, 테이블은 상태와 행동을 기반으로 Q 값을 저장하고 조회하는 데 사용, 각 열(column)은 가능한 행동을 나타내며, 초기에는 비어 있음
        self.q_table = pd.DataFrame(columns=self.actions, dtype=np.float64)

    # 주어진 상태를 기반으로 에이전트가 취할 액션을 선택하는 함수
    # 이 메서드는 현재 상태와 입실론 그리디 정책을 기반으로, 무작위 탐험 또는 최적의 액션 선택 사이에서 어떤 액션을 취할지 결정
    # Q-Learning에서 이러한 액션 선택 방식은 학습 도중 다양한 경험을 축적하고 최적의 전략을 발견
    # observation: 현재의 상태를 나타내는 값
    def choose_action(self, observation):
        # 현재 상태(observation)가 Q 테이블에 존재하는지 확인하는 메서드를 호출, 만약 상태가 Q 테이블에 존재하지 않으면, 그 상태를 Q 테이블에 추가
        self.check_state_exist(observation)

        # Epsilon-greedy 정책을 사용하여 액션을 선택
        # np.random.uniform() 함수는 0과 1 사이의 무작위 실수를 반환, 값이 self.epsilon보다 작으면, 가장 큰 Q 값에 해당하는 액션(최적의 액션)을 선택, 그렇지 않으면 무작위 액션을 선택
        if np.random.uniform() < self.epsilon:
            # 현재 상태에 해당하는 모든 액션의 Q 값을 가져옴(.ix는 오래된 버전의 pandas에서 사용되었으므로, 최신 버전에서는 .loc나 .iloc를 사용하는 것이 좋음)
            state_action = self.q_table.ix[observation, :]

            # Q 값이 동일한 여러 액션 중에서 무작위로 하나를 선택하기 위해 인덱스를 재정렬
            state_action = state_action.reindex(np.random.permutation(state_action.index))
            # 가장 큰 Q 값에 해당하는 액션의 인덱스를 가져옴
            action = state_action.idxmax()
        else:
            # 가능한 액션 중에서 무작위로 하나를 선택
            action = np.random.choice(self.actions)

        return action

    # Q-러닝 알고리즘을 사용하여 학습하는 함수
    # s: 현재 상태 (state)
    # a: 현재 상태에서 취한 행동 (action)
    # r: 행동 a를 취한 후 받은 보상 (reward)
    # s_: 행동 a를 취한 후 도달한 다음 상태 (next state)
    def learn(self, s, a, r, s_):
        # 현재 상태와 다음 상태가 Q 테이블에 존재하는지 확인하고, 없으면 추가
        # 이는 Q 테이블을 동적으로 확장하면서 알려지지 않은 상태들에 대한 학습이 가능하게 함
        self.check_state_exist(s_)
        self.check_state_exist(s)
        # 현재 상태 s에서 액션 a를 취할 때의 예측된 Q 값
        q_predict = self.q_table.ix[s, a]
        # 실제 Q 값의 타겟(목표)은 주어진 보상 r에 다음 상태 s_에서 가능한 모든 액션 중 최대 Q 값에 할인율 gamma를 곱한 값
        q_target = r + self.gamma * self.q_table.ix[s_, :].max()

        # 예측된 Q 값(q_predict)과 타겟 Q 값(q_target) 사이의 차이를 학습률(lr)로 조정하여 현재 상태와 액션에 대한 Q 값을 업데이트
        # 이 차이가 크면 큰 폭으로 Q 값을 조정하게 되며, 차이가 작으면 작은 폭으로 조정
        self.q_table.ix[s, a] += self.lr * (q_target - q_predict)

    # 주어진 상태(state)가 Q-테이블에 존재하는지 확인하고, 존재하지 않으면 해당 상태를 Q-테이블에 추가하는 함수
    # 하나의 매개변수, 즉 확인하고자 하는 state를 받음
    def check_state_exist(self, state):
        # q_table의 인덱스를 사용하여 주어진 state가 Q-테이블에 존재하는지 확인합니다. 만약 존재하지 않으면, 다음 코드를 실행하여 새로운 상태를 추가
        if state not in self.q_table.index:
            # 주어진 state를 Q-테이블에 추가
            self.q_table = self.q_table.append(
                # 새로운 시리즈 객체를 생성, 이때, 각 액션에 대한 Q 값은 초기에 0으로 설정. 시리즈의 인덱스는 Q-테이블의 컬럼과 동일하며, 시리즈의 이름은 주어진 state로 설정
                pd.Series([0] * len(self.actions), index=self.q_table.columns, name=state))


# 2. Define the Actions
# 에이전트가 수행할 수 있는 액션들을 정의
ACTION_DO_NOTHING = 'donothing'
ACTION_SELECT_SCV = 'selectscv'
ACTION_BUILD_SUPPLY_DEPOT = 'buildsupplydepot'
ACTION_BUILD_BARRACKS = 'buildbarracks'
ACTION_SELECT_BARRACKS = 'selectbarracks'
ACTION_BUILD_MARINE = 'buildmarine'
ACTION_SELECT_ARMY = 'selectarmy'
ACTION_ATTACK = 'attack'

# 액션 리스트를 정의
smart_actions = [
    ACTION_DO_NOTHING,
    ACTION_SELECT_SCV,
    ACTION_BUILD_SUPPLY_DEPOT,
    ACTION_BUILD_BARRACKS,
    ACTION_SELECT_BARRACKS,
    ACTION_BUILD_MARINE,
    ACTION_SELECT_ARMY,
    ACTION_ATTACK,
]

# 에이전트의 step 함수를 정의
# 함수는 주어진 관측(observation)에 기반하여 어떤 액션을 수행할 것인지 결정하고, 해당 액션을 반환
def step(self, obs):
    super(SmartAgent, self).step(obs)

    # 플레이어 위치 파악
    # 주어진 관측(observation)에서 미니맵 정보 중에서 플레이어와 관련된 부분(_PLAYER_RELATIVE)을 추출
    # == _PLAYER_SELF를 사용하여 플레이어 자신의 위치를 미니맵에서 확인
    # .nonzero() 메소드는 해당 조건에 만족하는 위치의 좌표를 반환. 따라서 player_y와 player_x에는 플레이어 자신의 유닛이나 건물이 위치하는 y좌표와 x좌표들이 저장
    player_y, player_x = (obs.observation['minimap'][_PLAYER_RELATIVE] == _PLAYER_SELF).nonzero()
    # 기지 위치 확인
    # player_y.any()는 player_y 배열 내에 어떤 값이라도 있는지 확인. 이는 플레이어 자신의 유닛이나 건물이 화면 내에 존재하는지 확인하는 데 사용
    # player_y.mean() <= 31은 플레이어의 유닛이나 건물들의 평균 y 좌표가 31보다 작거나 같은지 확인. 이 값은 화면의 중앙 y 좌표를 기준으로 사용
    # 따라서, 이 로직은 플레이어의 기지가 맵의 왼쪽 상단에 위치하는지 확인하는 데 사용
    self.base_top_left = 1 if player_y.any() and player_y.mean() <= 31 else 0

    # 무작위 액션 선택
    # smart_actions 리스트에서 가능한 액션 중 무작위로 하나를 선택
    # random.randrange(0, len(smart_actions) - 1)를 사용하여 가능한 액션의 인덱스 범위 내에서 무작위로 인덱스를 선택. 선택된 인덱스의 액션이 smart_action에 할당
    smart_action = smart_actions[random.randrange(0, len(smart_actions) - 1)]

    # 아무 것도 하지 않기
    # 만약 선택된 액션이 ACTION_DO_NOTHING이라면, _NO_OP (No Operation)이라는 행동을 반환. 즉, 이 행동은 아무런 동작도 수행하지 않음
    if smart_action == ACTION_DO_NOTHING:
        return actions.FunctionCall(_NO_OP, [])

    # SCV 선택하기
    # 이 분기는 smart_action이 ACTION_SELECT_SCV일 때 실행. 이는 게임 내에서 SCV 유닛을 선택하려는 액션을 나타냄.
    # 첫 번째로, 현재 화면에서의 모든 유닛의 유형을 unit_type 변수에 저.
    # 두 번째로, 해당 유닛 유형 중에서 테란의 SCV 유닛(_TERRAN_SCV)의 위치를 찾음. .nonzero() 메소드는 SCV 유닛의 y좌표와 x좌표를 반환
    elif smart_action == ACTION_SELECT_SCV:
        unit_type = obs.observation['screen'][_UNIT_TYPE]
        unit_y, unit_x = (unit_type == _TERRAN_SCV).nonzero()

        # 만약 SCV 유닛이 화면에 존재한다면 (unit_y.any()), SCV의 y좌표 중에서 무작위로 하나의 y좌표를 선택
        # 그 후, 선택된 y좌표에 해당하는 x좌표와 함께 target 변수에 SCV의 위치를 저장
        # 마지막으로, _SELECT_POINT 동작을 반환하고, 선택할 대상의 위치를 target으로 지정. _NOT_QUEUED는 해당 동작이 다른 동작들에 추가되지 않고 바로 실행되도록 함
        if unit_y.any():
            i = random.randint(0, len(unit_y) - 1)
            target = [unit_x[i], unit_y[i]]

            return actions.FunctionCall(_SELECT_POINT, [_NOT_QUEUED, target])
        # 결과적으로, 이 코드는 선택된 액션에 따라 게임 내에서 아무 동작도 하지 않거나, 무작위로 SCV를 선택하는 동작을 수행

    # smart_action이 ACTION_BUILD_SUPPLY_DEPOT (즉, 공급 저장소를 건설하는 액션)일 경우 실행되는 로직
    elif smart_action == ACTION_BUILD_SUPPLY_DEPOT:
        # 공급 저장소 건설 가능성 확인
        # 현재 가능한 액션들 중에서 공급 저장소 건설 액션이 포함되어 있는지 확인. 만약 건설이 가능하지 않다면 (예: 자원 부족, 기타 조건 미충족 등), 이 분기는 실행되지 않음
        if _BUILD_SUPPLY_DEPOT in obs.observation['available_actions']:
            # 테란 커맨드 센터 위치 확인
            # 공급 저장소를 건설하기 위해 테란 커맨드 센터 (즉, 기본 건물)의 위치를 확인
            # unit_type 변수에 현재 화면의 모든 유닛 유형을 저장하고, 이 중에서 테란 커맨드 센터의 위치를 unit_y와 unit_x에 저장
            unit_type = obs.observation['screen'][_UNIT_TYPE]
            unit_y, unit_x = (unit_type == _TERRAN_COMMANDCENTER).nonzero()

            # 공급 저장소 건설 위치 결정
            # 만약 테란 커맨드 센터가 화면 내에 존재한다면, 공급 저장소를 건설할 위치를 결정합니다.
            # self.transformLocation 함수를 사용하여 건설 위치를 결정하는데, 이 함수는 커맨드 센터의 평균 x 좌표와 y 좌표를 기준으로 일정한 거리를 떨어진 위치에 건설하도록 함
            # 여기서는 x 좌표는 그대로 유지하고, y 좌표는 평균 y 좌표에서 20만큼 아래쪽에 건설하도록 위치를 조정
            if unit_y.any():
                target = self.transformLocation(int(unit_x.mean()), 0, int(unit_y.mean()), 20)
                # 공급 저장소 건설 액션 반환
                # 최종적으로, 결정된 건설 위치 (target)를 사용하여 공급 저장소 건설 액션을 반환
                # _NOT_QUEUED는 해당 동작이 다른 동작들에 추가되지 않고 바로 실행되도록 험
                return actions.FunctionCall(_BUILD_SUPPLY_DEPOT, [_NOT_QUEUED, target])
        # 코드의 목적은, 가능한 경우에 테란 커맨드 센터 근처에 공급 저장소를 건설하는 것

    # smart_action이 ACTION_BUILD_BARRACKS일 경우 실행되는 로직
    elif smart_action == ACTION_BUILD_BARRACKS:
        # BARRACKS 건설 가능성 확인
        # 현재 가능한 액션들 중에서 병영 건설 액션이 포함되어 있는지 확인
        # 만약 건설이 가능하지 않다면 (예: 자원 부족, 기타 조건 미충족 등), 이 분기는 실행되지 않음
        if _BUILD_BARRACKS in obs.observation['available_actions']:
            # 테란 커맨드 센터 위치 확인
            # BARRACKS을 건설하기 위해 테란 커맨드 센터 (즉, 기본 건물)의 위치를 확인합니다.
            # unit_type 변수에 현재 화면의 모든 유닛 유형을 저장하고, 이 중에서 테란 커맨드 센터의 위치를 unit_y와 unit_x에 저장
            unit_type = obs.observation['screen'][_UNIT_TYPE]
            unit_y, unit_x = (unit_type == _TERRAN_COMMANDCENTER).nonzero()

            # BARRACKS 건설 위치 결정
            # 만약 테란 커맨드 센터가 화면 내에 존재한다면, 병영을 건설할 위치를 결정합니다.
            # self.transformLocation 함수를 사용하여 건설 위치를 결정하는데, 이 함수는 커맨드 센터의 평균 x 좌표와 y 좌표를 기준으로 일정한 거리를 떨어진 위치에 건설하도록 함
            # 여기서는 x 좌표를 평균 x 좌표에서 20만큼 오른쪽에, y 좌표는 그대로 유지하면서 건설하도록 위치를 조정
            if unit_y.any():
                target = self.transformLocation(int(unit_x.mean()), 20, int(unit_y.mean()), 0)
                # BARRACKS 건설 액션 반환
                # 최종적으로, 결정된 건설 위치 (target)를 사용하여 병영 건설 액션을 반환
                # _NOT_QUEUED는 해당 동작이 다른 동작들에 추가되지 않고 바로 실행되도록 함
                return actions.FunctionCall(_BUILD_BARRACKS, [_NOT_QUEUED, target])

    # smart_action이 ACTION_SELECT_BARRACKS일 경우 실행되는 로직. Barracks을 선택하는 동작을 수행
    elif smart_action == ACTION_SELECT_BARRACKS:
        # BARRACKS 위치 확인
        # 화면에 표시된 모든 유닛의 유형을 unit_type 변수에 저장
        # unit_y와 unit_x 변수에는 _TERRAN_BARRACKS의 y좌표와 x좌표가 각각 저장
        unit_type = obs.observation['screen'][_UNIT_TYPE]
        unit_y, unit_x = (unit_type == _TERRAN_BARRACKS).nonzero()

        # BARRACKS 선택 위치 결정
        # 화면 내에 BARRACKS이 존재하는 경우 (unit_y.any()가 참인 경우), BARRACKS을 선택하기 위한 목표 위치(target)를 결정
        # 여기서는 화면 내에 존재하는 모든 병영의 평균 x 좌표와 y 좌표를 사용하여 선택할 BARRACKS의 대략적인 위치를 결정
        if unit_y.any():
            target = [int(unit_x.mean()), int(unit_y.mean())]
            # BARRACKS 선택 액션 반환
            # 결정된 위치 (target)를 사용하여 BARRACKS 선택 액션을 반환. _NOT_QUEUED는 해당 동작이 다른 동작들에 추가되지 않고 바로 실행되도록 함
            return actions.FunctionCall(_SELECT_POINT, [_NOT_QUEUED, target])
    # 코드의 목적은 화면 내에 존재하는 BARRACKS 중 하나를 선택하는 것. 평균 좌표를 사용하는 것은 화면 내에 여러 개의 BARRACKS이 있을 경우, 중앙에 위치한 BARRACKS을 대상으로 하기 위함

    # smart_action 값에 따라 다른 행동을 수행
    # MARINE 생성
    # smart_action이 MARINE 생성을 나타내는 ACTION_BUILD_MARINE이면서, 해당 행동이 가능한 액션 중 하나인 경우 (_TRAIN_MARINE in obs.observation['available_actions']), BARRACK에서 MARINE을 생산하는 명령을 반환
    # 여기서 _QUEUED는 해당 동작을 다른 동작들 뒤에 추가하여 순차적으로 실행되도록 합
    elif smart_action == ACTION_BUILD_MARINE:
        if _TRAIN_MARINE in obs.observation['available_actions']:
            return actions.FunctionCall(_TRAIN_MARINE, [_QUEUED])

    # 전체 군대 선택 (ACTION_SELECT_ARMY)
    # smart_action이 전체 군대 선택을 나타내는 ACTION_SELECT_ARMY이면서, 해당 행동이 가능한 액션 중 하나인 경우, 전체 군대를 선택하는 명령을 반환
    elif smart_action == ACTION_SELECT_ARMY:
        if _SELECT_ARMY in obs.observation['available_actions']:
            return actions.FunctionCall(_SELECT_ARMY, [_NOT_QUEUED])

    # 공격 (ACTION_ATTACK)
    # smart_action이 공격을 나타내는 ACTION_ATTACK이면서, 해당 행동이 가능한 액션 중 하나인 경우, 군대에게 미니맵 상의 특정 위치로 공격하라는 명령을 반환
    # 여기서 self.base_top_left는 플레이어의 기지 위치가 미니맵의 좌측 상단에 있는지 나타내는 플래그. 해당 플래그 값에 따라 공격할 목표 위치가 결정
    elif smart_action == ACTION_ATTACK:
        if _ATTACK_MINIMAP in obs.observation["available_actions"]:
            if self.base_top_left:
                return actions.FunctionCall(_ATTACK_MINIMAP, [_NOT_QUEUED, [39, 45]])

            return actions.FunctionCall(_ATTACK_MINIMAP, [_NOT_QUEUED, [21, 24]])

    # 위의 모든 조건들 중 어느 것에도 해당되지 않는 경우, 아무 행동도 하지 않는 _NO_OP을 반환
    return actions.FunctionCall(_NO_OP, [])


# add the Q-Learning table
# Q-러닝 테이블을 초기화하는 함수를 정의
def __init__(self):
    super(SmartAgent, self).__init__()

    self.qlearn = QLearningTable(actions=list(range(len(smart_actions))))


# 3. Define the State
# 에이전트의 상태를 정의하는 함수
def step(self, obs):
    super(SmartAgent, self).step(obs)

    # 미니맵에서의 플레이어 위치 정보, _PLAYER_SELF 값에 해당하는 위치를 찾아서 좌표를 가져옴
    player_y, player_x = (obs.observation['minimap'][_PLAYER_RELATIVE] == _PLAYER_SELF).nonzero()
    # 플레이어의 기지가 미니맵의 좌측 상단에 위치하는지의 여부
    self.base_top_left = 1 if player_y.any() and player_y.mean() <= 31 else 0

    # 현재 화면에 표시되는 유닛의 타입 정보
    unit_type = obs.observation['screen'][_UNIT_TYPE]

    # 공급 디포의 위치 정보. _TERRAN_SUPPLY_DEPOT 값에 해당하는 위치를 찾아서 좌표를 가져옴
    depot_y, depot_x = (unit_type == _TERRAN_SUPPLY_DEPOT).nonzero()
    # 공급 디포의 유무를 나타냄
    supply_depot_count = 1 if depot_y.any() else 0

    # barracks의 위치 정보. _TERRAN_BARRACKS 값에 해당하는 위치를 찾아서 좌표를 가져옴
    barracks_y, barracks_x = (unit_type == _TERRAN_BARRACKS).nonzero()
    # barracks의 유무
    barracks_count = 1 if barracks_y.any() else 0

    # 플레이어의 최대 공급량 정보
    supply_limit = obs.observation['player'][4]
    # 플레이어의 현재 군대 공급량 정보
    army_supply = obs.observation['player'][5]

    # 위에서 추출한 상태 정보를 배열로 만들어서 현재 상태를 정의
    current_state = [
        supply_depot_count,
        barracks_count,
        supply_limit,
        army_supply,
    ]

    # Q-learning 객체의 choose_action 함수를 사용하여 현재 상태에 대한 최적의 행동을 선택
    rl_action = self.qlearn.choose_action(str(current_state))
    smart_action = smart_actions[rl_action]
    # 주어진 관측(observation)을 바탕으로 현재 게임 상태를 판단하고, 해당 상태에서 수행해야 할 최적의 행동을 결정

# 4. Define the Rewards
# 리워드를 정의하는 상수를 설정
KILL_UNIT_REWARD = 0.2
KILL_BUILDING_REWARD = 0.5

# 에이전트의 초기화 함수를 정의
def __init__(self):
    super(SmartAgent, self).__init__()

    # Q-Learning 초기화
    # QLearningTable 객체를 초기화하고 이를 self.qlearn에 할당. 가능한 모든 행동의 수만큼의 액션을 가진 Q-테이블이 생성
    self.qlearn = QLearningTable(actions=list(range(len(smart_actions))))

    # 점수 초기화
    # 이전 단계에서 죽인 유닛과 건물의 점수를 추적하기 위한 변수들을 초기화
    self.previous_killed_unit_score = 0
    self.previous_killed_building_score = 0

    # 보상 계산
    # 게임의 현재 상태(observation)에서 죽인 유닛과 건물의 점수를 가져옴.
    # 현재 상태의 게임 정보를 바탕으로 에이전트의 상태를 정의. 상태는 supply depot, barracks, supply limit, army supply의 수를 포함
    # 이전에 얻은 점수보다 현재 점수가 높다면, 보상을 증가. 이는 적 유닛 또는 건물을 파괴할 때마다 에이전트에게 보상을 제공
    killed_unit_score = obs.observation['score_cumulative'][5]
    killed_building_score = obs.observation['score_cumulative'][6]

    current_state = [
        supply_depot_count,
        barracks_count,
        supply_limit,
        army_supply,
    ]

    reward = 0

    if killed_unit_score > self.previous_killed_unit_score:
        reward += KILL_UNIT_REWARD

    if killed_building_score > self.previous_killed_building_score:
        reward += KILL_BUILDING_REWARD

    # 행동 선택
    # self.qlearn.choose_action(str(current_state)): 현재 상태를 기반으로 Q-테이블에서 최적의 행동을 선택
    # 선택된 행동을 smart_actions 리스트에서 찾아 smart_action에 할당
    rl_action = self.qlearn.choose_action(str(current_state))
    smart_action = smart_actions[rl_action]
    # 점수 업데이트
    self.previous_killed_unit_score = killed_unit_score
    self.previous_killed_building_score = killed_building_score
    # SmartAgent의 상태와 Q-러닝 객체를 초기화하고, 현재 게임 상태에서 얻은 점수를 바탕으로 보상을 계산하며, 이 보상을 사용하여 Q-테이블에서 최적의 행동을 선택

# 5. It’s Alive!
# 에이전트의 생명 주기와 관련된 코드
# 이전 상태와 액션을 추적
def __init__(self):
    super(SmartAgent, self).__init__()

    self.qlearn = QLearningTable(actions=list(range(len(smart_actions))))

    self.previous_killed_unit_score = 0
    self.previous_killed_building_score = 0
    # 이전의 행동 및 상태 초기화
    # 이전의 행동과 상태를 추적하기 위한 변수들을 초기화
    self.previous_action = None
    self.previous_state = None

    current_state = [
        supply_depot_count,
        barracks_count,
        supply_limit,
        army_supply,
    ]

    # Q-Learning 업데이트
    # 이전에 수행한 행동이 있는 경우만 Q-Learning 시스템을 업데이트
    if self.previous_action is not None:
        # 보상을 0으로 초기화
        reward = 0

        # 이전 단계에 비해 더 많은 유닛이나 건물을 파괴한 경우, 해당하는 보상을 추가
        if killed_unit_score > self.previous_killed_unit_score:
            reward += KILL_UNIT_REWARD

        if killed_building_score > self.previous_killed_building_score:
            reward += KILL_BUILDING_REWARD

        # Q-Learning 시스템을 이전 상태, 이전 행동, 계산된 보상, 그리고 현재 상태를 사용하여 업데이트
        self.qlearn.learn(str(self.previous_state), self.previous_action, reward, str(current_state))

    # 행동 선택
    # 현재 상태를 기반으로 Q-테이블에서 최적의 행동을 선택
    rl_action = self.qlearn.choose_action(str(current_state))
    # 선택된 행동을 smart_actions 리스트에서 찾아 smart_action에 할당
    smart_action = smart_actions[rl_action]

    # 이전 정보 업데이트
    self.previous_killed_unit_score = killed_unit_score
    self.previous_killed_building_score = killed_building_score
    self.previous_state = current_state
    self.previous_action = rl_action
    # 초기화 함수는 SmartAgent의 상태와 Q-러닝 객체를 초기화하며, 이전에 수행한 행동과 상태에 대한 정보를 사용하여 Q-Learning 시스템을 업데이트
    # 또한, 현재 상태를 바탕으로 다음에 수행할 행동을 선택하고, 이전의 정보를 현재의 정보로 업데이트

