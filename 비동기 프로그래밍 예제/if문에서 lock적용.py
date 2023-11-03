#한번만 실행
import asyncio

async def callback():
    print("start")
    await asyncio.sleep(5)
    print("end")

class GasStation:
    def __init__(self):
        self.gas_lock = asyncio.Lock()

    async def refuel(self, car, should_refuel):
        if should_refuel:
            # 락을 획득하려고 시도
            if await self.gas_lock.acquire():
                try:
                    # 락을 획득한 자동차만 주유 진행
                    print(f"{car}가 주유 중입니다...")
                    await asyncio.sleep(2)
                    print(f"{car}가 주유를 완료했습니다.")
                    if callback:
                        await callback()
                finally:
                    # 락 해제
                    self.gas_lock.release()
            else:
                print(f"{car}는 이미 다른 자동차가 주유 중입니다.")
        else:
            print(f"{car}는 주유를 하지 않습니다.")

async def main():
    station = GasStation()
    tasks = [station.refuel(f"자동차 {i}", i == 0) for i in range(20)]
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())


# import asyncio

# class TaskQueue:
#     def __init__(self):
#         self.lock = asyncio.Lock()
    
#     async def add_task(self, task, callback):
#         async with self.lock:
#             # 작업 큐에 작업 추가
#             print(f"Adding task: {task}")
#             await asyncio.sleep(1)  # 실제로는 어떤 작업을 수행하고 있는 상상
#             print(f"Task completed: {task}")

#             # 작업이 완료된 후 콜백 함수 호출
#             if callback:
#                 await callback()

# async def main():
#     queue = TaskQueue()

#     async def on_task_complete():
#         print("Task completed callback called")

#     # 여러 개의 작업을 큐에 추가
#     await asyncio.gather(
#         queue.add_task("Task 1", on_task_complete),
#         queue.add_task("Task 2", on_task_complete),
#         queue.add_task("Task 3", on_task_complete),
#     )

# if __name__ == "__main__":
#     asyncio.run(main())
