from sc2.bot_ai import BotAI
from sc2.data import Difficulty, Race
from sc2.main import run_game
from sc2.player import Bot, Computer
from sc2 import maps
from sc2.ids.unit_typeid import UnitTypeId
import random
import sys

from sc2.ids.ability_id import AbilityId


class IncrediBot(BotAI):
    async def on_step(self, iteration: int):
        if iteration == 0:
            self.check = True
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

            # if we have less than 10 voidrays, build one:
            if self.structures(UnitTypeId.VOIDRAY).amount < 10 and self.can_afford(UnitTypeId.VOIDRAY):
                for sg in self.structures(UnitTypeId.STARGATE).ready.idle:
                    sg.train(UnitTypeId.VOIDRAY)
                    await self.do_chrono_boost(sg)



            #4이상 여유로울 때 프로브 생산
            supply_remaining = self.supply_cap - self. supply_used #공급한도-공급량
            if nexus.is_idle and self.can_afford(UnitTypeId.PROBE) and supply_remaining > 2 and self.units(UnitTypeId.PROBE).amount < 3*(self.structures(UnitTypeId.ASSIMILATOR).amount)+2*len(self.mineral_field.closer_than(10, self.townhalls.first)):
                await self.chat_send(f"{supply_remaining}, {self.units(UnitTypeId.PROBE).amount}, {3*(self.structures(UnitTypeId.ASSIMILATOR).amount)+2*len(self.mineral_field.closer_than(10, self.townhalls.first))}")
                # await self.chat_send(self.time_formatted)
                nexus.train(UnitTypeId.PROBE)  # train a probe

            # if we dont have *any* pylons, we'll build one close to the nexus.
            elif not self.structures(UnitTypeId.PYLON) and self.already_pending(UnitTypeId.PYLON) == 0:
                if self.can_afford(UnitTypeId.PYLON):
                    await self.build(UnitTypeId.PYLON, near=nexus)

            # #파일런 최대 5개 생산
            # elif self.structures(UnitTypeId.PYLON).amount < 2:
            #     if self.can_afford(UnitTypeId.PYLON):
            #         # build from the closest pylon towards the enemy
            #         target_pylon = self.structures(UnitTypeId.PYLON).closest_to(self.enemy_start_locations[0])
            #         # build as far away from target_pylon as possible:
            #         pos = target_pylon.position.towards(self.enemy_start_locations[0], random.randrange(8, 15))
            #         await self.build(UnitTypeId.PYLON, near=nexus)

            elif self.structures(UnitTypeId.ASSIMILATOR).amount <= 1:
                for nexus in self.structures(UnitTypeId.NEXUS):
                    vespenes = self.vespene_geyser.closer_than(15, nexus)
                    for vespene in vespenes:
                        if self.can_afford(UnitTypeId.ASSIMILATOR) and not self.already_pending(UnitTypeId.ASSIMILATOR):
                            await self.build(UnitTypeId.ASSIMILATOR, vespene)

            # elif not self.structures(UnitTypeId.FORGE):  # if we don't have a forge:
            #     if self.can_afford(UnitTypeId.FORGE):  # and we can afford one:
            #         # build one near the Pylon that is closest to the nexus:
            #         await self.build(UnitTypeId.FORGE, near=self.structures(UnitTypeId.PYLON).closest_to(nexus))

            # # if we have less than 3 cannons, let's build some more if possible:
            # elif self.structures(UnitTypeId.FORGE).ready and self.structures(UnitTypeId.PHOTONCANNON).amount < 3:
            #     if self.can_afford(UnitTypeId.PHOTONCANNON):  # can we afford a cannon?
            #         await self.build(UnitTypeId.PHOTONCANNON, near=nexus)  # build one near the nexus

            buildings = [UnitTypeId.GATEWAY, UnitTypeId.CYBERNETICSCORE, UnitTypeId.STARGATE]

            for building in buildings:
                if not self.structures(building) and self.already_pending(building) == 0:
                    if self.can_afford(building):
                        await self.build(building, near=self.structures(UnitTypeId.PYLON).closest_to(nexus))
                    break
            
            #인구수 막히면 파일런
            supply_remaining = self.supply_cap - self. supply_used #공급한도-공급량
            if supply_remaining < 4 and not self.already_pending(UnitTypeId.PYLON):
                await self.build(UnitTypeId.PYLON, near=nexus)

        else:
            if self.can_afford(UnitTypeId.NEXUS):  # can we afford one?
                await self.expand_now()  # build one!

        #공격커맨드
        if self.units(UnitTypeId.VOIDRAY).amount >= 5:
            if self.check:
                await self.chat_send(f"{self.time_formatted}, {iteration}")
                self.check = False
            if self.enemy_units:
                for vr in self.units(UnitTypeId.VOIDRAY).idle:
                    vr.attack(random.choice(self.enemy_units))

            elif self.enemy_structures:
                for vr in self.units(UnitTypeId.VOIDRAY).idle:
                    vr.attack(random.choice(self.enemy_structures))

            else:
                for vr in self.units(UnitTypeId.VOIDRAY).idle:
                    vr.attack(self.enemy_start_locations[0])
        
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
    Computer(Race.Protoss, Difficulty.Easy)],
    realtime=False,
)