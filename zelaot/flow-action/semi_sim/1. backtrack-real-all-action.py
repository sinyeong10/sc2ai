#0:일꾼 #12
#1:파일런 #18
#2:게이트 #46
#3:질럿 ZEALOT #27
#4:멀티 #71
#ex:코어 36, 차원관문 100 [11생산 20 대기], 가스 21
#9:end 의미!

mineral_field = 8


order = []
tmp = []
def backtrack(idx, num_worker, num_pylon, num_gateway, num_jealot):
    if num_jealot == 2: #2마리 달성 목표!
        order.append(tmp[:]+[9])
        return
    
    # if idx >= 12: #컴퓨터 사양상 환경의 일부분만 먼저 체크
    #     print(tmp)
    #     return

    if num_worker < min(15 + num_pylon*8-2*num_jealot, mineral_field*2): #12/15로 시작! 일꾼수가 최대 인구수 보다 적거나, 2배수 이하인 경우에 생산
        tmp.append(0)
        backtrack(idx+1, num_worker+1, num_pylon, num_gateway, num_jealot)
        tmp.pop()
    
    #현재 인구수+한번에 추가 가능한 인구수 > 최대 인구수
    #동시에 실시하면 일꾼, 파일런, 질럿의 순서로 완료됨
    #처음 파일런 조건을 추가! 일꾼 3마리를 먼저 뽑지 않아도 됨!
    if num_pylon < 1:
        tmp.append(1) 
        backtrack(idx+1, num_worker, num_pylon+1, num_gateway, num_jealot)
        tmp.pop()

    if num_pylon >= 1 and num_gateway<2: #기지 기반자원 수급량으로 최대 5개까지 가능
        tmp.append(2)
        backtrack(idx+1, num_worker, num_pylon, num_gateway+1, num_jealot)
        tmp.pop()

    if num_gateway >= 1 and 15 + num_pylon*8-num_worker-num_jealot*2 >= 2: #게이트가 지어질 시 질럿 생산, 현재 인구수가 2이상일 시 질럿 생산
        tmp.append(3)
        backtrack(idx+1, num_worker, num_pylon, num_gateway, num_jealot+1)
        tmp.pop()

backtrack(0,12,0,0,0)
print(len(order))
# print(order)
for i, elem in enumerate(order):
    # if elem == [1, 2, 3, 3, 3, 2, 2, 1, 3, 3, 9]: #(12, 15, 12, 1, 2, 1, 0)
    # if i >= 4804:
    # if elem.count(1) == 2 and elem.count(2) >= 1:
    print(i, elem)
import pickle

with open("./all_order.pkl", "wb") as f:
    pickle.dump(order, f)
