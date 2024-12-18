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

# total_steps = 10000 
# steps_for_pun = np.linspace(0, 1, total_steps)
# step_punishment = ((np.exp(steps_for_pun**3)/10) - 0.1)*10

early_stop = 0
reward = 0

try:
    order = list(map(int, sys.argv[1].split()))
except:
    print("order이 전달되지 않음!")
    order = [0,0,1,2,2,3,3,3,9]
    # sys.exit()

import datetime
now = datetime.datetime.now()
date_string = now.strftime('%Y-%m-%d')

file_path = f"game_log-{date_string}.txt"
print(file_path)


class tmpIncrediBot(BotAI): # inhereits from BotAI (part of BurnySC2)
    async def on_step(self, iteration: int):
        pass

finish_action = False
count = 0

class IncrediBot(BotAI): # inhereits from BotAI (part of BurnySC2)
    def make(self): #이건 비동기 함수로 하면 안됨!
        global count
        global finish_action
        with open('flow_action.pkl', 'rb') as f:
            data = pickle.load(f)

        # action 값을 변경합니다.
        if finish_action:
            print(f"{count}번 째 명령인 {order[count]} 완료")
            count += 1
            print(f"{data}에서 {count}번 째 명령인 {order[count]} 시도 중")
        data['action'] = order[count]

        # 변경된 데이터를 파일에 저장합니다.
        with open('flow_action.pkl', 'wb') as f:
            pickle.dump(data, f)
            
        finish_action = False

    async def on_step(self, iteration: int): # on_step is a method that is called every step of the game.
        global early_stop
        global reward
        global finish_action #해당 명령을 지금 프레임에서 수행하였는지 여부!
        global count
        if iteration == 0:
            self.check = True
            await self.chat_send(f"order : {order}")
        if iteration > 4000: #4000이 넘어가면 불가능한 경우이므로 종료
            with open(file_path, "a") as file:
                file.write(f"{order} : {self.time_formatted}, {iteration}\n")
            await self.client.leave() # 게임 종료
            early_stop = 0
        no_action = True

        self.make() #같은 클래스에서 명령 할당!
        
        while no_action:
            try: #파일을 미리 생성
                with open('flow_action.pkl', 'rb') as f:
                    flow_action = pickle.load(f)
                    if flow_action['action'] is None:
                        print("No action yet")
                        no_action = True
                        # return #아직 없으면 해당 스텝 넘김
                    else:
                        print(iteration, "Action found")
                        no_action = False
                        #다른 코드에서 해당 파일을 수정하였으므로 명령이 입력됨!
            except:
                pass

        await self.distribute_workers() # put idle workers back to work

        action = flow_action['action']
        # print("현재 명령", action)
        # print(iteration, action)

        '''
        #0:일꾼 #12
        #1:파일런 #18
        #2:게이트 #46
        #3:질럿 ZEALOT #27
        #4:멀티 #71
        #ex:코어 36, 차원관문 100 [11생산 20 대기], 가스 21
        '''

        nexus = self.townhalls.random
        if action == 0:
            #4이상 여유로울 때 프로브 생산
            supply_remaining = self.supply_cap - self. supply_used #공급한도-공급량
            # and supply_remaining > 2 제한이 있어서 계속 뽑아도 될 듯?
            #self.structures(UnitTypeId.ASSIMILATOR).amount의 갯수만큼 인식된 일꾼 수에 더해줌, 가스통안에 들어간 거 갯수 인식 못함
            if nexus and self.can_afford(UnitTypeId.PROBE): #최대 일꾼수가 3인 상황이라 .is_idle 제한 해제
                await self.chat_send(f"{supply_remaining}, {self.units(UnitTypeId.PROBE).amount}, {3*(self.structures(UnitTypeId.ASSIMILATOR).amount)+2*len(self.mineral_field.closer_than(10, self.townhalls.first))}")
                # await self.chat_send(self.time_formatted)
                nexus.train(UnitTypeId.PROBE)  # train a probe
                finish_action = True
            
        elif action == 1:
            if not self.structures(UnitTypeId.PYLON):
                if self.can_afford(UnitTypeId.PYLON):
                    pos = nexus.position.towards(self.enemy_start_locations[0], 3)
                    await self.build(UnitTypeId.PYLON, near=pos)
                    finish_action = True
            else:
                if self.can_afford(UnitTypeId.PYLON):
                    pos = nexus.position.towards(self.enemy_start_locations[0], random.randrange(5, 7))
                    await self.build(UnitTypeId.PYLON, near=pos)
                    finish_action = True

        elif action == 2:
            # print(self.structures(UnitTypeId.PYLON), self.structures(UnitTypeId.PYLON).ready, self.structures(UnitTypeId.PYLON).idle)
            # if not self.structures(UnitTypeId.GATEWAY): #동시 건설 제한 해제 and self.already_pending(UnitTypeId.GATEWAY) == 0:
            #     if self.can_afford(UnitTypeId.GATEWAY) and self.structures(UnitTypeId.PYLON).ready: #건설가능한 미네랄과 파일런 완성이 되어있는 경우
            #         await self.build(UnitTypeId.GATEWAY, near=self.structures(UnitTypeId.PYLON).closest_to(nexus))
            #         finish_action = True

            #한 유닛이 명령을 받은 후 완료 전에 다른 명령을 받으면 앞의 명령이 무시되는 문제 발생 가능..
            #하지만 이 시점에서는 미네랄 수급량이 명령이 동시성을 유발할만큼 충족되지 않음
            if self.can_afford(UnitTypeId.GATEWAY): #갯수제한 해제 and self.structures(UnitTypeId.GATEWAY).amount <= 2 and self.already_pending(UnitTypeId.GATEWAY) <= 2:
                # print(self.structures(UnitTypeId.STARGATE).amount, self.can_afford(UnitTypeId.STARGATE), self.already_pending(UnitTypeId.STARGATE))
                if self.structures(UnitTypeId.PYLON).ready:
                    await self.build(UnitTypeId.GATEWAY, near=self.structures(UnitTypeId.PYLON).closest_to(nexus))
                    finish_action = True

        elif action == 3:
            if self.can_afford(UnitTypeId.ZEALOT):
                sg = self.structures(UnitTypeId.GATEWAY).ready #생산 중복 가능하게 함 .idle
                if sg:
                    sg[0].train(UnitTypeId.ZEALOT)
                    finish_action = True
                    if len(sg[0].orders) == 1:
                        await self.do_chrono_boost(sg[0])
        
        # #현재 2개 이상 생산 중인 건물이 있고 새로 건물이 지어졌다면 생산명령을 분배함
        # if self.structures(UnitTypeId.GATEWAY).ready.idle:
        #     build_count = len(self.structures(UnitTypeId.GATEWAY).ready.idle) #생산 가능한 건물
        #     for gw in self.structures(UnitTypeId.GATEWAY).ready: #지금 생산중인 건물
        #         while len(gw.orders) > 1 and build_count > 0: #2개이상의 생산이며 현재 생산 가능한 건물이 있다면
        #             await self.do(gw.orders[-1].unit.tag('cancel')) #취소함
        #             build_count -= 1
        #             self.structures(UnitTypeId.GATEWAY).ready.idle.random.train(UnitTypeId.ZEALOT)
        
        #현재 2개 이상 생산 중인 건물이 있고 새로 건물이 지어졌다면 생산명령을 분배함
        if self.structures(UnitTypeId.GATEWAY).ready.idle and len(self.structures(UnitTypeId.GATEWAY).ready[0].orders) > 1:
            print("생산 재분배")
            build_count = len(self.structures(UnitTypeId.GATEWAY).ready.idle) #생산 가능한 건물
            for gw in self.structures(UnitTypeId.GATEWAY).ready: #지금 생산중인 건물
                while len(gw.orders) > 1 and build_count > 0: #2개이상의 생산이며 현재 생산 가능한 건물이 있다면
                    # print(gw.orders, gw.orders[0], gw.orders[-1])
                    self.do(gw(AbilityId.CANCEL_LAST)) #취소함
                    build_count -= 1
                    accel = self.structures(UnitTypeId.GATEWAY).ready.idle.random
                    accel.train(UnitTypeId.ZEALOT)
                    await self.do_chrono_boost(accel)

        #9의 경우는 걸리지 않음, end조건 확인하고 끝

        #종료 커맨드
        if self.units(UnitTypeId.ZEALOT).amount >= 2 or not self.townhalls:
            if self.check:
                await self.chat_send(f"{self.time_formatted}, {iteration}")
                print(f"{self.time_formatted}, {iteration}")
                with open(file_path, "a") as file:
                    file.write(f"{order} : {self.time_formatted}, {iteration}\n")
                self.check = False
                early_stop = 4000-iteration
                await self.client.leave() # 게임 종료
        
        #[minerals, gas / population, max_population / number_of_workers /
        # number_of_nexuses, tech_level, iteration]
        map = [0,0,0,0,0,0,0,0]
        map[0], map[1] = self.minerals, self.vespene
        map[2], map[3] = self.supply_used, self.supply_cap
        map[4] = self.workers.amount
        map[5] = self.structures(UnitTypeId.NEXUS).amount
        Tech_level = [UnitTypeId.PYLON, UnitTypeId.GATEWAY]#, UnitTypeId.CYBERNETICSCORE]
        map[6] += sum(1 for tech_build in Tech_level if self.structures(tech_build))
        map[7] = iteration

        #유닛 생산시 -의 값으로 정보를 가져오는 경우가 있음!
        if any(value < 0 for value in map):
            # Print the entire map
            ## print(f"Map with negative values: {map}, {iteration}, {action}")
            for i in range(len(map)):
                if map[i] < 0:
                    map[i] = 0
            ## print(f"Map with negative values change: {map}, {iteration}, {action}")
        
        if iteration % 100 == 0:
            print(f"{map}, {action}\nIter: {iteration}. RWD: {reward}. VR: {self.units(UnitTypeId.ZEALOT).amount}")

        # write the file: 
        # observation(minimap), reward for this step, Action(None if waiting for action, otherwise 0,1,2,3,4,5), Is the game over
        data = {"state": map, "reward": reward, "action": None, "done": False}  # empty action waiting for the next one!
        with open('flow_action.pkl', 'wb') as f:
            # Save this dictionary as a file(pickle)
            pickle.dump(data, f)
                    
        if finish_action:
            await self.chat_send(f"명령 {order} 중 {count}번 째 명령인 {order[count]} 완료")
            await self.chat_send(f"상태 {data['state']}에서 {count+1}번 째 명령인 {order[count+1]} 시도 중")

    async def do_chrono_boost(self, target_structure): #검증 x
        # Find a Nexus
        for nexus in self.townhalls.ready: #다 지어진 것
            # Use Chrono Boost on a target structure (e.g., a Gateway)
            if target_structure:
                abilities = await self.get_available_abilities(nexus)
                if AbilityId.EFFECT_CHRONOBOOSTENERGYCOST in abilities:
                    self.do(nexus(AbilityId.EFFECT_CHRONOBOOSTENERGYCOST, target_structure))
                    break #한번만 하면 됨!

result = run_game(  # run_game is a function that runs the game.
    maps.get("Simple64"), # the map we are playing on
    [Bot(Race.Protoss, IncrediBot()), # runs our coded bot, protoss race, and we pass our bot object 
     Computer(Race.Terran, Difficulty.VeryEasy)], #Bot(Race.Zerg, tmpIncrediBot())], #기록이 중점이므로 아무것도 하지 않는 상대를 설정 #Computer(Race.Zerg, Difficulty.Hard)], # runs a pre-made computer agent, zerg race, with a hard difficulty.
    realtime=False, # When set to True, the agent is limited in how long each step can take to process.
)

with open("results.txt","a") as f:
    f.write(f"{result}\n")

reward = int(early_stop)

map = [0,0,0,0,0,0,0,0] #np.zeros((88, 96, 3), dtype=np.uint8)  #(224, 224였음)
print("end game", map, reward)
observation = map
data = {"state": map, "reward": reward, "action": None, "done": True}  # empty action waiting for the next one!
with open('flow_action.pkl', 'wb') as f:
    pickle.dump(data, f)

cv2.destroyAllWindows()
cv2.waitKey(1)
time.sleep(3)
sys.exit()