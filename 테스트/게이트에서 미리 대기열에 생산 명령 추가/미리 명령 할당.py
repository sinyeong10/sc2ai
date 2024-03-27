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

class tmpIncrediBot(BotAI): # inhereits from BotAI (part of BurnySC2)
    async def on_step(self, iteration: int):
        pass


class IncrediBot(BotAI):
    async def on_step(self, iteration: int):
        if iteration == 0:
            self.check = True
            self.Flag_count = 0
            self.gas_flag = 1
            self.gas_lock = asyncio.Lock()
            self.closest_worker = None
        await self.distribute_workers()

        #중복 체크를 위해 초반 자원이 풍족한 이후 명령 실행
        if self.minerals < 500:
            return

        # begin logic:
        if self.townhalls:  # do we have a nexus?
            nexus = self.townhalls.random  # select one (will just be one for now)

            if not self.structures(UnitTypeId.PYLON) and self.already_pending(UnitTypeId.PYLON) == 0:
                if self.can_afford(UnitTypeId.PYLON):
                    pos = nexus.position.towards(self.enemy_start_locations[0], 3)
                    await self.build(UnitTypeId.PYLON, near=pos)

            #파일런 최대 5개 생산
            elif self.structures(UnitTypeId.PYLON).amount + self.already_pending(UnitTypeId.PYLON) < 2:
                if self.can_afford(UnitTypeId.PYLON):
                    # build from the closest pylon towards the enemy
                    target_pylon = self.structures(UnitTypeId.PYLON).closest_to(self.enemy_start_locations[0])
                    # build as far away from target_pylon as possible:
                    pos = target_pylon.position.towards(self.enemy_start_locations[0], random.randrange(8, 15))
                    await self.build(UnitTypeId.PYLON, near=nexus)

            if not self.structures(UnitTypeId.GATEWAY) and self.already_pending(UnitTypeId.GATEWAY) == 0:
                if self.can_afford(UnitTypeId.GATEWAY) and self.structures(UnitTypeId.PYLON):
                    await self.build(UnitTypeId.GATEWAY, near=self.structures(UnitTypeId.PYLON).closest_to(nexus))
            
            # if we have less than 10 ZEALOT, build one:
            if self.Flag_count < 6:
                if self.structures(UnitTypeId.GATEWAY) and self.can_afford(UnitTypeId.ZEALOT):
                    # print(self.structures(UnitTypeId.GATEWAY), self.structures(UnitTypeId.GATEWAY).ready, self.structures(UnitTypeId.GATEWAY).idle, self.structures(UnitTypeId.GATEWAY).ready.idle)
                    #지어지는 시점에서 structures 객체 생성, .idle로 일하지는 않는 상태
                    #생산 중인 시점에서 .ready상태 (5개의 최대 생산 상태여도 동일)
                    sg = self.structures(UnitTypeId.GATEWAY).ready #.idle
                    if sg:
                        sg[0].train(UnitTypeId.ZEALOT)
                        print("질럿 생산")
                        self.Flag_count += 1
                        await self.do_chrono_boost(sg[0])

            
            #현재 2개 이상 생산 중인 건물이 있고 새로 건물이 지어졌다면 생산명령을 분배함
            if self.structures(UnitTypeId.GATEWAY).ready.idle and len(self.structures(UnitTypeId.GATEWAY).ready[0].orders) > 1:
                print("생산 재분배")
                count = len(self.structures(UnitTypeId.GATEWAY).ready.idle) #생산 가능한 건물
                for gw in self.structures(UnitTypeId.GATEWAY).ready: #지금 생산중인 건물
                    while len(gw.orders) > 1 and count > 0: #2개이상의 생산이며 현재 생산 가능한 건물이 있다면
                        # print(gw.orders, gw.orders[0], gw.orders[-1])
                        self.do(gw(AbilityId.CANCEL_LAST)) #취소함
                        count -= 1
                        self.structures(UnitTypeId.GATEWAY).ready.idle.random.train(UnitTypeId.ZEALOT)

        else:
            if self.can_afford(UnitTypeId.NEXUS):  # can we afford one?
                await self.expand_now()  # build one!

        #공격커맨드
        if self.units(UnitTypeId.ZEALOT).amount >= 20:
            if self.check:
                await self.chat_send(f"{self.time_formatted}, {iteration}")
                self.check = False
        
    async def do_chrono_boost(self, target_structure):
        # Find a Nexus
        nexus = self.townhalls.ready.random #다 지어진 것
        if nexus:
            # Use Chrono Boost on a target structure (e.g., a Gateway)
            # target_structure = self.structures(UnitTypeId.GATEWAY).ready.random
            if target_structure:
                abilities = await self.get_available_abilities(nexus)
                if AbilityId.EFFECT_CHRONOBOOSTENERGYCOST in abilities:
                    self.do(nexus(AbilityId.EFFECT_CHRONOBOOSTENERGYCOST, target_structure))

run_game(
    maps.get("Simple64"), #2000AtmospheresAIE"),
    [Bot(Race.Protoss, IncrediBot()),
    Computer(Race.Terran, Difficulty.VeryEasy)], #Bot(Race.Protoss, tmpIncrediBot())],
    realtime=True,
)