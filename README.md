# Introduction
컴퓨터 게임은 강화학습 연구 분야에서 높은 관심을 받는 환경 중 하나이다. 이러한 게임은 다양한 요소와 도전 과제를 제공하며 현실 세계의 다양한 응용 분야와 유사한 문제를 모델링한다. 특히 스타크래프트2는 실시간 전략 게임으로, 강화학습 연구의 중요한 벤치마크로 인정받고 있다. 이 게임은 광범위하고 다양한 행동 공간과 다중 에이전트 환경을 제공하며 불완전한 정보를 가지고 있어, 강화학습 알고리즘의 일반화 능력을 테스트하고 불확실하고 다양한 정보 아래에서 최적의 결정을 내려야 하는 상황을 모델링할 수 있다.

기존 스타크래프트2 관련 연구들은 강화학습을 통해 게임의 마스터리를 시도하거나 다중 에이전트 강화학습을 활용하여 그랜드 마스터 수준의 성과를 달성한 연구가 있다. 이러한 연구들은 스타크래프트2를 강화학습 연구의 중요한 대상으로 인정하고 있으며, 게임 인공지능 분야에서 큰 관심을 받고 있다.

본 연구에서는 스타크래프트 2 환경에서 강화학습 알고리즘을 활용하여 최적의 빌드 전략을 개발하고 이를 통해 특정 유닛을 가장 효율적으로 생산하여 전투에서 승리하는 방법을 탐구할 것이다. 이 빌드 전략은 게임에서 승리에 중요한 역할을 하며, 각 빌드에는 다양한 전략적 선택과 게임 상황에 대한 대응이 포함되어 있다. 이를 통해 스타크래프트 2를 통한 강화학습 연구의 중요성과 가능성을 강조하고, 게임 전략 개발 및 게임 인공지능 분야에 새로운 기여를 하고자 한다.

# Methodology
본 연구에서는 스타크래프트2 내 빌드 전략과 전투 전략을 개발했다. 멀티가 하나인 가정하에서 특정 시점에 가장 많은 미네랄과 가스를 획득하도록 하는 것을 강화 학습을 통해 계산하였다. 강화 학습의 평가는 동일한 맵과 초기 상태에서 시작하며, DP 테이블과 마르코프 연쇄 법칙을 활용하여 이론적으로 계산한 값과 강화 학습 결과를 비교하였다.

먼저, 미네랄 수급률을 최대화하는 빌드 전략을 강화학습을 통해 계산하였다. 미네랄 수급률에 대한 공식은 미네랄 단위당 일꾼 수가 2배수일 때 최적 효율이라는 것을 고려되었다. 이를 바탕으로 초기 빌드의 상성을 계산하고, 유닛 생산 시간 및 이동 거리와 같은 다른 변수도 고려하여 초기 빌드를 최적화하고 플레이어의 피로감을 줄일 수 있는 전략을 개발하였다.

미네랄 수급 봇을 개발하는 목적은 복잡한 실시간 전략 게임인 스타크래프트2의 게임 환경을 이해하고 에이전트가 현재 상태(미네랄 양, 유닛 수 등)를 고려하여 최적의 미네랄 수집 행동을 학습하도록 하는 것이었다. 이를 위해 봇 학습을 위한 알고리즘으로 Q-Learning 알고리즘을 사용하였다.

Q-Learning은 환경 모델을 필요로 하지 않고 게임 내 상황에 따라 병렬처리를 통해 여러 상태와 행동 조합을 동시에 학습할 수 있는 강화 학습 기법 중 하나이다. 따라서, 스타크래프트2와 같이 복잡한 게임에 적용하기에 적합하다 판단했다. 에이전트가 특정 상태에서 어떤 행동을 선택해야 하는지를 학습하는데 사용되었다.

스타크래프트2 게임에서는 다양한 환경 요소를 고려하여 게임 환경을 모델링하고 데이터를 수집하여 학습했다. 스타크래프트2 게임 환경 모델링에는 유닛의 움직임, 미네랄 위치, 적군 유닛 및 구조물 위치 등 다양한 정보가 사용되었다. 또한, 시간과 관련된 정보를 확인하고 보상으로 활용하기 위해 self.check 변수를 통해 사용했다. 

Q-Learning 알고리즘의 성능 최적화를 위해 학습률, 할인 요소, 엡실론 값 등 하이퍼파라미터를 조정하였다. 성능은 목표 미네랄량 달성 여부를 기준으로 평가되었으며 게임 진행 시간, 미네랄 채집 속도, 승리 확률 등 다양한 지표를 통해 분석되었다. 이를 통해 Q-Learning 기반의 미네랄 수집 봇의 효과가 확인되었다.

다음으로는 'IncrediBot'의 핵심 로직을 포함하는 봇이 프로토스 종족으로 게임을 진행하며, 게임 상황을 실시간으로 모니터링하고, 적절한 전략을 선택하여 최단 시간에 승리하는 전투 전략을 강화학습을 통해 계산하였다. 
초기 설정으로 게임 맵은 "Simple64"를 사용하였고, 상대방은 마찬가지로 프로토스 종족의 AI인 "Computer"로 설정하였다. 봇은 초기 단계에서 게임 시작 시 자원 및 유닛 상태를 확인하고 초기 설정을 수행한다. 이를 통해 자원 생산과 유닛 훈련에 필요한 정보를 파악한다.

봇은 on_step 함수를 통해 게임을 진행하며, 다음와 같은 주요 로직을 수행한다. 먼저 iteration이 0일 때, self.check 변수를 True로 설정한다. self.check가 True인 경우에는 현재 게임 시간과 iteration을 채팅으로 출력하고, self.check를 False로 변경한다. self.units(UnitTypeId.VOIDRAY).amount가 5 이상인 경우, 공격 커맨드를 수행한다. 이후 적군 유닛이 존재하면, 봇은 공허포격기 유닛들을 무작위로 선택하여 적군 유닛을 공격하고 적군 건물이 존재하면 마찬가지로 적군 건물을 공격한다. 그렇지 않은 경우, 봇은 공허포격기 유닛들을 게임 시작 위치로 이동시킨다. 이 때 do_chrono_boost 함수를 통해 Chrono Boost를 사용한다. Chrono Boost는 Nexus에서 활성화되며, 대상 건물의 생산 속도를 증가시킨다. 이렇게 봇은 공허포격기를 생성하고 적군을 공격하여 게임을 승리하려는 전략을 채택한다. 또한 Chrono Boost를 통해 생산 속도를 높이는 등의 추가적인 전략 요소를 활용하여 게임을 진행한다.

# Conclusion
본 연구에서는 스타크래프트2를 강화학습 연구의 중요한 대상으로 제시하고 게임 내 빌드 전략 및 전투 전략을 개발하여 그 가치를 입증하였다. 스타크래프트2 환경은 강화학습 알고리즘의 일반화 능력을 검증하고, 불확실하고 다양한 정보 아래에서 최적의 결정을 내리는 능력을 모델링하는데 매우 적합한 것으로 나타났다.

이러한 연구를 통해 게임 환경에서의 강화학습 연구의 중요성과 가능성을 강조하며, 게임 인공지능 분야에 새로운 기여를 제공함을 확인했다. 미네랄 수집과 전투 전략 최적화를 통해 게임에서의 인공지능 성능을 향상시킬 수 있음을 입증하였으며, 앞으로의 연구에서는 이러한 결과를 발전시켜 게임 인공지능 분야에 더 큰 기여를 할 것으로 기대한다.
