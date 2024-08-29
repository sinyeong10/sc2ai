#서버 강화학습 돌릴 컴퓨터 : 이거 먼저 실행되야 함!
from sys import stdin
import pickle
import sys
flag = 0
try:
    all_order = list(map(int, sys.argv[1].split()))
except:
    print("order이 전달되지 않음!")
    all_order = [0, 0, 0, 1, 0, 2, 2, 2, 3, 1, 3, 3, 3, 1, 3, 1,9]#[0,0,1,2,2,3,3,1,3,3,3,9]
    # sys.exit()
cnt = 0
user_order = False

log = [[], []]

def make_order(user_ans):
    #전송 flag, 명령의 순서, 명령
    order = {"flag":0, "idx":0, "action":user_ans}

    # print("user order :", order)

    with open("./socket_order.pkl", "wb") as f:
        pickle.dump(order, f)

data = {'state': [0, 0, 0, 0, 0, 0, 0, 0, 0, 0], 'reward': 0, 'action': None, 'done': False}  # empty action waiting for the next one!
with open('state_rwd_action.pkl', 'wb') as f:
    # Save this dictionary as a file(pickle)
    pickle.dump(data, f)
# print("초기화 : ", data)

import socket

# 서버 소켓 생성
server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

# 서버 주소와 포트 설정
server_address = ('172.30.1.43', 12345)  # 모든 네트워크 인터페이스에 바인딩
server_socket.bind(server_address)

# 클라이언트 연결을 기다림
server_socket.listen(1)
print("서버가 시작되었습니다. 클라이언트 연결을 기다립니다...")

import subprocess
if flag == 0:
    subprocess.Popen(["python", 'zelaot/flow-action/semi_sim/incredibot-sct.py'])
else:
    subprocess.Popen(["python", 'zelaot/flow-action/semi_sim/4.semi_sim.py'])

# 클라이언트 연결 대기
client_socket, client_address = server_socket.accept()
print(f"클라이언트가 연결되었습니다.") # {client_address}

end_flag = False

first_check_flag = False #어느 시점에서 불가능한 경우를 처리할 지

while True:
    if user_order:
        print('사용자 명령을 입력해주세요')
        user_ans = int(stdin.readline())
        while user_ans not in [-1,0,1,2,3,4,5,6,7,8,9]:
            print('사용자 명령을 다시 입력해주세요')
            user_ans = int(stdin.readline())
    elif all_order:
        user_ans = all_order[cnt]
        cnt += 1
    else:
        print("명령을 받을 수단이 없당")
        
    if first_check_flag:
        if log[0].count(3) == 5:
                user_ans = 9
                print("완료, 마지막 명령")
                end_flag = True
        elif 1 not in log[0] and (user_ans == 2 or user_ans == 3):
            user_ans = -1
            print("필요건물 부족")
            end_flag = True
        elif 2 not in log[0] and user_ans == 3:
            user_ans = -1
            print("필요건물 부족")
            end_flag = True
        elif user_ans == 0 and log[0].count(0) >= 4:#+8:
            user_ans = -1
            print("일꾼 수 과충족")
            end_flag = True
        elif 12+log[0].count(0)+log[0].count(3)*2 >= 15+log[0].count(1)*8 and user_ans != 1:
            print(12+log[0].count(0)+log[0].count(3)*2 , 15+log[0].count(1)*8)
            user_ans = -1
            print("인구수 부족")
            end_flag = True
    

    # print("do something")
    make_order(user_ans)

    try:
        # order.pkl 파일 전송
        with open("socket_order.pkl", "rb") as f:
            order_data = f.read()
        client_socket.sendall(order_data)
        # print("socket_order.pkl 파일을 클라이언트에게 성공적으로 전송하였습니다.")
    except Exception as e:
        print(f"전송 오류 발생: {e}")


    try:
        # state_rwd_action.pkl 파일 수신
        data = client_socket.recv(1024)
        with open("rev_state_rwd_action.pkl", "wb") as f:
            f.write(data)
        # print("rev_state_rwd_action.pkl 파일을 성공적으로 수신하였습니다.")
    except Exception as e:
        print(f"수신 오류 발생: {e}")

    with open("./rev_state_rwd_action.pkl", "rb") as f:
        rev_state_rwd_action = pickle.load(f)
    # print("rev_state :", rev_state_rwd_action)
    
    log[0].append(user_ans)
    log[1].append(rev_state_rwd_action)


    if rev_state_rwd_action['done'] or end_flag:
        # 클라이언트 소켓 닫기
        print(f"연결 종료")#{client_address}와의 
        client_socket.close()
        server_socket.close()
        break

# print(log)

if log[1][-1]["state"][-1] == 4001:
    raise ValueError

import datetime

# 오늘 날짜를 기준으로 파일명 생성
today = datetime.date.today()
if flag == 0:
    filename = f"5__full_log.txt"
else:
    filename = f"5__semi_log.txt"

# 데이터를 파일에 저장
with open(filename, 'a') as f:
    for elem in zip(log[0], log[1]):
        f.write(f"{elem}\n")
    f.write(f"\n")
# print(f"데이터가 {filename} 파일에 성공적으로 저장되었습니다.")
