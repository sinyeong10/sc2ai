# #1,2,2,3,3
# num = 11682
# end_frame = 583
# frame = [45,160,199,435,436]
# a = []
# for elem in frame:
#     a.append(num/end_frame*elem)
#     # print(num/end_frame*elem)

# print()
# #1,2,2,0,3,3
# num = 11723
# end_frame = 577
# frame = [45,160,199,226,431,432]
# b = []
# for elem in frame:
#     b.append(num/end_frame*elem)
#     # print(num/end_frame*elem)

# for q,w in zip(a,b):
#     print(q,w)


# #지수함수 그래프 그리기
# import numpy as np
# import matplotlib.pyplot as plt

# # x 값 범위 설정 (0에서 4000까지)
# x = np.linspace(600, 1000, 1000)

# # 지수 함수 정의 (예: f(x) = e^(-0.001x))
# k = 0.01  # 감소 속도를 조절하는 매개변수
# y = np.exp(-k * (x))
# y1 = np.exp(-k * (x-1200))
# # 그래프 그리기
# plt.figure(figsize=(10, 6))
# plt.plot(x, y, label=r'$f(x) = e^{-0.001x}$', color='blue')
# plt.plot(x, y1, label=r'$f(x) = e^{-0.001x}$', color='red')

# # 그래프 설정
# plt.title('Exponential Decay Function: $f(x) = e^{-0.001x}$')
# plt.xlabel('x')
# plt.ylabel('f(x)')
# plt.grid(True)
# plt.legend()

# plt.show()

# #SemiWorld 환경 테스트
# from semi_world import SemiWorld
# import random
# import time
# env = SemiWorld()
# done = False 
# while not done:
#     action = random.randint(0,3)
#     print(action)
#     next_state, reward, done = env.step(action)

#     print(next_state)
#     print(reward)
#     print(done)
#     print()
#     time.sleep(1)

