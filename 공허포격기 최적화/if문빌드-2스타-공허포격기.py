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
        # await asyncio.sleep(0.05)
        #5초에 한번씩 코드 실행
        # if iteration % (5.7*5) != 0:
        #     return

        if iteration % 100 == 0:
            print(f"{self.time_formatted}, {iteration}")
        if iteration > 4000:
            await self.client.leave() # 게임 종료
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

            # if we have less than 10 voidrays, build one:
            if self.can_afford(UnitTypeId.VOIDRAY):
                for sg in self.structures(UnitTypeId.STARGATE).ready.idle:
                    sg.train(UnitTypeId.VOIDRAY)
                    await self.do_chrono_boost(sg)

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
            
            elif self.structures(UnitTypeId.ASSIMILATOR).amount <= 1 and self.can_afford(UnitTypeId.ASSIMILATOR) and not self.already_pending(UnitTypeId.ASSIMILATOR):
                #락 취득을 시도하여 한번 접근 중이면 접근 x
                if await self.gas_lock.acquire():
                    try: #락 취득 한 번만 돌 코드
                        await self.gas_build(iteration)
                    finally:
                    # 락 해제
                        self.gas_lock.release()
                else:
                    print("락이 이미 있는데 조건 만족")

            #인위적 가스 할당
            elif len(self.gas_buildings.ready) == 1 and self.Flag_count == 0:
                # print(self.Flag_count, iteration)
                await self.move_gas(3)
                self.Flag_count = 1
            elif len(self.gas_buildings.ready) == 2 and self.Flag_count == 1:
                # print(self.Flag_count, iteration)
                await self.move_gas(5)
                self.Flag_count = 2

            buildings = [UnitTypeId.GATEWAY, UnitTypeId.CYBERNETICSCORE]

            for building in buildings:
                if not self.structures(building) and self.already_pending(building) == 0:
                    if self.can_afford(building) and self.structures(UnitTypeId.PYLON):
                        await self.build(building, near=self.structures(UnitTypeId.PYLON).closest_to(nexus))
                    break
            
            if self.structures(UnitTypeId.STARGATE).amount <= 1 and self.can_afford(UnitTypeId.STARGATE) and self.already_pending(UnitTypeId.STARGATE) <= 1:
                print(self.structures(UnitTypeId.STARGATE).amount, self.can_afford(UnitTypeId.STARGATE), self.already_pending(UnitTypeId.STARGATE))
                if self.structures(UnitTypeId.PYLON):
                    await self.build(UnitTypeId.STARGATE, near=self.structures(UnitTypeId.PYLON).closest_to(nexus))


            #인구수 막히면 파일런
            supply_remaining = self.supply_cap - self. supply_used #공급한도-공급량
            if supply_remaining < 4 and not self.already_pending(UnitTypeId.PYLON):
                if self.can_afford(UnitTypeId.PYLON):
                    pos = nexus.position.towards(self.enemy_start_locations[0], random.randrange(5, 7))
                    await self.build(UnitTypeId.PYLON, near=pos)
            if supply_remaining < 8 and self.structures(UnitTypeId.CYBERNETICSCORE).amount > 0 and self.can_afford(UnitTypeId.PYLON) and self.already_pending(UnitTypeId.PYLON) <= 2:
                pos = nexus.position.towards(self.enemy_start_locations[0], random.randrange(5, 7))
                await self.build(UnitTypeId.PYLON, near=pos)

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
                #부족한 만큼 채움
                target_location.extend([mining_place]*(3 - len(local_workers)))

        local_workers = self.units([]) #초기화
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
            local_workers += self.workers.filter(
                lambda unit: unit.order_target in local_minerals_tags or
                (unit.is_carrying_minerals and unit.order_target == mining_place.tag)
            )

        move_worker_count = 0 #현재 이동한 일꾼 수
        for target_place in target_location: #가스 기준 가장 가까운 일꾼을 일시킴
            if move_worker_count > move_worker: #이 만큼 미네랄에서 가스로 보냄
                continue
            worker = min(local_workers, key=lambda w: target_place.distance_to(w))
            worker.gather(target_place)
            local_workers.remove(worker)
            move_worker_count += 1
            print(move_worker_count, worker, target_place, type(target_place))

    async def gas_build(self, iteration): #가스 한번 건설
        for nexus in self.structures(UnitTypeId.NEXUS):
            vespenes = self.vespene_geyser.closer_than(15, nexus)
            for vespene in vespenes:
                if True: #self.can_afford(UnitTypeId.ASSIMILATOR) and not self.already_pending(UnitTypeId.ASSIMILATOR): #and self.gas_build_flag:
                    # self.gas_build_flag = False
                    # await self.build(UnitTypeId.ASSIMILATOR, vespene)
                    
                    self.closest_worker = None #명령 후 이동해야 함!
                    closest_distance = float('inf')  # 초기 거리를 무한대로 설정

                    # 모든 일꾼에 대해 거리를 계산하여 가장 가까운 일꾼 선택
                    for worker in self.workers:
                        distance = worker.distance_to(vespene)
                        if distance < closest_distance:
                            self.closest_worker = worker
                            closest_distance = distance
                        # print(self.closest_worker)


                    # 가장 가까운 일꾼에게 건물 건설 명령 내림
                    print(self.Flag_count, self.closest_worker, type(self.closest_worker))
                    print(self.closest_worker.orders)
                    self.do(self.closest_worker.build(UnitTypeId.ASSIMILATOR, vespene))
                    print(f"{self.time_formatted}, {iteration}")
                    print(self.Flag_count, self.closest_worker, type(self.closest_worker))
                    print(self.closest_worker.orders)
                    self.gas_flag = iteration

                    # count = 1
                    # # while안에서 코드가 멈춰버림, 명령이 수행되지 않으니 결과도 안바낌
                    # while self.already_pending(UnitTypeId.ASSIMILATOR) == 0: #건설 중이면 다음 코드로 감
                    #     print(count, self.already_pending(UnitTypeId.ASSIMILATOR))
                    #     count+=1
                    #     pass
                    # target_position = Point2((self.closest_worker.position.x + 100, self.closest_worker.position.y+100))
                    # self.do(self.closest_worker.move(self.enemy_start_locations[0])) #target_position))
                    self.closest_worker.stop(queue=True)
                    # self.closest_worker.move(self.enemy_start_locations[0], queue=True) #한번 실행 체크용!
                    
                    return self.closest_worker

run_game(
    maps.get("Simple64"), #2000AtmospheresAIE"),
    [Bot(Race.Protoss, IncrediBot()),
    Computer(Race.Protoss, Difficulty.Easy)],
    realtime=True,
)