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
            self.command = [0]*12
            self.sent_time_message = False
        # print(f"This is my bot in iteration {iteration}, workers: {self.workers}, idle workers: {self.workers.idle}, supply: {self.supply_used}/{self.supply_cap}")
        # print(f"{iteration}, n_workers: {self.workers.amount}, n_idle_workers: {self.workers.idle.amount},", \
            # f"minerals: {self.minerals}, gas: {self.vespene}, cannons: {self.structures(UnitTypeId.PHOTONCANNON).amount},", \
            # f"pylons: {self.structures(UnitTypeId.PYLON).amount}, nexus: {self.structures(UnitTypeId.NEXUS).amount}", \
            # f"gateways: {self.structures(UnitTypeId.GATEWAY).amount}, cybernetics cores: {self.structures(UnitTypeId.CYBERNETICSCORE).amount}", \
            # f"stargates: {self.structures(UnitTypeId.STARGATE).amount}, voidrays: {self.units(UnitTypeId.VOIDRAY).amount}, supply: {self.supply_used}/{self.supply_cap}")

        await self.distribute_workers()

        # begin logic:
        if self.townhalls:  # do we have a nexus?
            nexus = self.townhalls.random  # select one (will just be one for now)

            # if we have less than 10 voidrays, build one:
            if self.structures(UnitTypeId.ZEALOT).amount < 10 and self.can_afford(UnitTypeId.ZEALOT):
                for sg in self.structures(UnitTypeId.GATEWAY).ready.idle:
                    sg.train(UnitTypeId.ZEALOT)
                
                #현재 생산 중인 곳에 가속 걸기
            startfast = self.structures(UnitTypeId.GATEWAY).filter(lambda gateway: gateway.is_ready)#train_progress > 0)
            if self.state.game_loop % (60 * 22.4) == 0:
                print(startfast)
            for elem in startfast:
                self.command[-1]+=1
                await self.do_chrono_boost(elem)



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

            #파일런 최대 5개 생산
            elif self.structures(UnitTypeId.PYLON).amount < 2:
                if self.can_afford(UnitTypeId.PYLON):
                    # build from the closest pylon towards the enemy
                    target_pylon = self.structures(UnitTypeId.PYLON).closest_to(self.enemy_start_locations[0])
                    # build as far away from target_pylon as possible:
                    pos = target_pylon.position.towards(self.enemy_start_locations[0], random.randrange(8, 15))
                    await self.build(UnitTypeId.PYLON, near=nexus)

            buildings = [UnitTypeId.GATEWAY]

            for building in buildings:
                if self.structures(building).amount + self.already_pending(building) < 3:
                    if self.can_afford(building):
                        await self.build(building, near=self.structures(UnitTypeId.PYLON).closest_to(nexus))
                    break

        if self.state.game_loop % (60 * 22.4) == 0:
            await self.chat_send(f"현재 게임 시간: {self.time_formatted}, {self.command}")
            self.sent_time_message = True

    
    async def do_chrono_boost(self, target_structure):
        # Find a Nexus
        nexus = self.townhalls.ready.random #다 지어진 것
        if nexus:
            # Use Chrono Boost on a target structure (e.g., a Gateway)
            # target_structure = self.structures(UnitTypeId.GATEWAY).ready.random
            if target_structure:
                self.command[2]+=1
                abilities = await self.get_available_abilities(nexus)
                if AbilityId.EFFECT_CHRONOBOOSTENERGYCOST in abilities:
                    self.command[3]+=1
                    self.do(nexus(AbilityId.EFFECT_CHRONOBOOSTENERGYCOST, target_structure))

            # if (
            #     target_structure
            #     and self.state.game_loop - self.last_chrono_boost_frame > 22.4 * 20  # 예: 20초 간격으로 재사용
            #     and "AbilityId.EFFECT_CHRONOBOOSTENERGYCOST" in await self.get_available_abilities(self.townhalls.ready.random)
            # ):
            #     # 시간증폭 사용
            #     await self.do(self.townhalls.ready.random("AbilityId.EFFECT_CHRONOBOOSTENERGYCOST", target_structure))
            #     self.last_chrono_boost_frame = self.state.game_loop



run_game(
    maps.get("Simple64"), #2000AtmospheresAIE"),
    [Bot(Race.Protoss, IncrediBot()),
    Computer(Race.Protoss, Difficulty.Easy)],
    realtime=False,
)