import pickle

# 파일에서 데이터를 읽어옵니다.
with open("./state_rwd_action.pkl", "rb") as f:
    state_rwd_action = pickle.load(f)
print(state_rwd_action)

with open("./socket_order.pkl", "rb") as f:
    socket_order = pickle.load(f)
print(socket_order)

with open("./rev_state_rwd_action.pkl", "rb") as f:
    rev_state_rwd_action = pickle.load(f)
print(rev_state_rwd_action)

with open("./order.pkl", "rb") as f:
    order = pickle.load(f)
print(order)

# import pickle

# # 파일에서 데이터를 읽어옵니다.
# with open("./order.pkl", "rb") as f:
#     loaded_order = pickle.load(f)

# # 읽어온 데이터를 출력
# # print(loaded_order)
# print(len(loaded_order))

# # 이중 리스트의 요소를 하나씩 추출하는 제너레이터 함수 정의
# def iterate_nested_list(nested_list):
#     for inner_list in nested_list:
#         yield inner_list

# # 제너레이터 생성
# nested_list_iterator = iterate_nested_list(loaded_order)

# import subprocess

# # yield를 사용하여 요소 하나씩 추출
# for i in range(len(loaded_order)):
#     order = next(nested_list_iterator)
#     print(i, order)
#     subprocess.run(["python", 'C:\sc2ai\질럿 최적화\\flow-action\socket_order\incredibot-sct.py', ' '.join(map(str, order))])
# # print(ans)
# print("end")

