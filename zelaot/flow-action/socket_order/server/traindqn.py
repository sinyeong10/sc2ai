from stable_baselines3 import DQN
import os
from read_action_sc2env import Sc2Env
import time
from wandb.integration.sb3 import WandbCallback
import wandb

model_name = "sin_dqn_min_action"#f"{int(time.time())}"

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
    model = DQN.load(r"models\sin_dqn_min_action\1200.zip", env=env)
    print("모델 로드함")
except:
    model = DQN('MlpPolicy', env, verbose=2, tensorboard_log=logdir, batch_size=32)
    print("모델 못 불러옴 새로 함")  

TIMESTEPS = 100 #10000
iters = 12
while iters < 200:
    print("\n\n\nOn iteration: ", iters)
    iters += 1
    model.learn(total_timesteps=TIMESTEPS, tb_log_name=f"DQN") #, reset_num_timesteps=False
    model.save(f"{models_dir}/{TIMESTEPS*iters}")
    env.forced_end()
    # env.end_flag = True

print("end")