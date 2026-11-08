// 빌드 명령 실행기 (BWAPI AI 모듈). protocol.md v1을 TCP로 받아 스타1 안에서 실행한다.
//
// 자동 기능(환경의 일부, 명령이 아님):
//   A1 일꾼 자동 채취 : 시작 일꾼과 새 프로브를 넥서스 근처 미네랄에 결정론적으로(거리순, 패치당 최대 2) 배정하고,
//                        놀고 있으면 배정 패치로 다시 보낸다.
//   A2 건설 일꾼 선택 : 미네랄을 들고 있지 않은 가장 가까운 프로브. 건물을 놓으면 A1이 다시 채취로 보낸다.
//   A3 건설 위치     : 파일런은 넥서스에서 적 본진 방향 N타일 주변, 게이트는 첫 파일런 주변. 나선 탐색 + canBuildHere/hasPower.
//   A4 게이트 배정   : 완성된 게이트 중 놀고 있는 것, 없으면 큐가 가장 짧고 남은 생산 시간이 가장 적은 것.
//   A5 실행 가능 판정 : 자원·인구·선행 건물·위치·일꾼이 모두 되는 첫 프레임에 명령을 내리고 그 프레임을 기록.
//   A6 종료 판정     : 목표 수째 질럿 완성 프레임(onUnitComplete).
//   A7 에피소드 재시작: reset → restartGame(). onStart에서 상태 초기화.
//   A8 속도         : setLocalSpeed(0), setFrameSkip, setGUI(false). 환경 변수 BUILD_EXEC_GUI=1이면 GUI 유지.
//   A9 로그         : 명령 실행 시점 관측을 JSON 줄로 파일에 남긴다(SC2 로그와 같은 10칸 state).
#pragma once
#include <BWAPI.h>

#include <map>
#include <set>
#include <memory>
#include <string>
#include <vector>

#include "TcpLineServer.h"

// 게임 사이에도 살아 있어야 하는 상태. BWAPI가 게임마다 모듈 객체를 지우므로(GameInternals.cpp) 프로세스 수명으로 둔다.
// Dll.cpp가 라이브러리를 고정(pin)해 두어 정적 객체가 내려가지 않는다.
struct ExecutorShared {
    TcpLineServer server;
    bool serverStarted = false;
    int lastId = -1;
    std::string lastReply;
    // reset 이 게임 재시작을 요구했을 때: 새 모듈 객체의 onStart 가 이 값으로 응답한다
    bool resetPending = false;
    int resetId = -1;
    int resetTarget = 0;
    int resetSeed = -1;
};
ExecutorShared& executorShared();

class BuildExecutor : public BWAPI::AIModule {
public:
    BuildExecutor();
    ~BuildExecutor() override;

    void onStart() override;
    void onEnd(bool isWinner) override;
    void onFrame() override;
    void onUnitCreate(BWAPI::Unit unit) override;
    void onUnitComplete(BWAPI::Unit unit) override;
    void onUnitDestroy(BWAPI::Unit unit) override;
    void onSendText(std::string text) override;

private:
    // ---- 프로토콜
    void handleMessages();
    void handleMessage(const std::string& line);
    void reply(const std::string& json);
    std::string obsJson(int id, bool accepted, bool done, int endFrame, const std::string& error);
    std::vector<int> stateVector() const;
    void sendError(int id, const std::string& msg, bool fatal);
    void finishPending(bool accepted, const std::string& error);

    // ---- 자동 기능
    void setupSpeed();
    void assignMinerals();
    void autoMine();
    bool tryExecute(int action, std::string& why);
    bool canAffordSupply(BWAPI::UnitType t) const;
    int queuedSupply() const;     // 큐에서 대기 중(생산 전)인 유닛의 인구 (BW 2배 단위)
    int supplyInUse() const;      // supplyUsed() + queuedSupply()
    BWAPI::Unit pickBuilder(BWAPI::TilePosition near, const std::vector<int>* exclude = nullptr) const;
    BWAPI::TilePosition findBuildTile(BWAPI::UnitType type, BWAPI::TilePosition anchor, int maxRadius, BWAPI::Unit builder, int pathMode = 0) const;
    BWAPI::Unit pickGateway() const;
    bool keepsPath(BWAPI::TilePosition t, BWAPI::UnitType type, bool strict = true) const;  // 길막 방지(A3). strict: 2칸 통로
    bool pendingOf(BWAPI::UnitType t) const;   // 명령은 냈지만 아직 놓이지 않은 건설이 있는가
    BWAPI::TilePosition findExpansion() const; // 앞마당 넥서스 자리 (멀티)
    void rebalanceWorkers(BWAPI::Unit depot);   // 멀티로 본진 초과 일꾼 이전
    std::string techJson() const;
    std::string watchesJson() const;
    std::string abandonedJson();
    int countCompleted(BWAPI::UnitType t) const;
    int countAll(BWAPI::UnitType t) const;
    void logObservation(int action, int frame);

    // ---- 상태 (server_, serverStarted_, lastId_, lastReply_ 는 executorShared() 의 참조: 게임 사이에도 유지)
    ExecutorShared& sh_;
    TcpLineServer& server_;
    bool& serverStarted_;
    bool inGame_ = false;
    int target_ = 0;
    int endFrame_ = -1;
    int zealotsCompleted_ = 0;
    int cyberCores_ = 0;

    // 대기 중 요청 (한 번에 하나)
    struct Pending {
        bool active = false;
        int id = -1;
        std::string type;   // "step" 또는 "reset"
        int action = -1;
        int sinceFrame = 0;
        int untilFrame = 0;        // action 8(대기): 이 프레임이 되면 관측을 돌려준다
        int retries = 0;
        bool awaitingEnd = false;  // 목표 수째 질럿 명령을 내렸다. 완성(종료 프레임)까지 응답을 미룬다
    } pending_;
    // 내려진 건설 명령의 감시. 응답은 명령 시점에 이미 보냈고(SC2 로그와 같은 규약), 여기서는
    // 일꾼이 도착해 건물을 놓았는지 확인하고, 막혔으면 같은 명령을 다시 내린다(새 명령이 아니다).
    struct BuildWatch {
        BWAPI::Unit builder = nullptr;
        BWAPI::UnitType type = BWAPI::UnitTypes::None;
        BWAPI::TilePosition anchor;
        BWAPI::TilePosition tile;      // build() 에 준 자리. 다음 건물은 이 자리를 피하고, 비용은 놓일 때까지 예약
        int issuedFrame = 0;
        int expectedCount = 0;   // 명령 시점의 해당 건물 수
        int retries = 0;
        std::vector<int> tried;  // 실패한 건설 프로브 ID (갇힌 프로브를 다시 고르지 않게)
        int requestId = -1;      // 라이브 v2: 이 건설을 요구한 요청
    };
    // ---- 라이브 v2: 비동기 요청. 수명 queued → issued(건물: 놓일 때까지) → done | failed(사유)
    struct Request {
        int id = -1;
        int action = -1;
        std::string state;       // queued | issued | done | failed
        std::string reason;      // 대기 사유 또는 실패 사유
        int frameIn = 0, issuedFrame = -1, doneFrame = -1;
    };
    std::vector<Request> requests_;
    void processRequests();
    Request* findRequest(int id);
    std::string snapshotJson(int id);
    std::string requestsJson() const;
    std::string buildingsJson() const;
    void rebalanceBases();          // 일꾼 분배 규칙: 가스 3, 미네랄 기지당 덩이 2배수 → 3배수
    int lostUnits_ = 0, lostBuildings_ = 0, lastLossFrame_ = -1;
    int lastRebalanceFrame_ = 0;
    std::vector<std::string> abandoned_;  // 포기한 건설(유형 이름). 다음 관측에 실어 보내고 비운다
    std::set<int> badTiles_;              // build() 가 거부한 자리 (x*10000+y). 같은 자리로 되풀이하지 않게
    std::vector<BuildWatch> watches_;
    void checkBuildWatches();
    bool issueBuild(BWAPI::UnitType type, BWAPI::TilePosition anchor, BWAPI::Unit& builderOut, BWAPI::TilePosition& tileOut, std::string& why,
                    const std::vector<int>* exclude = nullptr);
    bool isBuilder(BWAPI::Unit u) const;
    int& lastId_;
    std::string& lastReply_;
    // reset 응답 뒤 ~ 종료 전. 이 동안 명령이 없으면 onFrame에서 다음 명령을 기다리며 프레임을 멈춘다(프레임 블로킹).
    // AI가 생각하는 동안 게임 시간이 흐르지 않아야 같은 명령열이 같은 결과를 낸다.
    bool episodeActive_ = false;
    int blockTimeoutMs_ = 50;
    int seed_ = -1;  // reset의 seed. OpenBW에서만 setRandomSeed로 쓴다
    bool wantRestart_ = false;
    int restartRequestedFrame_ = -1;
    int lastWaitFrame_ = 0;

    BWAPI::Unit mainNexus_ = nullptr;
    BWAPI::TilePosition enemyStart_ = BWAPI::TilePositions::Unknown;
    std::vector<BWAPI::Unit> patches_;             // 넥서스 근처 미네랄, 거리순
    std::vector<BWAPI::Unit> geysers_;             // 본진 간헐천 (건설 위치가 가스 길을 막지 않게)
    std::map<int, BWAPI::Unit> workerPatch_;       // 프로브 ID -> 패치
    std::vector<int> commandLog_;                  // 이번 에피소드의 명령열
    std::string logPath_;
    int waitEvery_ = 200;
    int frameSkip_ = 0;
    bool gui_ = false;
    // 인구 예약: 스타1은 큐에 넣은 유닛의 인구를 생산이 시작될 때 센다(supplyUsed 에 안 잡힘). 실행기가 내린 명령 기준으로
    // 직접 센다. 안 그러면 인구 한도를 넘는 질럿 명령이 통과해 영원히 시작되지 못하고 에피소드가 끝나지 않는다(2026-11-08).
    int issuedSupply_ = 0;      // BW 2배 단위
    int maxFrames_ = 40000;     // 이 프레임을 넘기면 대기 중 명령을 실패로 응답한다 (BUILD_EXEC_MAX_FRAMES)
    int curSpeed_ = -1;         // 에피소드 중 0(최대), 대기 중 42(보통) — 창이 응답하게
    bool live_ = false;
    int reserveMinerals_ = 0;   // 예비 자원(reserve 메시지): 이 아래로는 쓰지 않는다
    int reserveGas_ = 0;
    std::string hudText_;       // 화면 상태 표시(hud 메시지), 줄 구분 '|'         // 라이브 모드: 사람과 함께. 프레임 블로킹·재시작 없음, 기본 속도, 채팅을 text 로 전달
};
