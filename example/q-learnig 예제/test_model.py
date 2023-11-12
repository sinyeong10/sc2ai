from stable_baselines3 import PPO
from sc2env import Sc2Env


LOAD_MODEL = r"C:\Users\User\Documents\GitHub\models\1647915989\2880000.zip"
# Environment:
env = Sc2Env()

# load the model:
model = PPO.load(LOAD_MODEL)


# Play the game:
obs = env.reset()
done = False
while not done:
    action, _states = model.predict(obs)
    obs, rewards, dones, info = env.step(action)
print("end")

# from stable_baselines3 import PPO
# from sc2env import Sc2Env
# import os

# LOAD_MODEL = "models/1647915989/2880000.zip"

# # Environment:
# env = Sc2Env()

# # Check if model exists, and if not, train and save one
# if not os.path.exists(LOAD_MODEL):
#     model = PPO("MlpPolicy", env, verbose=1)
#     model.learn(total_timesteps=200000)  # You can adjust this value
#     model.save(LOAD_MODEL)
# else:
#     # Load the model:
#     model = PPO.load(LOAD_MODEL, env)

# # Play the game:
# obs = env.reset()
# done = False
# while not done:
#     action, _states = model.predict(obs)
#     obs, rewards, dones, info = env.step(action)
