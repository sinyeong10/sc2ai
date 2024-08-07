### socket_order 방식 문제점
1. trainppo.py파일에서 model.learn이 끝나고 incredibot-sct인 가상환경 파일과 연결이 두절되는 문제
1-1. 일단 model.learn이 끝나는 시점에 다시 새로 학습가능하도록 해둠
1-2. total_timesteps기준이 아니라 total_timesteps이상이며 done이 True일때 학습이 종료되도록 해야지 중간 종료 학습 데이터가 안들어간다. (큰 영향이 있는 지는 n_steps단위라 이걸 크게하면 될 듯)

## 원인
# close()시 b""가 전달되어 socket 통신 간에 순서 문제 및 파일 읽기의 문제 발생!

### 진행과정
1. client/incredibot-bot.py파일이 가상환경
2. server/trainppo.py파일이 모델 학습
2-1. 해당 코드에서 env가 server/read_action_sc2env.py파일
2-2. 하나의 컴퓨터 처리시 server/read_action_sc2env.py파일에서 thread로 client/incredibot-bot.py파일을 실행시킴

### 학습 과정
s/t : server/trainppo.py
s/r : server.read_action_sc2env.py
c/i : client/incredibot-bot.py
1. s/t에서 env를 s/r로 실행하고 env.reset함
2. s/r {'state': [0, 0, 0, 0, 0, 0, 0, 0, 0, 0], 'reward': 0, 'action': None, 'done': False} state_rwd_action.pkl 생성
3. 서버 시작 클라이언트(가상환경) 연결 기다림
4. threading으로 c/i 실행
5. c/i {"state": [0,0,0,0,0,0,0,0,0,0], 'reward': 0, "action": None, "done": False} state_rwd_action.pkl 생성
6. c/i {'flag': 0, 'idx': 0, 'action': 0} order.pkl 생성
7. c/i 연결 order.pkl 파일 수신
8. model.learn에서 s/r step함수 실행
9. 입력 받은 명령의 조기 종료 조건 처리
10. s/r make_order로 socket_order.pkl 생성
11. s/r socket_order.pkl 전송
12. c/i 첫명령이 담긴 order.pkl 파일 수신
13. 게임 환경 실행
14. 
15. 



### 생산 최적화 함수 문제
# 문제가 발생하는 명령 순서 1 2 2 3 2 1 3 9
# 취소가 해당 프레임에 이뤄지지 않아서 자원이 100미만인 경우 생산을 하지 못함!
# 다음 프레임으로 넘겨야함...
# 매개 변수 추가해서 다음 프레임에서 처리
# 근데 다음 프레임에서 명령이 전달되는 경우 먼저 처리하지는 않는 지 체크가 필요
# finish_action가 self.make에서 True이면 다음 명령을 받아오는 구조이므로 일단 간단히 해당 함수 전에 처리