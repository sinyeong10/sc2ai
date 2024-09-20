import numpy as np
import matplotlib
import matplotlib.pyplot as plt


class Renderer:
    def __init__(self, matrix, goal_state, one_hot, find_one_hot, find_matrix):
        plt.close()
        plt.close()
        self.matrix = matrix
        self.goal_state = goal_state

        self.one_hot = one_hot
        self.find_one_hot = find_one_hot
        self.find_matrix = find_matrix
        
        self.ys = len(self.matrix)
        self.xs = len(self.matrix[0])

        self.ax = None
        self.fig = None
        self.first_flg = True

    def set_figure(self, figsize=None):
        fig = plt.figure(figsize=figsize)
        self.ax = fig.add_subplot(111)
        ax = self.ax
        ax.clear()
        ax.tick_params(labelbottom=False, labelleft=False, labelright=False, labeltop=False)
        ax.set_xticks(range(self.xs))
        ax.set_yticks(range(self.ys))
        ax.set_xlim(0, self.xs)
        ax.set_ylim(0, self.ys)
        ax.grid(True)

    def render_v(self, cnt, v=None, policy=None, print_value=True):
        self.set_figure(figsize=(10,10))

        ys, xs = self.ys, self.xs
        ax = self.ax

        if v is not None:
            color_list = ['red', 'white', 'green']
            cmap = matplotlib.colors.LinearSegmentedColormap.from_list(
                'colormap_name', color_list)

            # dict -> ndarray
            v_dict = v
            v = np.zeros(self.matrix.shape)
            for state, value in v_dict.items():
                # print(state, self.find_one_hot[state], self.find_matrix[self.find_one_hot[state]], value)
                v[self.find_matrix[self.find_one_hot[state]]] = value

            vmax, vmin = v.max(), v.min()
            vmax = max(vmax, abs(vmin))
            vmin = -1 * vmax
            #값이 너무 작을 때를 대비해서 처리함
            vmax = 1 if vmax < 1 else vmax
            vmin = -1 if vmin > -1 else vmin

            ax.pcolormesh(np.flipud(v), cmap=cmap, vmin=vmin, vmax=vmax)
            print(v_dict)
            print(v)

        for y in range(ys):
            for x in range(xs):
                state = (y, x)
                # r = self.matrix[y, x]
                # print(state, self.matrix[state]) #(0, 1) 0
                if self.matrix[state] < 0: #-는 보상이 없는 공간!
                    r = None
                else: #최종 목적지면 보상 아니면 0
                    r = 0 if self.one_hot[self.matrix[state]] not in self.goal_state else self.goal_state[self.one_hot[self.matrix[state]]]
                # print(r)
                if r != 0 and r is not None: #보상이 있으면 최종 위치!
                    txt = 'End Frame ' + str(r)
                    if self.one_hot[self.matrix[state]] in self.goal_state:
                        txt = txt + ' (GOAL)'
                    ax.text(x+.1, ys-y-0.9, txt)
                # print(state, self.matrix[state])
                if (v is not None) and self.matrix[state] >= 0:# state != self.wall_state:
                    if print_value:
                        offsets = [(0.4, -0.15), (-0.15, -0.3)]
                        key = 0
                        if v.shape[0] > 7: key = 1
                        offset = offsets[key]
                        ax.text(x+offset[0], ys-y+offset[1], "{:12.2f}".format(v[y, x]))

                if policy is not None and self.matrix[state] >= 0:# state != self.wall_state:
                    actions = policy[state]
                    max_actions = [kv[0] for kv in actions.items() if kv[1] == max(actions.values())]

                    arrows = ["0", "1", "2", "3"]#["↑", "↓", "←", "→"]
                    offsets = [(0, 0.1), (0, 0.1), (0, 0.1), (0, 0.1)]#(0, 0.1),  (0, -0.1), (-0.1, 0), (0.1, 0)]
                    for action in max_actions:
                        arrow = arrows[action]
                        offset = offsets[action]
                        if self.one_hot[self.matrix[state]] in self.goal_state: #최종은 제외
                            # print(self.one_hot[self.matrix[state]])
                            continue
                        ax.text(x+0.45+offset[0], ys-y-0.5+offset[1], arrow)

                if self.matrix[state] < 0: #state == self.wall_state:
                    ax.add_patch(plt.Rectangle((x,ys-y-1), 1, 1, fc=(0.4, 0.4, 0.4, 1.)))

                if self.matrix[state] == -30: #"→"
                    ax.text(x+0.05+0, ys-y-0.3-0.1, "3", fontsize=10, color='blue')
                    ax.text(x+0.05+0, ys-y-0.45-0.3, "→", fontsize=25, color='blue')
                
                if self.matrix[state] == -40: #"↓","→"
                    ax.text(x+0.6+0.1, ys-y-0.3-0.05, "2", fontsize=10)
                    ax.text(x+0.6+0, ys-y-0.45-0.3, "→", fontsize=25)
                    ax.text(x+0.3+0.15, ys-y-0.45-0.1, "↓", fontsize=25)
                
                if self.matrix[state] == -50: #"→","↓","→"
                    ax.text(x+0.6+0.1, ys-y-0.3-0.05, "2", fontsize=10)
                    ax.text(x+0.6+0, ys-y-0.45-0.3, "→", fontsize=25)
                    ax.text(x+0.3+0.15, ys-y-0.45-0.1, "↓", fontsize=25)
                    ax.text(x+0.05+0, ys-y-0.3-0.1, "3", fontsize=10, color='blue')
                    ax.text(x+0.05+0, ys-y-0.45-0.3, "→", fontsize=25, color='blue')


                if self.matrix[state] == -20: #"↓"
                    pass


        plt.show(block=False)
        print(f'./zelaot/flow-action/semi_sim/V_s_{cnt}.png')
        plt.savefig(f'./zelaot/flow-action/semi_sim/V_s_{cnt}.png')
        plt.pause(1)

    def render_q(self, cnt, q, show_greedy_policy=True):
        self.set_figure(figsize=(10,10))

        ys, xs = self.ys, self.xs
        ax = self.ax
        action_space = [0, 1, 2, 3]

        qmax, qmin = max(q.values()), min(q.values())
        qmax = max(qmax, abs(qmin))
        qmin = -1 * qmax
        qmax = 1 if qmax < 1 else qmax
        qmin = -1 if qmin > -1 else qmin


        color_list = ['red', 'white', 'green']
        cmap = matplotlib.colors.LinearSegmentedColormap.from_list(
            'colormap_name', color_list)

        for y in range(ys):
            for x in range(xs):
                for action in action_space:
                    state = (y, x)

                    # r = self.matrix[y, x]
                    # print(state)
                    if self.matrix[state] < 0:
                        r = None
                    else:
                        r = 0 if self.one_hot[self.matrix[state]] not in self.goal_state else self.goal_state[self.one_hot[self.matrix[state]]]
                    # print(r)

                    if r != 0 and r is not None:
                        txt = 'End Frame ' + str(r)
                        if self.one_hot[self.matrix[state]] in self.goal_state:
                            txt = txt + ' (GOAL)'
                        ax.text(x+.05, ys-y-0.95, txt)

                    #접근가능한 상태이고 최종상태이면 넘어감
                    if self.matrix[state] >= 0 and self.one_hot[self.matrix[state]] in self.goal_state:
                        continue

                    tx, ty = x, ys-y-1

                    action_map = {
                        0: ((0.5+tx, 0.5+ty), (tx+1, ty+1), (tx, ty+1)),
                        1: ((tx, ty), (tx+1, ty), (tx+0.5, ty+0.5)),
                        2: ((tx, ty), (tx+0.5, ty+0.5), (tx, ty+1)),
                        3: ((0.5+tx, 0.5+ty), (tx+1, ty), (tx+1, ty+1)),
                    }
                    offset_map = {
                        0: (0.1, 0.8),
                        1: (0.1, 0.1),
                        2: (-0.2, 0.4),
                        3: (0.4, 0.4),
                    }
                    if self.matrix[state] < 0: #state == self.wall_state:
                        ax.add_patch(plt.Rectangle((tx, ty), 1, 1, fc=(0.4, 0.4, 0.4, 1.)))
                    elif self.one_hot[self.matrix[state]] in self.goal_state:
                        ax.add_patch(plt.Rectangle((tx, ty), 1, 1, fc=(0., 1., 0., 1.)))
                    else:
                        tq = q[(self.one_hot[self.matrix[state]], action)]
                        color_scale = 0.5 + (tq / qmax) / 2  # normalize: 0.0-1.0

                        poly = plt.Polygon(action_map[action],fc=cmap(color_scale))
                        ax.add_patch(poly)

                        offset= offset_map[action]
                        ax.text(tx+offset[0], ty+offset[1], "{:12.2f}".format(tq))

                    if self.matrix[state] == -30: #"→"
                        ax.text(x+0.05+0, ys-y-0.3-0.1, "3", fontsize=10, color='blue')
                        ax.text(x+0.05+0, ys-y-0.45-0.3, "→", fontsize=25, color='blue')
                    
                    if self.matrix[state] == -40: #"↓","→"
                        ax.text(x+0.6+0.1, ys-y-0.3-0.05, "2", fontsize=10)
                        ax.text(x+0.6+0, ys-y-0.45-0.3, "→", fontsize=25)
                        ax.text(x+0.3+0.15, ys-y-0.45-0.1, "↓", fontsize=25)
                    
                    if self.matrix[state] == -50: #"→","↓","→"
                        ax.text(x+0.6+0.1, ys-y-0.3-0.05, "2", fontsize=10)
                        ax.text(x+0.6+0, ys-y-0.45-0.3, "→", fontsize=25)
                        ax.text(x+0.3+0.15, ys-y-0.45-0.1, "↓", fontsize=25)
                        ax.text(x+0.05+0, ys-y-0.3-0.1, "3", fontsize=10, color='blue')
                        ax.text(x+0.05+0, ys-y-0.45-0.3, "→", fontsize=25, color='blue')

        plt.show(block=False)
        plt.savefig(f'./zelaot/flow-action/semi_sim/Q_s_a_{cnt}.png')
        plt.pause(1)

        if show_greedy_policy:
            policy = {}
            for y in range(self.ys):
                for x in range(self.xs):
                    state = (y, x)
                    if self.matrix[state] >= 0:
                        # print(state, action, q[state, action], q[self.one_hot[self.matrix[state]], action])
                        qs = [q[self.one_hot[self.matrix[state]], action] for action in range(4)]  # action_size
                        max_action = np.argmax(qs)
                    else: #None이 state면 defaultdict라 무조건 0임!
                        max_action = 0
                    probs = {0:0.0, 1:0.0, 2:0.0, 3:0.0}
                    probs[max_action] = 1
                    policy[state] = probs
            self.render_v(cnt, None, policy)
        