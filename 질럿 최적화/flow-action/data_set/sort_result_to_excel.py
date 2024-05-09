filename = "game_log-2024-05-09.txt"

order_speed = {}

with open(filename, 'r') as file:
    for line in file:
        tmp = line.split(":")
        key = tuple(map(int, tmp[0].strip("[] ").split(","))) #리스트는 키가 안됨!
        time = (tmp[1]+":"+tmp[2]).strip().split(",")
        # print(time)
        if key in order_speed:
            order_speed[key].append((int(time[1]), time[0]))
        else:
            order_speed[key]=[(int(time[1]), time[0])]

#다 기록 후 정렬
for key in order_speed.keys():
    order_speed[key].sort()

import pandas as pd

#가장 좋은 결과 기준으로 정렬
df = pd.DataFrame(sorted(order_speed.items(), key = lambda x : x[1][0]), columns=['Order', 'Time'])

# print(f"{filename[:-3]}xlsx")
df.to_excel(f"{filename[:-3]}xlsx", index=False)


