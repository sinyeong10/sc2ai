file_path = "zelaot/flow-action/semi_sim/5__data.txt"
import numpy as np
state_data = {}
cnt = 0
tmp = []
best_data = [] #[float("inf"), 0, (-1)]
with open(file_path, 'r') as file:
    for line in file:
        if line == "\n":
            all_action = []
            for elem in tmp:
                all_action.append(elem[0])
            # print(all_action) #한 에피소드 단위 명령 집합
            # print(tmp) #한 에피소드 단위 모든 환경
            cal_value = tmp[-1][1]["state"][-1]
            end_reward = np.exp(-0.01 * (cal_value-1000)) #tmp[-1][1]["reward"]
            # print(end_reward) #한 에피소드 단위 최종 보상
            end_frame = tmp[-1][1]["state"][-1] +1
            # print(end_frame) #한 에피소드 단위 최종 프레임
            frame_value = end_reward/end_frame
            last_minaral = tmp[-1][1]["state"][0]

            best_data.append([end_frame, last_minaral, all_action])

            # #최고의 값만 보기
            # if best_data[0] > end_frame:
            #     best_data = (end_frame, last_minaral, all_action)
            # elif best_data[0] == end_frame and best_data[1] < last_minaral:
            #     best_data = (end_frame, last_minaral, all_action)

            for elem in tmp[:-1]: #마지막 9는 앞과 동일한 상태
                # print(elem) #(9, {'state': [735, 0, 24, 31, 14, 1, 2, 3, 5, 866], 'reward': 3.819043505366336, 'action': None, 'done': True})
                state = tuple(elem[1]["state"][2:9])
                frame = elem[1]["state"][9]
                frame += 1
                frame_elem = frame*frame_value
                reward = elem[1]["reward"]
                # print(state) #현재 처리하고 있는 상태 (12, 15, 12, 1, 0, 0, 0) 형식
                if state in state_data:
                    state_data[state].append((frame_elem,all_action,frame,end_frame, last_minaral))
                else:
                    state_data[state] = [(frame_elem,all_action,frame,end_frame, last_minaral)]
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
    if len(value)>=2:
        print(value[0], value[1])
    else:
        print(value[0])

with open('zelaot/flow-action/semi_sim/5__state_data.txt', 'w') as output_file:
    output_file.write(f"{state_data}")

best_data.sort(key = lambda x : (-x[0], x[1]))
for end_frame, last_minaral, all_action in best_data:
    print(end_frame, last_minaral, all_action)
print(best_data[0])
print(best_data[-1])