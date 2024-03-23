import pickle

# 파일에서 데이터를 읽어옵니다.
with open("./order.pkl", "rb") as f:
    loaded_order = pickle.load(f)

# 읽어온 데이터를 출력합니다.
print(loaded_order)
print(len(loaded_order))

