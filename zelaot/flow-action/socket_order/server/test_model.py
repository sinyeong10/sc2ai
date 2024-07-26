from stable_baselines3 import PPO
from sc2env import Sc2Env


LOAD_MODEL = r"C:\sc2ai\models\sin_ppo\2.zip"
# Environment:
env = Sc2Env()
# env.reset()

# load the model:
model = PPO.load(LOAD_MODEL)


# Play the game:
obs = env.reset()
done = False
while not done:
    print(obs)
    action, _states = model.predict(obs)
    print(action)
    obs, rewards, dones, info = env.step(action)

