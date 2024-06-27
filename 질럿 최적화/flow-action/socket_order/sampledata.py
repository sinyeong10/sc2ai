import pickle

data = {"state": [100,20,30,40], "reward": 100, "action": None, "done": False}  # empty action waiting for the next one!
with open('state_rwd_action.pkl', 'wb') as f:
    # Save this dictionary as a file(pickle)
    pickle.dump(data, f)

data = {"flag":0, "idx":0, "action":0}
with open('socket_order.pkl', 'wb') as f:
    pickle.dump(data, f)

