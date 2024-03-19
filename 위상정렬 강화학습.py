import numpy as np
import networkx as nx

# 그리드 환경 생성
grid_size = (5, 5)
G = nx.DiGraph()  # 방향 그래프로 수정
G.add_nodes_from((i, j) for i in range(grid_size[0]) for j in range(grid_size[1]))
for i in range(grid_size[0]):
    for j in range(grid_size[1]):
        if i + 1 < grid_size[0]:
            G.add_edge((i, j), (i + 1, j))
        if j + 1 < grid_size[1]:
            G.add_edge((i, j), (i, j + 1))

# 시작 상태 및 목표 상태 설정
start_state = (0, 0)
goal_state = (4, 4)

# 위상 정렬 수행
topological_order = list(nx.topological_sort(G))

# 강화 학습 루프
current_state = start_state

while current_state != goal_state:
    next_action = None

    # 위상 정렬을 따라 행동 결정
    for state in topological_order:
        if state == current_state:
            neighbors = list(G.neighbors(state))
            # 무작위로 다음 행동 선택 (이 부분을 강화 학습 알고리즘으로 대체 가능)
            if neighbors:
                next_action = np.random.choice(neighbors)
            else:
                print("더 이상 이동할 수 있는 이웃이 없습니다.")
                break

    if next_action is None:
        break

    # 에이전트 이동
    current_state = next_action
    print("현재 위치:", current_state)

if current_state == goal_state:
    print("목표 지점에 도달!")
else:
    print("목표 지점에 도달하지 못했습니다.")
