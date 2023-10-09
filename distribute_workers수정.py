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

#최적화 츙족시킬 일꾼은 self.workers.idle은 잘 분배됨
#

class IncrediBot(BotAI):
    async def on_step(self, iteration: int):
        await asyncio.sleep(0.01)
        if iteration == 0:
            self.check = True
            self.Flag_count = 0
        # print(f"This is my bot in iteration {iteration}, workers: {self.workers}, idle workers: {self.workers.idle}, supply: {self.supply_used}/{self.supply_cap}")
        # print(f"{iteration}, n_workers: {self.workers.amount}, n_idle_workers: {self.workers.idle.amount},", \
        #     f"minerals: {self.minerals}, gas: {self.vespene}, cannons: {self.structures(UnitTypeId.PHOTONCANNON).amount},", \
        #     f"pylons: {self.structures(UnitTypeId.PYLON).amount}, nexus: {self.structures(UnitTypeId.NEXUS).amount}", \
        #     f"gateways: {self.structures(UnitTypeId.GATEWAY).amount}, cybernetics cores: {self.structures(UnitTypeId.CYBERNETICSCORE).amount}", \
        #     f"stargates: {self.structures(UnitTypeId.STARGATE).amount}, voidrays: {self.units(UnitTypeId.VOIDRAY).amount}, supply: {self.supply_used}/{self.supply_cap}")
        
        #self.custom_distribute_workers 매번 실행해야 초과되는 상황에 좋음
        if self.workers.idle:
            await self.chat_send(f"{iteration} 이 일꾼때문에 명령함 {self.workers.idle}")
            await self.custom_distribute_workers() #가스 우선
        elif self.units(UnitTypeId.PROBE).amount > 19 and (iteration%30 == 0):
            await self.chat_send(f"{iteration} 다 뽑고 체크")
            await self.custom_distribute_workers() #가스 우선

        # begin logic:
        if self.townhalls:  # do we have a nexus?
            nexus = self.townhalls.random  # select one (will just be one for now)

            #4이상 여유로울 때 프로브 생산
            supply_remaining = self.supply_cap - self. supply_used #공급한도-공급량
            if nexus.is_idle and self.can_afford(UnitTypeId.PROBE) and self.units(UnitTypeId.PROBE).amount+2 < 3*(self.structures(UnitTypeId.ASSIMILATOR).amount)+2*len(self.mineral_field.closer_than(10, self.townhalls.first)):
                await self.chat_send(f"{self.can_afford(UnitTypeId.PROBE)}")
                await self.chat_send(f"{supply_remaining}, {self.units(UnitTypeId.PROBE).amount}, {3*(self.structures(UnitTypeId.ASSIMILATOR).amount)+2*len(self.mineral_field.closer_than(10, self.townhalls.first))}")
                # await self.chat_send(self.time_formatted)
                await self.do_chrono_boost(nexus)
                nexus.train(UnitTypeId.PROBE)  # train a probe

            # if we dont have *any* pylons, we'll build one close to the nexus.
            #첫 파일런은 적기지 방향으로 지음
            elif not self.structures(UnitTypeId.PYLON) and self.already_pending(UnitTypeId.PYLON) == 0:
                if self.can_afford(UnitTypeId.PYLON):
                    pos = nexus.position.towards(self.enemy_start_locations[0], 3)
                    await self.build(UnitTypeId.PYLON, near=pos)
                    
            #         # build from the closest pylon towards the enemy
            #         target_pylon = self.structures(UnitTypeId.PYLON).closest_to(self.enemy_start_locations[0])

            elif self.structures(UnitTypeId.ASSIMILATOR).amount <= 1:
                for nexus in self.structures(UnitTypeId.NEXUS):
                    vespenes = self.vespene_geyser.closer_than(15, nexus)
                    for vespene in vespenes:
                        if self.can_afford(UnitTypeId.ASSIMILATOR) and not self.already_pending(UnitTypeId.ASSIMILATOR):
                            await self.build(UnitTypeId.ASSIMILATOR, vespene)

            # #인위적 가스 할당
            elif len(self.gas_buildings.ready) == 1 and self.Flag_count == 0:
                await self.move_gas(2)
                self.Flag_count = 1
            elif len(self.gas_buildings.ready) == 2 and self.Flag_count == 1:
                await self.move_gas(2)
                self.Flag_count = 2

            elif not self.structures(UnitTypeId.FORGE):  # if we don't have a forge:
                if self.can_afford(UnitTypeId.FORGE):  # and we can afford one:
                    # build one near the Pylon that is closest to the nexus:
                    await self.build(UnitTypeId.FORGE, near=self.structures(UnitTypeId.PYLON).closest_to(nexus))

            # if we have less than 3 cannons, let's build some more if possible:
            elif self.structures(UnitTypeId.FORGE).ready and self.structures(UnitTypeId.PHOTONCANNON).amount < 3:
                if self.can_afford(UnitTypeId.PHOTONCANNON):  # can we afford a cannon?
                    target_pylon = self.structures(UnitTypeId.PYLON).closest_to(self.enemy_start_locations[0])
                    pos = target_pylon.position.towards(self.enemy_start_locations[0], 3)
                    await self.build(UnitTypeId.PHOTONCANNON, near=pos)
            
            #인구수 막히면 파일런
            supply_remaining = self.supply_cap - self. supply_used #공급한도-공급량
            if supply_remaining < 4 and not self.already_pending(UnitTypeId.PYLON):
                if self.can_afford(UnitTypeId.PYLON):
                    pos = nexus.position.towards(self.enemy_start_locations[0], random.randrange(3, 5))
                    await self.build(UnitTypeId.PYLON, near=pos)

        else:
            if self.can_afford(UnitTypeId.NEXUS):  # can we afford one?
                await self.expand_now()  # build one!
        
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

    async def move_gas(self, move_worker: int = 1):
        bases = self.townhalls.ready
        gas_buildings = self.gas_buildings.ready
        target_location = []

        #가스일꾼 체크
        for mining_place in gas_buildings:
            if mining_place.has_vespene:
                # get all workers that target the gas extraction site
                # or are on their way back from it
                local_workers = self.workers.filter(
                    lambda unit: unit.order_target == mining_place.tag or
                    (unit.is_carrying_vespene and unit.order_target == bases.closest_to(mining_place).tag)
                )
            if len(local_workers) < 3:
                print(len(local_workers))
                target_location.append(mining_place)

        #옮길 미네랄 일꾼 체크
        for mining_place in bases:
            # get tags of minerals around expansion
            local_minerals_tags = {
                mineral.tag
                for mineral in self.mineral_field if mineral.distance_to(mining_place) <= 8
            }
            # get all target tags a worker can have
            # tags of the minerals he could mine at that base
            # get workers that work at that gather site
            local_workers = self.workers.filter(
                lambda unit: unit.order_target in local_minerals_tags or
                (unit.is_carrying_minerals and unit.order_target == mining_place.tag)
            )

        for _ in range(move_worker): #이 만큼 미네랄에서 가스로 보냄
            for target_place in target_location: #가스 기준 가장 가까운 일꾼을 일시킴
                print(target_place, type(target_place))
                worker = min(local_workers, key=lambda w: target_place.distance_to(w))
                worker.gather(target_place)
                local_workers.remove(worker)

    async def custom_distribute_workers(self, resource_ratio: float = 2):
        if not self.mineral_field or not self.workers or not self.townhalls.ready:
            return
        worker_pool = self.workers.idle #아무것도 하지 않는 일꾼
        bases = self.townhalls.ready
        gas_buildings = self.gas_buildings.ready

        # list of places that need more workers
        deficit_mining_places = []

        for mining_place in bases | gas_buildings:
            difference = mining_place.surplus_harvesters
            # perfect amount of workers, skip mining place
            if not difference:
                continue
            if mining_place.has_vespene:
                # get all workers that target the gas extraction site
                # or are on their way back from it
                local_workers = self.workers.filter(
                    lambda unit: unit.order_target == mining_place.tag or
                    (unit.is_carrying_vespene and unit.order_target == bases.closest_to(mining_place).tag)
                )
            else:
                # get tags of minerals around expansion
                local_minerals_tags = {
                    mineral.tag
                    for mineral in self.mineral_field if mineral.distance_to(mining_place) <= 8
                }
                # get all target tags a worker can have
                # tags of the minerals he could mine at that base
                # get workers that work at that gather site
                local_workers = self.workers.filter(
                    lambda unit: unit.order_target in local_minerals_tags or
                    (unit.is_carrying_minerals and unit.order_target == mining_place.tag)
                )
            # too many workers
            # print("부족한 부분", mining_place, difference)
            if difference > 0:
                for worker in local_workers[:difference]:
                    worker_pool.append(worker)
            # too few workers
            # add mining place to deficit bases for every missing worker
            else:
                deficit_mining_places += [mining_place for _ in range(-difference)]
        # print("모든 deficit_mining_places :", deficit_mining_places)
        # prepare all minerals near a base if we have too many workers
        # and need to send them to the closest patch
        if len(worker_pool) > len(deficit_mining_places):
            all_minerals_near_base = [
                mineral for mineral in self.mineral_field
                if any(mineral.distance_to(base) <= 8 for base in self.townhalls.ready)
            ]
        # distribute every worker in the pool
        for worker in worker_pool: #초과되어 일시킬 일꾼 리스트
            # as long as have workers and mining places
            if deficit_mining_places:
                # choose only mineral fields first if current mineral to gas ratio is less than target ratio
                if self.vespene and self.minerals / self.vespene < resource_ratio: #지정한 값보다 비율이 작으면 미네랄 선택
                    possible_mining_places = [place for place in deficit_mining_places if not place.vespene_contents]
                # else prefer gas
                else: #음수면 비율보다 낮아서 무조건 가스 선택
                    possible_mining_places = [place for place in deficit_mining_places if place.vespene_contents]
                # if preferred type is not available any more, get all other places
                if not possible_mining_places: #가스 선택해야하는 데 없어서 미네랄이라도 선택
                    possible_mining_places = deficit_mining_places

                #각 초과된 일꾼이 가장 가까운 자원으로 감
                # find closest mining place
                # current_place = min(deficit_mining_places, key=lambda place: place.distance_to(worker))
                current_place = min(possible_mining_places, key=lambda place: place.distance_to(worker))
                print("current_place", current_place)
                # remove it from the list
                deficit_mining_places.remove(current_place)
                # if current place is a gas extraction site, go there
                if current_place.vespene_contents: #가스면 가스캠
                    worker.gather(current_place)
                # if current place is a gas extraction site,
                # go to the mineral field that is near and has the most minerals left
                else: #미네랄이면 가장 많은 미네랄을 캠
                    local_minerals = (
                        mineral for mineral in self.mineral_field if mineral.distance_to(current_place) <= 8
                    )
                    # local_minerals can be empty if townhall is misplaced
                    target_mineral = max(local_minerals, key=lambda mineral: mineral.mineral_contents, default=None)
                    if target_mineral:
                        worker.gather(target_mineral)
            # more workers to distribute than free mining spots
            # send to closest if worker is doing nothing
            elif worker.is_idle and all_minerals_near_base:
                #각 일꾼은 all_minerals_near_base인 장소 중 가장 가까운 곳에 감
                print("all_minerals_near_base", all_minerals_near_base)
                target_mineral = min(all_minerals_near_base, key=lambda mineral: mineral.distance_to(worker))
                worker.gather(target_mineral)
            else:
                # there are no deficit mining places and worker is not idle
                # so dont move him
                pass


run_game(
    maps.get("Simple64"), #2000AtmospheresAIE"),
    [Bot(Race.Protoss, IncrediBot()),
    Computer(Race.Protoss, Difficulty.Easy)],
    realtime=True,
)