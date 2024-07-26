import gym
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import DummyVecEnv

# OpenAI Gym의 CartPole 환경을 설정합니다.
env = gym.make('CartPole-v1')
# 벡터 환경으로 변환합니다 (여기서는 단일 환경이지만, 벡터 환경으로 감싸는 것이 일반적입니다).
env = DummyVecEnv([lambda: env])

# PPO 알고리즘을 선택하여 모델을 초기화합니다.
model = PPO('MlpPolicy', env, verbose=1)

cnt = 0
while cnt < 2:
    cnt += 1
    print(cnt)
    # 모델을 학습시킵니다. 여기서는 간단하게 1000 타임스텝만큼 학습하도록 설정합니다.
    model.learn(total_timesteps=10)

    # 학습이 끝난 후, 모델을 저장할 수 있습니다.
    model.save("ppo_cartpole")
