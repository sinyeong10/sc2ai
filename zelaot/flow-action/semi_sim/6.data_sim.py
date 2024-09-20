file_path = "zelaot/flow-action/semi_sim/5__data.txt"
import numpy as np
state_data = {}
cnt = 0
tmp = []
with open(file_path, 'r') as file:
    for line in file:
        if line == "\n":
            all_action = []
            for elem in tmp:
                all_action.append(elem[0])
            print(all_action)
            print(tmp)
            end_frame = tmp[-1][1]["state"][-1] +1
            #1. 지수함수로 보상 처리
            cal_value = tmp[-1][1]["state"][-1]
            # end_reward = np.exp(-0.01 * (cal_value-1000)) #tmp[-1][1]["reward"]
            # print(end_reward)
            # print(end_frame)
            # frame_value = end_reward/end_frame

            #2. #보상을 고정값으로
            end_reward = 100 * 5

            for elem in tmp[:-1]: #마지막 9는 앞과 동일한 상태
                state = tuple(elem[1]["state"][2:9])
                frame = elem[1]["state"][9]
                frame += 1
                # frame_elem = frame*frame_value #지수함수보상
                # frame_elem = end_reward * (0.99 ** frame) # frame을 명령의 횟수로 생각
                frame_elem = end_reward * (0.99 ** end_frame)
                reward = elem[1]["reward"]
                print(state)
                if state in state_data:
                    state_data[state].append((frame_elem,all_action,frame,end_frame))
                else:
                    state_data[state] = [(frame_elem,all_action,frame,end_frame)]
            cnt += 1
            tmp = []
        else:
            tmp.append(eval(line.strip()))

for state in state_data:
    state_data[state] = sorted(state_data[state], key=lambda x: x[0])

print("데이터 출력")
for key, value in state_data.items():
    # print(key, min(value), max(value))
    print(key)
    #key에 따른 가장 큰 가치를 출력, 여러개면 2개, 1개면 1개만 출력
    if len(value)>=2:
        print(value[0], value[1])
    else:
        print(value[0])

with open('zelaot/flow-action/semi_sim/5__state_data.txt', 'w') as output_file:
    output_file.write(f"{state_data}")