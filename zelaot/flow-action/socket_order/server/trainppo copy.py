from stable_baselines3 import PPO
import os
from read_action_sc2env import Sc2Env
import time
from wandb.integration.sb3 import WandbCallback
import wandb


model_name = "sin_ppo_1"#f"{int(time.time())}"

models_dir = f"models/{model_name}/"
logdir = f"logs/{model_name}/"


conf_dict = {"Model": "v19",
             "Machine": "Main",
             "policy":"MlpPolicy",
             "model_save_name": model_name}


run = wandb.init(
    project=f'SC2RLv6',
    entity="cbrnt1210",#"ericoh5050", #"sentdex",
    config=conf_dict,
    sync_tensorboard=True,  # auto-upload sb3's tensorboard metrics
    save_code=True,  # optional
)


if not os.path.exists(models_dir):
	os.makedirs(models_dir)

if not os.path.exists(logdir):
	os.makedirs(logdir)

env = Sc2Env()

try:
    model = PPO.load(r"models/sin_ppo_1/4.zip", env=env)
    print("모델 로드함")
except:
    model = PPO('MlpPolicy', env, verbose=1, tensorboard_log=logdir, n_steps=512, batch_size=8)
    print("모델 못 불러옴 새로 함")  

TIMESTEPS = 1 #10000
iters = 4
while iters < 8:
    print("\n\n\nOn iteration: ", iters)
    iters += 1
    model.learn(total_timesteps=TIMESTEPS, tb_log_name=f"PPO") #, reset_num_timesteps=False
    model.save(f"{models_dir}/{TIMESTEPS*iters}")
    env.forced_end()
    # env.end_flag = True

print("end")