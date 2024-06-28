#클라이언트 강화학습 환경 보낼 데이터

#0:일꾼 #12
#1:파일런 #18
#2:게이트 #46
#3:질럿 ZEALOT #27
#4:멀티 #71
#ex:코어 36, 차원관문 100 [11생산 20 대기], 가스 21
#9:end 의미!
#파일 전송시키라는 flag, 명령의 번째, 명령
import pickle

data = {"state": [0, 0, 0, 0, 0, 0, 0, 0], 'reward': 0, "action": None, "done": False}  # empty action waiting for the next one!
with open('state_rwd_action.pkl', 'wb') as f:
    # Save this dictionary as a file(pickle)
    pickle.dump(data, f)
print(data)

# 읽은 데이터 확인
print("state :", data)

def send_data():
    import socket

    # 클라이언트 소켓 생성
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    # 서버 주소와 포트 설정 (서버의 IP 주소와 포트 번호)
    server_address = ('172.30.1.45', 12345)  # 예시: 서버의 IP 주소와 포트 번호를 적절히 설정

    try:
        # 서버에 연결
        client_socket.connect(server_address)
        print("서버에 연결되었습니다.")

    except Exception as e:
        print(f"서버 연결 중 오류 발생: {e}")

    try:
        # order.pkl 파일 수신
        order_data = client_socket.recv(1024)
        with open("order.pkl", "wb") as f:
            f.write(order_data)
        print("order.pkl 파일을 서버로부터 성공적으로 수신하였습니다.")

        
        with open("./order.pkl", "rb") as f:
            order = pickle.load(f)
        print("order :", order)

        
        # state_rwd_action.pkl 파일 전송
        with open("state_rwd_action.pkl", "rb") as f:
            data = f.read()
        client_socket.sendall(data)
        print("state_rwd_action.pkl 파일을 서버에 성공적으로 전송하였습니다.")


    except Exception as e:
        print(f"오류 발생: {e}")

    finally:
        # 클라이언트 소켓 닫기
        client_socket.close()

send_flag = True
while send_flag:
    try:
        send_data()
        send_flag = False
    except:
        print("문제 발생")
