from sc2.bot_ai import BotAI  # parent class we inherit 
import numpy as np
import sys
import pickle

early_stop = 0
reward = 0

order = [0, 0, 0, 1, 0, 2, 2, 2, 1, 3, 3, 9]

finish_action = False
count = 0

data = {"state": map, "reward": reward, "action": None, "done": False}  # empty action waiting for the next one!
with open('flow_action.pkl', 'wb') as f:
    # Save this dictionary as a file(pickle)
    pickle.dump(data, f)

trycount = 0
class IncrediBot(BotAI): # inhereits from BotAI (part of BurnySC2)
    def make(self):
        global count
        global finish_action
        global trycount
        trycount += 1
        with open('flow_action.pkl', 'rb') as f:
            data = pickle.load(f)

        # action 값을 변경합니다.
        if finish_action:
            print(trycount, order[count])
            count += 1
        data['action'] = order[count]

        # 변경된 데이터를 파일에 저장합니다.
        with open('flow_action.pkl', 'wb') as f:
            pickle.dump(data, f)
            
        finish_action = False

a = IncrediBot()
while True:
    a.make()
    with open('flow_action.pkl', 'rb') as f:
        data = pickle.load(f)
    print(data["action"])
    if data["action"] == 9:
        break
    finish_action = True
print("end")


with open('flow_action.pkl', 'rb') as f:
    data = pickle.load(f)
    print(data)

print("finish")