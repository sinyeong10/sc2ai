from sc2.bot_ai import BotAI
from sc2.data import Difficulty, Race
from sc2.main import run_game
from sc2.player import Bot, Computer
from sc2 import maps
from sc2.ids.unit_typeid import UnitTypeId
import random
import sys

from sc2.ids.ability_id import AbilityId

import asyncio

from sc2.position import Point2

from sc2.unit_command import UnitCommand

class IncrediBot(BotAI):
    async def on_step(self, iteration: int):
        await asyncio.sleep(0.05)
        #5초에 한번씩 코드 실행
        # if iteration % (5.7*5) != 0:
        #     return

        print(f"{self.time_formatted}, {iteration}")

        if iteration == 0:
            self.Flag_count = 0
            self.gas_flag = 1
            self.gas_lock = asyncio.Lock()
            self.closest_worker = None
            self.gas_build_flag = True

        await self.distribute_workers()

        # begin logic:
        if self.townhalls:  # do we have a nexus?
            nexus = self.townhalls.random  # select one (will just be one for now)

            if self.structures(UnitTypeId.ASSIMILATOR).amount <= 1:
                #이 ㅈ같은 for문을 처리해야 한번만 실행가능할 듯
                async with self.gas_lock:
                    for nexus in self.structures(UnitTypeId.NEXUS):
                        vespenes = self.vespene_geyser.closer_than(15, nexus)
                        for vespene in vespenes:
                            if self.can_afford(UnitTypeId.ASSIMILATOR) and not self.already_pending(UnitTypeId.ASSIMILATOR): #and self.gas_build_flag:
                                self.gas_build_flag = False
                                await self.build(UnitTypeId.ASSIMILATOR, vespene)

                                self.closest_worker = None
                                closest_distance = float('inf')  # 초기 거리를 무한대로 설정

                                # 모든 일꾼에 대해 거리를 계산하여 가장 가까운 일꾼 선택
                                for worker in self.workers:
                                    distance = worker.distance_to(vespene)
                                    if distance < closest_distance:
                                        self.closest_worker = worker
                                        closest_distance = distance

                                # if closest_worker:
                                #     build_action = UnitCommand(AbilityId.PROTOSSBUILD_ASSIMILATOR, closest_worker, vespene)
                                #     move_action = UnitCommand(AbilityId.MOVE, closest_worker, self.enemy_start_locations[0])
                                #     # 두 개의 동작을 함께 실행
                                #     await self._do_actions([build_action, move_action])


                                    # 가장 가까운 일꾼에게 건물 건설 명령 내림
                                    print(self.Flag_count, self.closest_worker, type(self.closest_worker))
                                    print(self.closest_worker.orders)
                                    self.do(self.closest_worker.build(UnitTypeId.ASSIMILATOR, vespene))
                                    print(f"{self.time_formatted}, {iteration}")
                                    print(self.Flag_count, self.closest_worker, type(self.closest_worker))
                                    print(self.closest_worker.orders)
                                    self.gas_flag = iteration
                # self.gas_build_flag = True

            if self.already_pending(UnitTypeId.ASSIMILATOR) and self.gas_flag < iteration - 5:
                print(f"락 전 {self.time_formatted}, {iteration}")
                print(f"락 후 {self.time_formatted}, {iteration}")
                target_position = Point2((self.closest_worker.position.x + 100, self.closest_worker.position.y+100))
                print("건설 후 이제 이동", self.Flag_count, self.closest_worker, type(self.closest_worker))
                print(self.closest_worker.orders, "\n\n")
                self.do(self.closest_worker.move(self.enemy_start_locations[0])) #target_position))
                # await asyncio.sleep(1) #게임 프레임은 멈춘 상태에서 작동
                self.gas_flag = float("inf")

run_game(
    maps.get("Simple64"), #2000AtmospheresAIE"),
    [Bot(Race.Protoss, IncrediBot()),
    Computer(Race.Protoss, Difficulty.Easy)],
    realtime=False,
)