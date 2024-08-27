file_path = "zelaot/flow-action/semi_sim/data.txt"

state_data = {}
cnt = 0
tmp = []
with open(file_path, 'r') as file:
    for line in file:
        if line == "\n":
            print(tmp)
            end_reward = 200 #tmp[-1][1]["reward"]
            print(end_reward)
            end_frame = tmp[-1][1]["state"][-1]
            print(end_frame)
            frame_value = end_reward/end_frame
            for elem in tmp:
                state = tuple(elem[1]["state"][2:9])
                frame = elem[1]["state"][9]*frame_value
                reward = elem[1]["reward"]
                print(state)
                if state in state_data:
                    state_data[state].append(frame)
                else:
                    state_data[state] = [frame]
            cnt += 1
            tmp = []
        else:
            tmp.append(eval(line.strip()))

print("데이터 출력")
for key, value in state_data.items():
    print(key, min(value), max(value))

with open('zelaot/flow-action/semi_sim/state_data.txt', 'w') as output_file:
    output_file.write(f"{state_data}")