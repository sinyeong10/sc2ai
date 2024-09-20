base = (12, 15, 12, 1, 0, 0, 0)
sim_list = {}
for a in range(5): #일꾼
    for b in range(3): #파일런
        for c in range(4): #게이트
            for d in range(6): #질럿
                sim_list[(a,b,c,d)] = (12+a+2*d, 15+8*b, 12+a, 1, 2 if c else 1 if b else 0, 0+c, 0+d)
# print(sim_list)

file_path = 'zelaot/flow-action/semi_sim/5__state_data.txt'
with open(file_path, 'r') as file:
    for elem in file:
        state_data = dict(eval(elem))
        break
# print(state_data)

#[0,0,0,0]형식과 (12, 15, 12, 1, 0, 0, 0)환경을 매칭
cnt = 0
for elema, elemb in sim_list.items():
    cnt += 1
    # if (cnt < 100 or cnt > 200):
    #     continue
    # print(cnt, elema, elemb)
    if elemb[-1] != 2:
        continue
    try:
        # a = state_data[elemb]
        print(elema, state_data[elemb][-1][-1])
    except:
        # print(f"{elemb}가 없음")
        pass
    print()
#(22, 23, 12, 1, 2, 1, 5)
#마지막 값을 출력하는 기능인가?
#질럿 2의 마지막 프레임을 모두 출력하는 기능인듯?

def start(start_tuple):
    print("\n", start_tuple)
    if start_tuple[-1] >=5:
        print('목표 달성')
        return
    max_idx = -1
    max_value = -1
    for i in range(4):
        start_tuple[i] += 1
        if tuple(start_tuple) in sim_list:
            if sim_list[tuple(start_tuple)] in state_data:
                # state_max_value = max(state_data[sim_list[tuple(start_tuple)]])
                state_max_value = state_data[sim_list[tuple(start_tuple)]][-1]
                print(i, state_max_value)
                if max_value < state_max_value[0]:
                    max_idx = i
                    max_value = state_max_value[0]
            else:
                print(f"{i}, 0, {sim_list[tuple(start_tuple)]}가 없음")
        else:
            print(f"{i}, {tuple(start_tuple)}는 없음")
            # continue
        start_tuple[i]-=1
    if max_idx != -1:
        start_tuple[max_idx] += 1
        start(start_tuple)
    
start([0,0,0,0])
