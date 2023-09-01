from sc2.bot_ai import BotAI
from sc2.data import Difficulty, Race
from sc2.main import run_game
from sc2.player import Bot, Computer
from sc2 import maps
from sc2.ids.unit_typeid import UnitTypeId
import numpy as np
import sys

SAVE_REPLAY = True
GOAL_MINERALS = 100

# Additional Q-learning hyperparameters
LEARNING_RATE = 0.1
DISCOUNT_FACTOR = 0.9
EPSILON = 0.1

class MineralGatherBot(BotAI):
    def __init__(self):
        super().__init__()
        self.goal_reached = False
        self.q_table = {}
        self.previous_minerals = 0
        self.previous_workers = 0
        self.pylon_built = False
        self.pylon_count = 0


    async def on_step(self, iteration: int):
        if self.goal_reached:
            await self.client.leave()
            return

        current_time = self.time_formatted
        # print(f"Time: {current_time}")

        await self.distribute_workers()
        current_minerals = self.minerals
        # print(f"Minerals: {current_minerals}")
        num_workers = self.workers.amount
        # print(f"Workers: {num_workers}")
        # print(f"Pylons: {self.pylon_count}")

        # Check if we need a pylon
        if (
            not self.pylon_built
            and (self.supply_left < 4 or self.supply_left < self.pylon_count)
            and self.already_pending(UnitTypeId.PYLON) == 0
        ):
            if self.can_afford(UnitTypeId.PYLON):
                await self.build(UnitTypeId.PYLON, near=self.townhalls.first.position.towards(self.game_info.map_center, 8))
                self.pylon_built = True
                self.pylon_count += 1

        # Update the Q-table based on the current state and action
        if not self.goal_reached:
            state = (current_minerals, num_workers)
            if state not in self.q_table:
                self.q_table[state] = [0, 0]

            # Choose action using epsilon-greedy policy
            if np.random.uniform(0, 1) < EPSILON:
                action = np.random.choice([0, 1])
            else:
                action = np.argmax(self.q_table[state])

            # Take action: 0 for building workers, 1 for doing nothing
            if action == 0 and self.can_afford(UnitTypeId.PROBE):
                for nexus in self.townhalls.ready:
                    if nexus.is_idle:
                        nexus.train(UnitTypeId.PROBE)

            # Calculate reward based on mineral change
            reward = current_minerals - self.previous_minerals

            # Update Q-value for the current state-action pair
            new_state = (current_minerals, num_workers)
            if new_state not in self.q_table:
                self.q_table[new_state] = [0, 0]

            # Q-learning update equation
            self.q_table[state][action] += LEARNING_RATE * (
                reward + DISCOUNT_FACTOR * max(self.q_table[new_state]) - self.q_table[state][action]
            )

            # Store current values for the next iteration
            self.previous_minerals = current_minerals
            self.previous_workers = num_workers

        # Check if the goal is reached
        if current_minerals >= GOAL_MINERALS:
            self.goal_reached = True
            print("Goal reached! You win!")
            print(f"Time: {current_time}")
            print(f"Minerals: {current_minerals}")
            print(f"Workers: {num_workers}")
            print(f"Pylons: {self.pylon_count}")

    async def on_end(self, result):
        if self.goal_reached:
            print(f"Victory - You have collected {GOAL_MINERALS} or more minerals!")

def main():
    result = run_game(
        maps.get("Simple64"),
        [Bot(Race.Protoss, MineralGatherBot()), Bot(Race.Protoss, MineralGatherBot())],
        realtime=True,
    )

if __name__ == "__main__":
    main()