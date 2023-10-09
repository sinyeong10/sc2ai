async def distribute_workers(self, resource_ratio: float = 2):
    """
- 점령된 모든 기지에 일꾼들을 분배 → 결과적으로 함수는 게임 내의 일꾼들을 자원 수집에 최적화하여 재배치하려고 시도
- resource_ratio 매개변수
    - 미네랄 대 가스의 현재 비율 > resource_ratio → 가스 건물을 채우려고 시도, 그렇지 않으면 미네랄 캐기를 선호
    - 이 함수는 최적화되지 않았으며, 사용자는 더 정교한 제어를 원하면 자체 배포 함수를 작성해야 합니다.
        - For example long distance mining control and moving workers if a base was killed
        are not being handled.
        - WARNING: This is quite slow when there are lots of workers or multiple bases
    """
    if not self.mineral_field or not self.workers or not self.townhalls.ready:
        return
    worker_pool = self.workers.idle  # 아무것도 하지 않는 일꾼
    bases = self.townhalls.ready
    gas_buildings = self.gas_buildings.ready

    # list of places that need more workers
    deficit_mining_places = []
    """
- 초기 체크
    - `if not self.mineral_field or not self.workers or not self.townhalls.ready:    return`
        - 미네랄 필드, 일꾼, 또는 준비된 타운홀이 없으면 함수는 아무 일도 수행하지 않고 종료
        - 결과적으로 초기 조건을 만족하지 않는 경우 함수는 변경 없이 게임의 상태를 그대로 유지
    - `worker_pool = self.workers.idle`
        - 현재 게임에서 아무 일도 하고 있지 않은 일꾼들의 목록을 `worker_pool`에 저장 → 후에 자원 수집을 위해 이 일꾼들을 재배치할 때 사용
    - `bases = self.townhalls.readygas_buildings = self.gas_buildings.ready`
        - 건물, 가스 건물 정보 가져오기
    - `deficit_mining_places = []`
        - 채광 장소 초기화 → 나중에 일꾼들이 부족한 채광 장소를 식별하는 데 사용

⇒ 일꾼 배치를 시작하기 전에 초기 조건을 체크하고, 필요한 데이터와 목록을 준비
    """

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
    """
- `for mining_place in bases | gas_buildings:`
    - `bases | gas_buildings`는 기지(`bases`)와 가스 건물(`gas_buildings`)을 합친 총 목록
    - 이 반복문은 총 목록의 각 채광 장소에 대해 실행
    - `difference = mining_place.surplus_harvesters`
        - 각 채광 장소(`mining_place`)에 대해, 현재 배치된 일꾼의 수와 이상적인 일꾼의 수와의 차이를 계산
    - `if not difference:    continue`
        - 적절한 일꾼 수 확인
        - 만약 해당 채광 장소에 일꾼 수가 적절하다면(차이가 없다면), 다음 채광 장소로 넘어감
    - `if mining_place.has_vespene:    local_workers = self.workers.filter(        lambda unit: unit.order_target == mining_place.tag or                     (unit.is_carrying_vespene and unit.order_target == bases.closest_to(mining_place).tag)    )`
        - 가스 채광 장소의 일꾼 확인
        - `mining_place.has_vespene`가 참이면 해당 장소는 가스 채광 장소.
        - 이 경우, 현재 해당 가스 건물을 대상으로 하거나 해당 가스 건물에서 가스를 운반하고 있는 일꾼들의 목록을 가져옴
    - `else:    local_minerals_tags = {        mineral.tag        for mineral in self.mineral_field if mineral.distance_to(mining_place) <= 8    }    local_workers = self.workers.filter(        lambda unit: unit.order_target in local_minerals_tags or                     (unit.is_carrying_minerals and unit.order_target == mining_place.tag)    )`
        - 미네랄 채광 장소의 일꾼 확인
        - `mining_place.has_vespene`가 거짓이면 해당 장소는 미네랄 채광 장소
        - 먼저 해당 채광 장소 주변의 미네랄 필드의 태그 목록을 생성
        - 그 후, 해당 미네랄 필드에서 일하고 있는 일꾼들의 목록을 가져옴.
⇒ 요약하면, 이 코드 부분은 각 채광 장소(가스 건물 또는 미네랄 필드)를 순회하며 해당 장소에 배치된 일꾼의 수를 확인하고, 그 장소에서 일하고 있는 일꾼들의 목록을 가져옴
    """

        if difference > 0:
            for worker in local_workers[:difference]:
                worker_pool.append(worker)
        # too few workers
        # add mining place to deficit bases for every missing worker
        else:
            deficit_mining_places += [mining_place for _ in range(-difference)]
    """
- `difference > 0` → 해당 채광 장소에 배치된 일꾼의 수 > 이상적인 수
- 초과하는 일꾼들을 게임 내에서 재배치하기 위해 `worker_pool`에 추가
- 이 때 `local_workers[:difference]`는 초과하는 일꾼 수만큼의 일꾼 리스트를 가져옴
- `difference`가 음수인 경우, 해당 채광 장소에 필요한 일꾼이 부족하다는 것을 의미
- `deficit_mining_places` 리스트에는 일꾼이 부족한 채광 장소를 여러 번 추가 → 부족한 일꾼 수만큼 동일한 채광 장소를 추가하는 것은, 나중에 일꾼을 재배치할 때 이 채광 장소를 우선적으로 고려하기 위함

⇒ 요약하면, 이 코드 부분은 채광 장소에 할당된 일꾼의 수가 너무 많거나 적은 경우 그에 따라 일꾼들을 재배치하기 위한 준비를 합니다. 너무 많은 일꾼들은 **`worker_pool`**에 추가되고, 부족한 채광 장소는 `deficit_mining_places` 목록에 반복적으로 추가됩니다
   """

    # prepare all minerals near a base if we have too many workers
    # and need to send them to the closest patch
    if len(worker_pool) > len(deficit_mining_places):
        all_minerals_near_base = [
            mineral for mineral in self.mineral_field
            if any(mineral.distance_to(base) <= 8 for base in self.townhalls.ready)
        ]
   """
- 이 조건은 `worker_pool`에 있는 일꾼의 수 > `deficit_mining_places`의 채광 장소 수 → 참
- 즉, 일꾼들을 재배치할 장소보다 더 많은 일꾼이 대기 중일 때 참입니다.
- 현재 게임 내의 모든 미네랄 필드(`self.mineral_field`) 중에서 각 기지(`self.townhalls.ready`)로부터 거리가 8 이하인 미네랄만 선택하여 목록을 생성
- 이렇게 생성된 목록(`all_minerals_near_base`)은 나중에 대기 중인 일꾼들을 가장 가까운 미네랄로 보내기 위해 사용

⇒ 요약하면, 이 코드 부분은 일꾼들이 더 많이 대기 중일 때, 그 일꾼들을 어디로 보낼지 결정하기 위해 모든 기지 주변의 미네랄 필드 목록을 준비합니다. 이 목록은 후속 코드에서 대기 중인 일꾼들을 적절한 미네랄로 보내기 위해 사용될 것입니다.
   """
    # distribute every worker in the pool
    for worker in worker_pool:
        # as long as have workers and mining places
        if deficit_mining_places:
            # choose only mineral fields first if current mineral to gas ratio is less than target ratio
            if self.vespene and self.minerals / self.vespene < resource_ratio:
                possible_mining_places = [place for place in deficit_mining_places if not place.vespene_contents]
            # else prefer gas
            else:
                possible_mining_places = [place for place in deficit_mining_places if place.vespene_contents]
            # if preferred type is not available any more, get all other places
            if not possible_mining_places:
                possible_mining_places = deficit_mining_places
            # find closest mining place
            current_place = min(deficit_mining_places, key=lambda place: place.distance_to(worker))
            # remove it from the list
            deficit_mining_places.remove(current_place)
            # if current place is a gas extraction site, go there
            if current_place.vespene_contents:
                worker.gather(current_place)
            # if current place is a gas extraction site,
            # go to the mineral field that is near and has the most minerals left
            else:
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
            target_mineral = min(all_minerals_near_base, key=lambda mineral: mineral.distance_to(worker))
            worker.gather(target_mineral)
        else:
            # there are no deficit mining places and worker is not idle
            # so dont move him
            pass
   """
distribute_workers 함수 -> 일꾼들을 자원 수집에 최적화하여 재배치
- 먼저 아무 것도 하지 않는 일꾼 목록(worker_pool)과 게임 내의 건물 및 가스 건물 정보를 초기화
- 각 채광 장소에 배치된 일꾼의 수를 확인하고, 부족한 채광 장소를 식별하여 deficit_mining_places 목록에 추가
- 만약 대기 중인 일꾼이 더 많으면, 그들을 가장 가까운 미네랄로 보내기 위해 모든 기지 주변의 미네랄 필드 목록을 준비
- 이후 모든 대기 중인 일꾼을 순회하며, 미네랄 대 가스의 현재 비율을 고려하여 일꾼들을 미네랄 필드 또는 가스 필드로 할당
- 일꾼이 할당되어야 할 채광 장소가 없고 일꾼이 한가하다면, 가장 가까운 미네랄로 보내고 그렇지 않으면, 일꾼은 움직이지 않음
   """
