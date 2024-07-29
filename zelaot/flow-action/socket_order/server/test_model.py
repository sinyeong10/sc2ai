from stable_baselines3 import PPO
from read_action_sc2env import Sc2Env


LOAD_MODEL = r"C:\sc2ai\models\sin_ppo\2.zip"
# Environment:
env = Sc2Env()
# env.reset()

# load the model:
model = PPO.load(LOAD_MODEL)

import time
# Play the game:
obs = env.reset()
done = False
cnt = 0
while not done:
    cnt+=1
    print("\n\nindex :", cnt, obs, end=" / ")
    time.sleep(1)
    if done:
        print(done)
        break
    action, _states = model.predict(obs)
    print(action, end=" / ")
    obs, rewards, done, info = env.step(int(action))
    print(obs, rewards, done, info)

print("testmodel_end")