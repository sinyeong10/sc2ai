from stable_baselines3 import DQN
from read_action_sc2env import Sc2Env


LOAD_MODEL = r"C:\sc2ai\models\sin_dqn_1\900.zip"
# Environment:
env = Sc2Env()
# env.reset()

# load the model:
model = DQN.load(LOAD_MODEL)

import time
import numpy as np
# Play the game:
obs = env.reset()
done = False
cnt = 0
while not done:
    cnt+=1
    print("\n\nindex :", cnt, obs, end=" / ")
    # time.sleep(1)
    if done:
        print(done)
        break
    obs = np.array(obs)
    action, _states = model.predict(obs)
    print(action, end=" / ")
    obs, rewards, done, info = env.step(int(action))
    print(obs, rewards, done, info)

print("testmodel_end")