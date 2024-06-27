#서버 강화학습 돌릴 컴퓨터

from sys import stdin
import pickle

def make_order(user_ans):
    #전송 flag, 명령의 순서, 명령
    order = {"flag":0, "idx":0, "action":user_ans}

    print("user order :", order)

    with open("./socket_order.pkl", "wb") as f:
        pickle.dump(order, f)

make_order(0)

import socket

# 서버 소켓 생성
server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

# 서버 주소와 포트 설정
server_address = ('172.30.1.45', 12345)  # 모든 네트워크 인터페이스에 바인딩
server_socket.bind(server_address)

# 클라이언트 연결을 기다림
server_socket.listen(1)
print("서버가 시작되었습니다. 클라이언트 연결을 기다립니다...")

while True:
    # 클라이언트 연결 대기
    client_socket, client_address = server_socket.accept()
    print(f"클라이언트 {client_address}가 연결되었습니다.")
    
    try:
        # state_rwd_action.pkl 파일 수신
        data = client_socket.recv(1024)
        with open("rev_state_rwd_action.pkl", "wb") as f:
            f.write(data)
        print("rev_state_rwd_action.pkl 파일을 성공적으로 수신하였습니다.")
    except Exception as e:
        print(f"수신 오류 발생: {e}")


    with open("./rev_state_rwd_action.pkl", "rb") as f:
        rev_state_rwd_action = pickle.load(f)
    print("rev_state :", rev_state_rwd_action)

    if rev_state_rwd_action['done']:
        print("마지막 명령 실행")
        user_ans = 9
    else:
        print('사용자 명령을 입력해주세요')
        user_ans = int(stdin.readline())

    make_order(user_ans)
    print("do something")



    try:
        # order.pkl 파일 전송
        with open("socket_order.pkl", "rb") as f:
            order_data = f.read()
        client_socket.sendall(order_data)
        print("socket_order.pkl 파일을 클라이언트에게 성공적으로 전송하였습니다.")
    except Exception as e:
        print(f"전송 오류 발생: {e}")

    

    # 클라이언트 소켓 닫기
    print(f"{client_address}와의 연결 종료")
    client_socket.close()

    if rev_state_rwd_action['done']:
        server_socket.close()
        break