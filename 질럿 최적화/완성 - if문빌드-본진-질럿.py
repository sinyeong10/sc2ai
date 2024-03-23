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

class tmpIncrediBot(BotAI): # inhereits from BotAI (part of BurnySC2)
    pass
    
class IncrediBot(BotAI):
    async def on_step(self, iteration: int):
        # await asyncio.sleep(0.05)
        #5초에 한번씩 코드 실행
        # if iteration % (5.7*5) != 0:
        #     return

        # print(f"{self.time_formatted}, {iteration}")

        if iteration == 0:
            self.check = True
            self.Flag_count = 0
            self.gas_flag = 1
            self.gas_lock = asyncio.Lock()
            self.closest_worker = None
            # self.gas_build_flag = True
        # print(f"This is my bot in iteration {iteration}, workers: {self.workers}, idle workers: {self.workers.idle}, supply: {self.supply_used}/{self.supply_cap}")
        # print(f"{iteration}, n_workers: {self.workers.amount}, n_idle_workers: {self.workers.idle.amount},", \
        #     f"minerals: {self.minerals}, gas: {self.vespene}, cannons: {self.structures(UnitTypeId.PHOTONCANNON).amount},", \
        #     f"pylons: {self.structures(UnitTypeId.PYLON).amount}, nexus: {self.structures(UnitTypeId.NEXUS).amount}", \
        #     f"gateways: {self.structures(UnitTypeId.GATEWAY).amount}, cybernetics cores: {self.structures(UnitTypeId.CYBERNETICSCORE).amount}", \
        #     f"stargates: {self.structures(UnitTypeId.STARGATE).amount}, voidrays: {self.units(UnitTypeId.VOIDRAY).amount}, supply: {self.supply_used}/{self.supply_cap}")

        await self.distribute_workers()

        # begin logic:
        if self.townhalls:  # do we have a nexus?
            nexus = self.townhalls.random  # select one (will just be one for now)

            # if we have less than 10 ZEALOT, build one:
            if self.can_afford(UnitTypeId.ZEALOT):
                sg = self.structures(UnitTypeId.GATEWAY).ready.idle
                if sg:
                    sg[0].train(UnitTypeId.ZEALOT)
                    await self.do_chrono_boost(sg[0])
            # if self.can_afford(UnitTypeId.ZEALOT):
            #     for sg in self.structures(UnitTypeId.GATEWAY).ready.idle:
            #         sg.train(UnitTypeId.ZEALOT)
            #         await self.do_chrono_boost(sg)

            # await self.chat_send(f"{iteration}, {self.already_pending(UnitTypeId.ASSIMILATOR)}, {self.structures(UnitTypeId.ASSIMILATOR).amount}")
            
            #4이상 여유로울 때 프로브 생산
            supply_remaining = self.supply_cap - self. supply_used #공급한도-공급량
            # and supply_remaining > 2 제한이 있어서 계속 뽑아도 될 듯?
            #self.structures(UnitTypeId.ASSIMILATOR).amount의 갯수만큼 인식된 일꾼 수에 더해줌, 가스통안에 들어간 거 갯수 인식 못함
            if nexus.is_idle and self.can_afford(UnitTypeId.PROBE) and supply_remaining > 2 and self.units(UnitTypeId.PROBE).amount\
                +self.structures(UnitTypeId.ASSIMILATOR).amount < 3*(self.structures(UnitTypeId.ASSIMILATOR).amount)\
                    +2*len(self.mineral_field.closer_than(10, self.townhalls.first)):
                await self.chat_send(f"{supply_remaining}, {self.units(UnitTypeId.PROBE).amount}, {3*(self.structures(UnitTypeId.ASSIMILATOR).amount)+2*len(self.mineral_field.closer_than(10, self.townhalls.first))}")
                # await self.chat_send(self.time_formatted)
                nexus.train(UnitTypeId.PROBE)  # train a probe

            # if we dont have *any* pylons, we'll build one close to the nexus.
            #첫 파일런은 적기지 방향으로 지음
            elif not self.structures(UnitTypeId.PYLON) and self.already_pending(UnitTypeId.PYLON) == 0:
                if self.can_afford(UnitTypeId.PYLON):
                    pos = nexus.position.towards(self.enemy_start_locations[0], 3)
                    await self.build(UnitTypeId.PYLON, near=pos)

            # #파일런 최대 5개 생산
            # elif self.structures(UnitTypeId.PYLON).amount < 2:
            #     if self.can_afford(UnitTypeId.PYLON):
            #         # build from the closest pylon towards the enemy
            #         target_pylon = self.structures(UnitTypeId.PYLON).closest_to(self.enemy_start_locations[0])
            #         # build as far away from target_pylon as possible:
            #         pos = target_pylon.position.towards(self.enemy_start_locations[0], random.randrange(8, 15))
            #         await self.build(UnitTypeId.PYLON, near=nexus)
            

            if not self.structures(UnitTypeId.GATEWAY) and self.already_pending(UnitTypeId.GATEWAY) == 0:
                if self.can_afford(UnitTypeId.GATEWAY) and self.structures(UnitTypeId.PYLON):
                    await self.build(UnitTypeId.GATEWAY, near=self.structures(UnitTypeId.PYLON).closest_to(nexus))
            
            if self.structures(UnitTypeId.GATEWAY).amount <= 5 and self.can_afford(UnitTypeId.GATEWAY) and self.already_pending(UnitTypeId.GATEWAY) <= 5:
                print(self.structures(UnitTypeId.GATEWAY).amount, self.can_afford(UnitTypeId.GATEWAY), self.already_pending(UnitTypeId.GATEWAY))
                if self.structures(UnitTypeId.PYLON):
                    await self.build(UnitTypeId.GATEWAY, near=self.structures(UnitTypeId.PYLON).closest_to(nexus))

            #인구수 막히면 파일런
            supply_remaining = self.supply_cap - self. supply_used #공급한도-공급량
            if supply_remaining < 2*self.structures(UnitTypeId.GATEWAY).amount+2 - self.already_pending(UnitTypeId.PYLON)*8:
                print(supply_remaining, 2*self.structures(UnitTypeId.GATEWAY).amount+2 - self.already_pending(UnitTypeId.PYLON)*8)
                if self.can_afford(UnitTypeId.PYLON):
                    pos = nexus.position.towards(self.enemy_start_locations[0], random.randrange(3, 5))
                    await self.build(UnitTypeId.PYLON, near=pos)

        else:
            if self.can_afford(UnitTypeId.NEXUS):  # can we afford one?
                await self.expand_now()  # build one!

        #공격커맨드
        if self.units(UnitTypeId.ZEALOT).amount >= 20:
            if self.check:
                await self.chat_send(f"{self.time_formatted}, {iteration}")
                self.check = False
            # if self.enemy_units:
            #     for vr in self.units(UnitTypeId.ZEALOT).idle:
            #         vr.attack(random.choice(self.enemy_units))

            # elif self.enemy_structures:
            #     for vr in self.units(UnitTypeId.ZEALOT).idle:
            #         vr.attack(random.choice(self.enemy_structures))

            # else:
            #     for vr in self.units(UnitTypeId.ZEALOT).idle:
            #         vr.attack(self.enemy_start_locations[0])
        
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
    Bot(Race.Protoss, tmpIncrediBot())],
    realtime=True,
)