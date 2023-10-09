import asyncio

class DistributeWorkersBot(BotAI):
    async def on_step(self, iteration: int):
        await asyncio.sleep(0.1)  # 게임의 속도를 느리게 하기 위한 딜레이
        if iteration == 0:
            await self.distribute_workers()

---
- 게임의 각 사이클에 딜레이를 추가하여 게임의 속도를 조절
- 게임의 실제 속도가 조절되는 것은 아니지만, 봇의 반응 속도를 줄여 게임이 느리게 진행되는 것처럼 보이게 할 수 있음
- 각 게임 사이클에 0.1초의 딜레이를 추가하여 게임의 속도를 줄이는 예제
- 딜레이를 0.2초로 설정하면 게임의 속도가 더 느려짐
---
