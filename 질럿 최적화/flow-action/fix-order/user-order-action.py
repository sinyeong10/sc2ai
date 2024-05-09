#0:일꾼 #12
#1:파일런 #18
#2:게이트 #46
#3:질럿 ZEALOT #27
#4:멀티 #71
#ex:코어 36, 차원관문 100 [11생산 20 대기], 가스 21
#9:end 의미!
order = [[1, 2, 2, 3, 3, 3, 9], [0, 1, 2, 2, 3, 3, 3, 9], [0, 0, 1, 2, 2, 3, 3, 3, 9]]

print(len(order))

import pickle

with open("./order.pkl", "wb") as f:
    pickle.dump(order, f)
