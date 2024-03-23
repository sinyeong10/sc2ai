# #1. threading.Lock()를 통해서 한번만 실행
# import asyncio
# import threading

# async def end_display():
#     print("이동을 완료했습니다.")

# class GasStation:
#     def __init__(self):
#         self.gas_lock = threading.Lock()# asyncio.Lock()

#     async def refuel(self, car, callback):
#         # 락을 획득하려고 시도
#         if self.gas_lock.acquire(blocking=False): #blocking=False로 락 취득 실패시 대기하지 않음
#             # 락을 획득한 자동차만 주유 진행
#             print(f"{car}에 탑승했습니다...")
#             await asyncio.sleep(2)
#             print(f"{car}로 이동했습니다.")
#             await callback()
#             # 락 해제
#             self.gas_lock.release()
#         else:
#             print(f"이미 사용자는 탑승하여 {car}에 탑승하지 않습니다.")


# async def main():
#     station = GasStation()
#     tasks = [station.refuel(f"자동차 {i}", end_display) for i in range(10)]
#     await asyncio.gather(*tasks)

# asyncio.run(main())

#2. asyncio.Lock()를 통해서 한번만 실행
#await self.gas_lock.acquire():는 락을 취득할 때까지 대기함
import asyncio

class GasStation:
    def __init__(self):
        self.gas_lock = asyncio.Lock()
        self.Flag = True #critical section

    async def refuel(self, car, callback):
        # 락을 획득하려고 시도
        if not self.Flag: #read는 문제 안됨
            print(f"이미 사용자는 탑승하여 {car}에 탑승하지 않습니다.")
            return
        await self.gas_lock.acquire() #락 취득은 한개만! #여기서 if문을 이미 봐서 에러 가능성이 존재할까요?
        self.Flag = False #write는 문제 되서 락 취득하고 진행
        # 락을 획득한 자동차만 주유 진행
        print(f"{car}에 탑승했습니다...")
        await asyncio.sleep(1)
        print(f"{car}로 이동 중")
        await callback(car) #일이 끝나면 다시 시작할 수 있게 함
        #락안에서 처리하도록 await로 결과 나오고 다음 코드로 감
        # 락 해제
        self.gas_lock.release()

    async def end_display(self,car): #callback에서 다시 작동할 수 있게 설정
        self.Flag = True
        print(f"{car}로 이동을 완료했습니다.")

async def main():
    station = GasStation()
    tasks = [station.refuel(f"자동차 {i}", station.end_display) for i in range(5)]
    print("비동기 함수의 병렬 실행")
    await asyncio.gather(*tasks)

    tasks = [station.refuel(f"자동차 {i}", station.end_display) for i in range(10)]
    print("\n비동기 함수를 시간이 지남에 따라 순차적으로 비동기 실행")
    count = 0
    for order in tasks:
        if count <= 2:
            await asyncio.sleep(0.1)
            count += 1
        else:
            await asyncio.sleep(0.7)
        asyncio.create_task(order)

    await asyncio.sleep(5)

asyncio.run(main())