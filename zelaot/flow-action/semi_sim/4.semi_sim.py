#현재 인구수, 최대 인구수, 일꾼 수, 넥서스 수, 테크 정도(넥서스, 파일런, 게이트), 게이트 수, 질럿 수
# base = [0,0,0,0,0,0,0]
base = [12,15,12,1,0,0,0]
#클라이언트 강화학습 환경 보낼 데이터
import numpy as np
import sys
import pickle
import time

def init_set():
    # print("c/i", "값 초기화")
    data = {"state": base, 'reward': 0, "action": None, "done": False}  # empty action waiting for the next one!
    with open('state_rwd_action.pkl', 'wb') as f:
        # Save this dictionary as a file(pickle)
        pickle.dump(data, f)
    # print("c/i", data)

    order = {"flag":0, "idx":0, "action":0}

    with open("./order.pkl", "wb") as f:
        pickle.dump(order, f)

    # print("c/i", "first order :", order)

init_set()
socket_flag = True
stop_flag = False

import socket

# 클라이언트 소켓 생성
client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

# 서버 주소와 포트 설정 (서버의 IP 주소와 포트 번호)
server_address = ('172.30.1.43', 12345)  # 예시: 서버의 IP 주소와 포트 번호를 적절히 설정

try:
    # 서버에 연결
    client_socket.connect(server_address)
    print("c/i", "서버에 연결되었습니다.")

except Exception as e:
    print("c/i", f"서버 연결 중 오류 발생: {e}")

def order_receive_state_send():
    global socket_flag
    global stop_flag
    reward = 0
    try:
        # print("c/i", "수신 대기")
        # order.pkl 파일 수신
        order_data = client_socket.recv(1024)
        with open("order.pkl", "wb") as f:
            f.write(order_data)
        # print("c/i", "처음으로 order.pkl 파일을 서버로부터 성공적으로 수신하였습니다.")
        
        with open("./order.pkl", "rb") as f:
            order_file = pickle.load(f)
        # print("c/i", "order :", order_file)
        order = order_file["action"]

    except Exception as e:
        print("c/i", f"처음 명령 수신 오류 발생: {e}")

    if base[6] == 5:
        stop_flag = True
        
    if order == 0:
        if base[1] < base[0]+1 or base[2]>=16:
            # order = -1
            stop_flag = True
        else:
            base[0] += 1
            base[2] += 1

    elif order == 1:
        base[1] += 8
        if base[4] == 0:
            base[4] = 1

    elif order == 2:
        if base[4] >= 1:
            base[5] += 1
            base[4] = 2 #이게 최종 테크라 관련 x
        else:
            # order = -1
            stop_flag = True

    elif order == 3:
        if base[4] == 2 and base[1]>=base[0]+2:
            base[0] += 2
            base[6] += 1
            reward = 100
        else:
            # order = -1
            stop_flag = True

    data = {"state": base, "reward": reward, "action": order, "done": False}  # empty action waiting for the next one!
    with open('state_rwd_action.pkl', 'wb') as f:
        pickle.dump(data, f)

    if order == 9 and stop_flag:
        order = None
    elif order == 9:
        print("error \n\n\n\n\n")
    if stop_flag:
        data = {"state": base, "reward": reward, "action": order, "done": True}  # empty action waiting for the next one!
        with open('state_rwd_action.pkl', 'wb') as f:
            pickle.dump(data, f)

    try:
        # state_rwd_action.pkl 파일 전송
        with open("state_rwd_action.pkl", "rb") as f:
            data = f.read()
        client_socket.sendall(data)
        # print("c/i", base, "state_rwd_action.pkl 파일을 서버에 성공적으로 전송하였습니다.")
    except Exception as e:
        print("c/i", f"상태 반환 안해주는 오류 발생: {e}")


    if stop_flag:
        # 클라이언트 소켓 닫기
        client_socket.close()
        print("c/i", "client 소켓 종료")
        socket_flag = False

while socket_flag:
    order_receive_state_send()

time.sleep(3)
sys.exit()