import numpy as np
from sc2 import maps
from sc2.bot_ai import BotAI
from sc2.data import Difficulty, Race
from sc2.ids.unit_typeid import UnitTypeId
from sc2.player import Bot, Computer
from sc2.main import run_game
import time


SAVE_REPLAY = True
GOAL_MINERALS = 4000  # 목표 미네랄을 4000으로 변경

# 추가: Q-학습 관련 하이퍼파라미터 설정
LEARNING_RATE = 0.1
DISCOUNT_FACTOR = 0.9
EPSILON = 0.1
RESET_AFTER_EPISODES = 10  # 일정 에피소드 후 리셋

base = [3,0, 0, 2, 0, 0, 0, 1, 2, 2,3,2]

class MineralGatherBot(BotAI):
    def __init__(self):
        super().__init__()
        self.q_table = {}
        self.episode = 0
        self.reset_episode()
        self.current_gateway = 0  # 현재 파일런 수 초기화
        self.idx = 0
        self.check = False

    def reset_episode(self):
        self.goal_reached = False
        self.current_minerals = 0
        self.current_workers = 0
        self.current_gateway = 0  # 에피소드 시작시 파일런 수 초기화

    async def on_step(self, iteration: int):
        if self.goal_reached or self.check:
            # await self.client.leave()
            # 끝내고 보상처리, 다시 시작, 파라미터 초기화
            print("end")
            return

        current_time = self.time_formatted
        print(f"Time: {current_time}")

        await self.distribute_workers()
        current_minerals = self.minerals
        print(f"Minerals: {current_minerals}")

        num_workers = self.workers.amount
        print(f"Workers: {num_workers}")

        num_nexuses = self.townhalls.amount
        print(f"Nexuses: {num_nexuses}")

        current_action = "end" if not self.goal_reached else "waiting"
        print(f"Action: {current_action}")

        if not self.goal_reached:
            state = (current_minerals, num_workers)
            if state not in self.q_table:
                self.q_table[state] = [0, 0, 0, 0]  # Make sure to match the number of actions

            '''if np.random.uniform(0, 1) < EPSILON:
                action = np.random.choice([0, 1, 2, 3])
            else:
                action = np.argmax(self.q_table[state])'''
            action = base[self.idx] #랜덤 자리

            if action == 0 and self.can_afford(UnitTypeId.PROBE):
                for nexus in self.townhalls.ready:
                    if nexus.is_idle:
                        nexus.train(UnitTypeId.PROBE)

                        if self.idx < len(base) - 2:
                            self.idx += 1
                        else:
                            check = True
            elif action == 1:
                if self.can_afford(UnitTypeId.NEXUS):
                    await self.expand_now()

                    if self.idx < len(base) - 2:
                        self.idx += 1
                    else:
                        check = True
            elif action == 2:
                if self.can_afford(UnitTypeId.PYLON):
                    await self.build(UnitTypeId.PYLON, near=self.townhalls.random)

                    if self.idx < len(base) - 2:
                        self.idx += 1
                    else:
                        check = True
            elif action == 3:
                # Build an Assimilator and assume gathering gas
                if self.can_afford(UnitTypeId.ASSIMILATOR):
                    vespene_geysers = self.vespene_geyser.closer_than(10, self.townhalls.random)
                    for ves in vespene_geysers:
                        worker = self.select_build_worker(ves.position)
                        if worker:
                            worker.build(UnitTypeId.ASSIMILATOR, ves)
                            if self.idx < len(base) - 2:
                                self.idx += 1
                            else:
                                check = True

            new_minerals = self.minerals
            reward = new_minerals - current_minerals
            new_state = (new_minerals, num_workers)

            # Make sure the new state is in the q_table
            if new_state not in self.q_table:
                self.q_table[new_state] = [0, 0, 0, 0]  # Make sure to match the number of actions

            # Update the Q-value based on the new state and action
            self.q_table[state][action] += LEARNING_RATE * (
                        reward + DISCOUNT_FACTOR * max(self.q_table[new_state]) - self.q_table[state][action])


    async def on_end(self, result):
        if self.goal_reached:
            print(f"Victory - You have collected {GOAL_MINERALS} or more minerals!")

def main():
    result = run_game(
        maps.get("Simple64"),
        [
            Bot(Race.Protoss, MineralGatherBot()),
            Computer(Race.Protoss, Difficulty.Easy),
        ],
        realtime=True,  # 실시간 모드로 설정
    )

if __name__ == "__main__":
    main()
