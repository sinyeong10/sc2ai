base = (12, 15, 12, 1, 0, 0, 0)
sim_list = {}
for a in range(5):
    for b in range(3):
        for c in range(3):
            for d in range(4):
                sim_list[(a,b,c,d)] = (12+a+2*d, 15+8*b, 12+a, 1, 2 if c else 1 if b else 0, 0+c, 0+d)
# print(sim_list)

file_path = 'zelaot/flow-action/semi_sim/state_data.txt'
with open(file_path, 'r') as file:
    for elem in file:
        state_data = dict(eval(elem))
        break
# print(state_data)

def start(start_tuple):
    print("\n", start_tuple)
    # if start_tuple[-1] >=2:
    #     print('목표 달성')
    #     return
    max_idx = -1
    max_value = -1
    for i in range(4):
        start_tuple[i] += 1
        if tuple(start_tuple) in sim_list:
            if sim_list[tuple(start_tuple)] in state_data:
                state_max_value = max(state_data[sim_list[tuple(start_tuple)]])
                print(i, state_max_value)
                if max_value < state_max_value:
                    max_idx = i
                    max_value = state_max_value
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
