from sc2.bot_ai import BotAI  # parent class we inherit from
from sc2.data import Difficulty, Race  # difficulty for bots, race for the 1 of 3 races
from sc2.main import run_game  # function that facilitates actually running the agents in games
from sc2.player import Bot, Computer  #wrapper for whether or not the agent is one of your bots, or a "computer" player
from sc2 import maps  # maps method for loading maps to play in.
from sc2.ids.unit_typeid import UnitTypeId
import random
import cv2
import math
import numpy as np
import sys
import pickle
import time

from sc2.ids.ability_id import AbilityId
import asyncio
from sc2.position import Point2
from sc2.unit_command import UnitCommand

SAVE_REPLAY = True

total_steps = 10000 
steps_for_pun = np.linspace(0, 1, total_steps)
step_punishment = ((np.exp(steps_for_pun**3)/10) - 0.1)*10


early_stop = 0
reward = 0

class IncrediBot(BotAI): # inhereits from BotAI (part of BurnySC2)
    async def on_step(self, iteration: int): # on_step is a method that is called every step of the game.
        global early_stop
        global reward
        if iteration == 0:
            self.check = True
            self.Flag_count = 0
            self.gas_flag = 1
            self.gas_lock = asyncio.Lock()
            self.closest_worker = None
        if iteration > 4000:
            await self.client.leave() # 게임 종료
            early_stop = 0
        no_action = True
        while no_action:
            try:
                with open('state_rwd_action.pkl', 'rb') as f:
                    state_rwd_action = pickle.load(f)
                

                    if state_rwd_action['action'] is None:
                        print("No action yet")
                        time.sleep(1)
                        no_action = True
                        # return #아직 없으면 해당 스텝 넘김
                    else:
                        #print("Action found")
                        no_action = False
            except:
                pass


        await self.distribute_workers() # put idle workers back to work
        reward = 50
        action = state_rwd_action['action']
        # print(iteration, action)
    
        '''
        0:일꾼
        1:파일런 건설
        2:테크
        3:voidray생산+시간가속
        4:확장
        5:가스 건설
        6:가스에 일꾼 이동
        7:아무것도 하지 않음
        '''

        nexus = self.townhalls.random
        if action == 0:
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
                reward += 50
            # else:
            #     reward -= 10
            
        elif action == 1:
            if not self.structures(UnitTypeId.PYLON) and self.already_pending(UnitTypeId.PYLON) == 0:
                if self.can_afford(UnitTypeId.PYLON):
                    pos = nexus.position.towards(self.enemy_start_locations[0], 3)
                    await self.build(UnitTypeId.PYLON, near=pos)
                    reward += 100
            elif not self.already_pending(UnitTypeId.PYLON):
                if self.can_afford(UnitTypeId.PYLON):
                    pos = nexus.position.towards(self.enemy_start_locations[0], random.randrange(5, 7))
                    await self.build(UnitTypeId.PYLON, near=pos)
                    reward += 50
            # else:
            #     reward -= 10

        elif action == 2:
            buildings = [UnitTypeId.GATEWAY, UnitTypeId.CYBERNETICSCORE]

            for building in buildings:
                if not self.structures(building) and self.already_pending(building) == 0:
                    if self.can_afford(building) and self.structures(UnitTypeId.PYLON):
                        await self.build(building, near=self.structures(UnitTypeId.PYLON).closest_to(nexus))
                        reward += 100
                    break
            
            if self.structures(UnitTypeId.STARGATE).amount <= 1 and self.can_afford(UnitTypeId.STARGATE) and self.already_pending(UnitTypeId.STARGATE) <= 1:
                # print(self.structures(UnitTypeId.STARGATE).amount, self.can_afford(UnitTypeId.STARGATE), self.already_pending(UnitTypeId.STARGATE))
                if self.structures(UnitTypeId.PYLON):
                    await self.build(UnitTypeId.STARGATE, near=self.structures(UnitTypeId.PYLON).closest_to(nexus))
                    reward += 300 - self.structures(UnitTypeId.STARGATE).amount * 50
            #     else:
            #         reward -= 10
            # else:
            #     reward -= 10

            
        elif action == 3:
            if self.can_afford(UnitTypeId.VOIDRAY):
                for sg in self.structures(UnitTypeId.STARGATE).ready.idle:
                    sg.train(UnitTypeId.VOIDRAY)
                    await self.do_chrono_boost(sg)
                    reward += (4000-iteration)//10
            # else:
            #     reward -= 10

        elif action == 4:
            if self.Flag_count == 0 and self.can_afford(UnitTypeId.NEXUS):  # can we afford one?
                await self.expand_now()  # build one!
                self.Flag_count = 1
                reward += 50
            #     else:
            #         reward -= 10
            # else:
            #     reward -= 10
        
        elif action == 5:
            if self.structures(UnitTypeId.ASSIMILATOR).amount <= 1 and self.can_afford(UnitTypeId.ASSIMILATOR) and not self.already_pending(UnitTypeId.ASSIMILATOR):
                #락 취득을 시도하여 한번 접근 중이면 접근 x
                if await self.gas_lock.acquire():
                    try: #락 취득 한 번만 돌 코드
                        await self.gas_build(iteration)
                        reward += 50
                    finally:
                    # 락 해제
                        self.gas_lock.release()
            #     else:
            #         reward -= 10
            # else:
            #     reward -= 10
        
        elif action == 6:
            if len(self.gas_buildings.ready) >= 1 and self.gas_flag <= 6:
                await self.move_gas(3)
                self.gas_flag += 1
                reward += 50
            # else:
            #     reward -= 10
        
        elif action == 7:
            reward += 10
        
        #공격커맨드
        if self.units(UnitTypeId.VOIDRAY).amount >= 5:
            if self.check:
                await self.chat_send(f"{self.time_formatted}, {iteration}")
                self.check = False
                early_stop = 4000-iteration
                await self.client.leave() # 게임 종료
            if self.enemy_units:
                for vr in self.units(UnitTypeId.VOIDRAY).idle:
                    vr.attack(random.choice(self.enemy_units))

            elif self.enemy_structures:
                for vr in self.units(UnitTypeId.VOIDRAY).idle:
                    vr.attack(random.choice(self.enemy_structures))

            else:
                for vr in self.units(UnitTypeId.VOIDRAY).idle:
                    vr.attack(self.enemy_start_locations[0])
        
        #[minerals, gas / population, max_population / number_of_workers /
        # number_of_nexuses, tech_level, iteration]
        map = [0,0,0,0,0,0,0,0]
        map[0], map[1] = self.minerals, self.vespene
        map[2], map[3] = self.supply_used, self.supply_cap
        map[4] = self.workers.amount
        map[5] = self.structures(UnitTypeId.NEXUS).amount
        Tech_level = [UnitTypeId.PYLON, UnitTypeId.GATEWAY, UnitTypeId.CYBERNETICSCORE]
        map[6] += sum(1 for tech_build in Tech_level if self.structures(tech_build))
        map[7] = iteration

        if any(value < 0 for value in map):
            # Print the entire map
            print(f"Map with negative values: {map}, {iteration}, {action}")
            for i in range(len(map)):
                if map[i] < 0:
                    map[i] = 0
            print(f"Map with negative values change: {map}, {iteration}, {action}")
        
        if iteration % 100 == 0:
            print(f"{map}, {action}\nIter: {iteration}. RWD: {reward}. VR: {self.units(UnitTypeId.VOIDRAY).amount}")

        # write the file: 
        # observation(minimap), reward for this step, Action(None if waiting for action, otherwise 0,1,2,3,4,5), Is the game over
        data = {"state": map, "reward": reward, "action": None, "done": False}  # empty action waiting for the next one!
        with open('state_rwd_action.pkl', 'wb') as f:
            # Save this dictionary as a file(pickle)
            pickle.dump(data, f)

    async def do_chrono_boost(self, target_structure): #검증 x
        # Find a Nexus
        for nexus in self.townhalls.ready: #다 지어진 것
            # Use Chrono Boost on a target structure (e.g., a Gateway)
            if target_structure:
                abilities = await self.get_available_abilities(nexus)
                if AbilityId.EFFECT_CHRONOBOOSTENERGYCOST in abilities:
                    self.do(nexus(AbilityId.EFFECT_CHRONOBOOSTENERGYCOST, target_structure))
                    break #한번만 하면 됨!

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
                # print(len(local_workers))
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
            if local_workers.empty:
                print("해당 일꾼이 없음")
                return
            worker = min(local_workers, key=lambda w: target_place.distance_to(w))
            worker.gather(target_place)
            local_workers.remove(worker)
            move_worker_count += 1
            # print(move_worker_count, worker, target_place, type(target_place))

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
                    # print(self.Flag_count, self.closest_worker, type(self.closest_worker))
                    # print(self.closest_worker.orders)
                    self.do(self.closest_worker.build(UnitTypeId.ASSIMILATOR, vespene))
                    # print(f"{self.time_formatted}, {iteration}")
                    # print(self.Flag_count, self.closest_worker, type(self.closest_worker))
                    # print(self.closest_worker.orders)
                    # self.gas_flag = iteration

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

result = run_game(  # run_game is a function that runs the game.
    maps.get("Simple64"), # the map we are playing on
    [Bot(Race.Protoss, IncrediBot()), # runs our coded bot, protoss race, and we pass our bot object 
     Computer(Race.Zerg, Difficulty.Hard)], # runs a pre-made computer agent, zerg race, with a hard difficulty.
    realtime=False, # When set to True, the agent is limited in how long each step can take to process.
)

with open("results.txt","a") as f:
    f.write(f"{result}\n")

reward = int(early_stop)

map = [0,0,0,0,0,0,0,0] #np.zeros((88, 96, 3), dtype=np.uint8)  #(224, 224였음)
print("end game", map, reward)
observation = map
data = {"state": map, "reward": reward, "action": None, "done": True}  # empty action waiting for the next one!
with open('state_rwd_action.pkl', 'wb') as f:
    pickle.dump(data, f)

cv2.destroyAllWindows()
cv2.waitKey(1)
time.sleep(3)
sys.exit()