import numpy as np
import semiworld_render as render_helper


class SemiWorld:
    def __init__(self):
        self.action_space = [0, 1, 2, 3]  # 행동 공간(가능한 행동들)
        self.action_meaning = {  # 행동의 의미
            0: "worker",
            1: "pylon",
            2: "gate",
            3: "zealot",
        }
        self.reward_map = { #보상 설정, 여기에 없는 key로 접근시 모두 0
            (0, 1, 1, 2) : 835,
            (0, 1, 2, 2) : 832,
            (0, 1, 3, 2) : 725,
            (0, 2, 3, 2) : 732,
            (1, 1, 1, 2) : 832,
            (1, 1, 2, 2) : 816,
            (1, 1, 3, 2) : 726,
            (1, 2, 3, 2) : 736,
            (2, 1, 1, 2) : 832,
            (2, 1, 2, 2) : 816,
            (2, 1, 3, 2) : 742,
            (2, 2, 2, 2) : 822,
            (2, 2, 3, 2) : 736,
            (3, 1, 1, 2) : 833,
            (3, 1, 2, 2) : 818,
            (3, 1, 3, 2) : 747,
            (3, 2, 2, 2) : 832,
            (3, 2, 3, 2) : 741,
            (4, 1, 1, 2) : 837,
            (4, 1, 2, 2) : 816,
            (4, 1, 3, 2) : 756,
            (4, 2, 1, 2) : 846,
            (4, 2, 2, 2) : 818,
            (4, 2, 3, 2) : 751
        }

        #5인경우
        # self.reward_map = {
        #     (0, 1, 2, 5) : 833,
        #     (0, 1, 3, 5) : 740,
        #     (0, 2, 1, 5) : 1137,
        #     (0, 2, 2, 5) : 836,
        #     (0, 2, 3, 5) : 725,
        #     (1, 1, 1, 5) : 1142,
        #     (1, 1, 2, 5) : 834,
        #     (1, 1, 3, 5) : 726,
        #     (1, 2, 1, 5) : 1139,
        #     (1, 2, 2, 5) : 834,
        #     (1, 2, 3, 5) : 733,
        #     (2, 2, 1, 5) : 1136,
        #     (2, 2, 2, 5) : 834,
        #     (2, 2, 3, 5) : 736,
        #     (3, 2, 1, 5) : 1135,
        #     (3, 2, 2, 5) : 832,
        #     (3, 2, 3, 5) : 741,
        #     (4, 2, 1, 5) : 1138,
        #     (4, 2, 2, 5) : 823,
        #     (4, 2, 3, 5) : 751,
        #     }  # 보상 맵(각 좌표의 보상 값)
        
        # self.goal_state = (0, 3)    # 목표 상태(좌표)
        # self.wall_state = (1, 1)    # 벽 상태(좌표)
        self.start_state = (0, 0, 0, 0)   # 시작 상태(좌표)
        self.agent_state = self.start_state   # 에이전트 초기 상태(좌표)

        self.sim_list = {}
        for a in range(5): #일꾼
            for b in range(2): #파일런
                for c in range(3): #게이트
                    for d in range(3): #질럿    
                        self.sim_list[(a,b,c,d)] = (12+a+2*d, 15+8*b, 12+a, 1, 2 if c else 1 if b else 0, 0+c, 0+d)
        
        file_path = 'zelaot/flow-action/semi_sim/5__state_data.txt'
        with open(file_path, 'r') as file:
            for elem in file:
                self.state_data = dict(eval(elem))
                break

        self.one_hot = {0 : (0, 0, 0, 0)}
        self.find_one_hot = {(0, 0, 0, 0) : 0}
        cnt = 1
        for key, value in self.sim_list.items():
            if value in self.state_data:
                self.one_hot[cnt] = key
                self.find_one_hot[key] = cnt
                cnt += 1
        #값을 직접 보고 검증할 필요 존재(혹시 모를 양식 문제 해결)
        print(self.one_hot)
        print(self.find_one_hot)

        self.matrix = np.array([
            [0, 1, 2, -30, 3, -30, 4, -1],
            [-1, -1, -40, 5, -50, 6, -30, 7],

            [8, 9, 10, -30, 11, -30, 12, -1],
            [-1, -1, -40, 13, -50, 14, -30, 15],

            [16, 17, 18, -30, 19, -30, 20, -1],
            [-1, -1, -40, 21, -50, 22, -30, 23],

            [24, 25, 26, -30, 27, -30, 28, -1],
            [-1, -1, -40, 29, -50, 30, -30, 31],

            [-1, 32, 33, -30, 34, -30, 35, -1],
            [-1, -1, -40, 36, -50, 37, -30, 38]
            ])

        self.find_matrix = {}
        for num in range(39):
            for i in range(10): 
                for j in range(8):
                    if self.matrix[i][j] == num:
                        self.find_matrix[num] = (i,j)
        print("self.find_matrix\n", self.find_matrix)


    @property
    def height(self):
        return len(self.reward_map)

    @property
    def width(self):
        return len(self.reward_map[0])

    @property
    def shape(self):
        return self.reward_map.shape

    def actions(self):
        return self.action_space

    def states(self):
        for h in range(self.height):
            for w in range(self.width):
                yield (h, w)

    def next_state(self, state, action):
        # 이동 위치 계산
        next_state = list(state)
        next_state[action] += 1

        next_state = tuple(next_state)

        if next_state not in self.sim_list:
            next_state = None
        elif next_state in self.sim_list and self.sim_list[next_state] not in self.state_data:
            next_state = None
        # else:
        #     print("정상")
        # action_move_map = [(-1, 0), (1, 0), (0, -1), (0, 1)]
        # move = action_move_map[action]
        # next_state = (state[0] + move[0], state[1] + move[1])
        # ny, nx = next_state

        # 이동한 위치가 그리드 월드의 테두리 밖이나 벽인가?
        # if nx < 0 or nx >= self.width or ny < 0 or ny >= self.height:

        #     next_state = state
        # elif next_state == self.wall_state:
        #     next_state = state
        if next_state is not None:
            next_state = tuple(next_state)
        return next_state  # 다음 상태 반환

    def reward(self, state, action, next_state):
        # print(0 if next_state not in self.reward_map else self.reward_map[next_state])
        return 0 if next_state not in self.reward_map else np.exp(-0.01 * (self.reward_map[next_state]-1000))#self.reward_map[next_state]

    def reset(self):
        self.agent_state = self.start_state
        return self.agent_state

    def step(self, action):
        state = self.agent_state
        next_state = self.next_state(state, action)

        if next_state is None:
            reward = -1 #0시 최종보상을 못찾음
            done = True
        else:
            reward = self.reward(state, action, next_state)
            # done = (next_state == self.goal_state)
            done = True if next_state[-1] == 2 else False

        self.agent_state = next_state
        return next_state, reward, done

    def render_v(self, cnt, v=None, policy=None, print_value=True):
        #가능한 공간, 종료 시점, 불가능한 공간
        renderer = render_helper.Renderer(self.matrix, self.reward_map,
                                          self.one_hot, self.find_one_hot, self.find_matrix)
        renderer.render_v(cnt, v, policy, print_value)

    def render_q(self, cnt, q=None, print_value=True):
        renderer = render_helper.Renderer(self.matrix, self.reward_map,
                                          self.one_hot, self.find_one_hot, self.find_matrix)  
        renderer.render_q(cnt, q, print_value)