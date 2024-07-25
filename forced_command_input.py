
import pickle
with open('state_rwd_action.pkl', 'rb') as f:
    state_rwd_action = pickle.load(f)
state = state_rwd_action['state']
reward = state_rwd_action['reward']
done = state_rwd_action['done']
print(state, reward, done)
print(state_rwd_action)


def step(action):
    print(action,"을 계산함")
    wait_for_action = True
    # waits for action.
    while wait_for_action:
        #print("waiting for action")
        try:
            with open('state_rwd_action.pkl', 'rb') as f:
                state_rwd_action = pickle.load(f)

                if state_rwd_action['action'] is not None:
                    #print("No action yet")
                    wait_for_action = True
                else:
                    #print("Needs action")
                    wait_for_action = False
                    state_rwd_action['action'] = action
                    with open('state_rwd_action.pkl', 'wb') as f:
                        # now we've added the action.
                        pickle.dump(state_rwd_action, f)
        except Exception as e:
            #print(str(e))
            print(action, "명령넣다 에러남", wait_for_action)
            pass

step(3)