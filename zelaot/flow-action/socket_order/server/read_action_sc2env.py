#강화학습 환경 설정
import gym
from gym import spaces
import numpy as np
import subprocess
import pickle
import time
import os

class Sc2Env(gym.Env):
    """Custom Environment that follows gym interface"""
    def __init__(self):
        super(Sc2Env, self).__init__()
        # Define action and observation space
        # They must be gym.spaces objects
        # Example when using discrete actions:
        self.action_space = spaces.Discrete(4)

        
        #[minerals, gas / population, max_population / number_of_workers, number_of_nexuses
        #/tech_level / number_of_gate, number_of_zealot / iteration]
        # 이산 변수 (0부터 n-1까지 범위)
        self.observation_space = spaces.MultiDiscrete([2001, 2001, 201, 201, 45, 3, 4, 10, 25, 4001])
        #Box(low=0, high=255,shape=(88, 96, 3), dtype=np.uint8) #(224, 224였음)
        


    def step(self, action):
        #액션 입력받는 부분

        print('사용자 명령을 입력해주세요')
        user_ans = action

        while user_ans not in [-1,0,1,2,3,4,5,6,7,8,9]:
            print('사용자 명령을 다시 입력해주세요')
            user_ans = action

        self.log[0].append(user_ans)

        #action을 알아서 오류처리
        if (user_ans != 3 and self.log[0].count(3) == 2) or self.log[0].count(3) >= 3: #현재 추가된 명령이 3이 아니면서 이전에 3을 2번 하여 목표달성한 경우
            print(user_ans, "완료, 마지막 명령")
            user_ans = 9
            self.end_flag = True
        elif 1 not in self.log[0] and (user_ans == 2 or user_ans == 3):
            print(user_ans, "필요건물 부족")
            user_ans = -1
            self.end_flag = True
        elif 2 not in self.log[0] and user_ans == 3:
            print(user_ans, "필요건물 부족")
            user_ans = -1
            self.end_flag = True
        elif user_ans == 0 and self.log[0].count(0) >= 4:#+8:
            print(user_ans, "일꾼 수 과충족")
            user_ans = -1
            self.end_flag = True
        elif 12+self.log[0].count(0)+self.log[0].count(3)*2 >= 15+self.log[0].count(1)*8 and user_ans != 1:
            print(12+self.log[0].count(0)+self.log[0].count(3)*2 , 15+self.log[0].count(1)*8)
            print(user_ans, "인구수 부족")
            user_ans = -1
            self.end_flag = True
        
        print("do something")
        self.make_order(user_ans)

        try:
            # order.pkl 파일 전송
            with open("socket_order.pkl", "rb") as f:
                order_data = f.read()
            self.client_socket.sendall(order_data)
            print("socket_order.pkl 파일을 클라이언트에게 성공적으로 전송하였습니다.")
        except Exception as e:
            print(f"전송 오류 발생: {e}")




        #상태를 반환받는 부분
        # waits for the new state to return (map and reward) (no new action yet. )
        
        try:
            # state_rwd_action.pkl 파일 수신
            data = self.client_socket.recv(1024)
            with open("rev_state_rwd_action.pkl", "wb") as f:
                f.write(data)
            print("rev_state_rwd_action.pkl 파일을 성공적으로 수신하였습니다.")
        except Exception as e:
            print(f"수신 오류 발생: {e}")

        try:
            with open("./rev_state_rwd_action.pkl", "rb") as f:
                rev_state_rwd_action = pickle.load(f)
            print("rev_state :", rev_state_rwd_action)

            self.log[1].append(rev_state_rwd_action)

        
        except Exception as e:
            print("파일을 못 읽음")
            map = [0,0,0,0,0,0,0,0,0,0] #np.zeros((88, 96, 3), dtype=np.uint8) #(224, 224였음)
            observation = map
            # if still failing, input an ACTION, 3 (scout)
            data = {"state": map, "reward": 0, "action": 0, "done": False}  # empty action waiting for the next one!
            with open('state_rwd_action.pkl', 'wb') as f:
                pickle.dump(data, f)

            state = map
            reward = 0
            done = False
            action = 0

        #반환 값 만듦
        state = rev_state_rwd_action['state']
        reward = rev_state_rwd_action['reward']
        done = rev_state_rwd_action['done']


        if rev_state_rwd_action['done'] or self.end_flag:
            # 클라이언트 소켓 닫기
            print(f"연결 종료")#{client_address}와의 
            self.client_socket.close()
            # self.server_socket.close()

            print(self.log)

            import datetime

            # 오늘 날짜를 기준으로 파일명 생성
            today = datetime.date.today()
            filename = f"log_{today}.txt"

            # 데이터를 파일에 저장
            with open(filename, 'a') as f:
                for elem in zip(self.log[0], self.log[1]):
                    f.write(f"{elem}\n")
                f.write(f"\n")
            print(f"데이터가 {filename} 파일에 성공적으로 저장되었습니다.")


        info ={}
        observation = state
        return observation, reward, done, info

    def reset(self):
        print("RESETTING ENVIRONMENT!!!!!!!!!!!!!")
        map = [0,0,0,0,0,0,0,0,0,0] #np.zeros((88, 96, 3), dtype=np.uint8) #(224, 224였음)
        observation = map
        data = {"state": map, "reward": 0, "action": None, "done": False}  # empty action waiting for the next one!
        with open('state_rwd_action.pkl', 'wb') as f:
            pickle.dump(data, f)
        # # run incredibot-sct.py non-blocking:
        # subprocess.Popen(['python3', r'zelaot\flow-action\socket_order\client\incredibot-sct.py'])
        
        self.server_set()
        return observation  # reward, done, info can't be included
        


    def make_order(self, user_ans):
        #전송 flag, 명령의 순서, 명령
        order = {"flag":0, "idx":0, "action":user_ans}

        print("user order :", order)

        with open("./socket_order.pkl", "wb") as f:
            pickle.dump(order, f)

    def server_set(self):
        #서버 강화학습 돌릴 컴퓨터
        # from sys import stdin
        import pickle

        self.log = [[], []]

        data = {'state': [0, 0, 0, 0, 0, 0, 0, 0, 0, 0], 'reward': 0, 'action': None, 'done': False}  # empty action waiting for the next one!
        with open('state_rwd_action.pkl', 'wb') as f:
            # Save this dictionary as a file(pickle)
            pickle.dump(data, f)
        print("초기화 : ", data)

        import socket

        # 서버 소켓 생성
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        # 서버 주소와 포트 설정
        server_address = ('172.30.1.45', 12345)  # 모든 네트워크 인터페이스에 바인딩
        server_socket.bind(server_address)

        # 클라이언트 연결을 기다림
        server_socket.listen(1)
        print("서버가 시작되었습니다. 클라이언트 연결을 기다립니다...")

        subprocess.Popen(['python3', r'zelaot\flow-action\socket_order\client\incredibot-sct.py'])

        # 클라이언트 연결 대기
        self.client_socket, self.client_address = server_socket.accept()
        print(f"클라이언트가 연결되었습니다.") # {client_address}

        self.end_flag = False