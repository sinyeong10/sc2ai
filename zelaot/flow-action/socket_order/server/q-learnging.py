import numpy as np
import pickle
with open("./rev_state_rwd_action.pkl", "rb") as f:
    rev_state_rwd_action = pickle.load(f)
print(rev_state_rwd_action)
data = rev_state_rwd_action

# Q 함수 초기화
num_actions = 9  # 0부터 8까지의 행동
Q = np.zeros((len(data['state']), num_actions))  # Q 함수 초기화 (예: 상태 특징의 길이에 따라 적절히 조정)

# Q-learning 파라미터
alpha = 0.1  # 학습률
gamma = 0.9  # 할인 계수

# 현재 상태
state = np.array(data['state'])

# Epsilon-greedy 정책을 통한 행동 선택
epsilon = 0.1  # 탐험 비율

if np.random.rand() < epsilon:
    # 랜덤하게 행동 선택 (탐험)
    action = np.random.randint(num_actions)
else:
    # Q 값이 가장 높은 행동 선택 (이용)
    action = np.argmax(Q[state])

# 선택한 행동 수행 (이 예시에서는 간단하게 랜덤으로 선택)
reward = 0  # 보상은 임의로 설정 (실제 환경에서는 환경에서 받아와야 함)

# Q 함수 업데이트
next_state = np.array(data['state'])  # 다음 상태 (이 예시에서는 동일한 상태로 가정)
Q[state, action] += alpha * (reward + gamma * np.max(Q[next_state]) - Q[state, action])

# 결과 출력
print("Selected action:", action)
print("Updated Q values:", Q)
