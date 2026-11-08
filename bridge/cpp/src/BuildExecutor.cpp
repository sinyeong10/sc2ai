#include "BuildExecutor.h"

#include <algorithm>
#include <cstdlib>
#include <ctime>
#include <fstream>

#include "MiniJson.h"

using namespace BWAPI;
namespace mj = minijson;

namespace {
const int kProtocolVersion = 1;
const int kDefaultPort = 15800;
const int kMaxBuildRetries = 200;      // 건설 재발행 상한 (24프레임 간격 → 약 80초 분량). 실행 보장: 프로브·자리를 바꿔 가며 끝까지
const int kBuildConfirmFrames = 600;   // 건설 명령 뒤 건물이 생기지 않으면 다시 내리는 한계
const int kReissueInterval = 24;       // 재발행 최소 간격(프레임). 매 프레임 재발행하면 프로브를 순식간에 다 써 버린다

const char* kActionNames[] = {"worker", "pylon", "gateway", "zealot"};

std::string envOr(const char* name, const std::string& dflt) {
    const char* v = std::getenv(name);
    return v && *v ? std::string(v) : dflt;
}

UnitType typeOf(int action) {
    switch (action) {
        case 0: return UnitTypes::Protoss_Probe;
        case 1: return UnitTypes::Protoss_Pylon;
        case 2: return UnitTypes::Protoss_Gateway;
        case 3: return UnitTypes::Protoss_Zealot;
        case 4: return UnitTypes::Protoss_Nexus;
        case 5: return UnitTypes::Protoss_Assimilator;
        case 6: return UnitTypes::Protoss_Cybernetics_Core;
        case 7: return UnitTypes::Protoss_Dragoon;
        case 10: return UnitTypes::Protoss_Citadel_of_Adun;
        case 11: return UnitTypes::Protoss_Templar_Archives;
        case 12: return UnitTypes::Protoss_High_Templar;
        case 13: return UnitTypes::Protoss_Dark_Templar;
        case 14: return UnitTypes::Protoss_Forge;
        default: return UnitTypes::None;
    }
}
UpgradeType upgradeOf(int action) {
    switch (action) {
        case 15: return UpgradeTypes::Protoss_Ground_Weapons;
        case 16: return UpgradeTypes::Protoss_Ground_Armor;
        case 17: return UpgradeTypes::Protoss_Plasma_Shields;
        default: return UpgradeTypes::None;
    }
}
bool knownAction(int a) { return typeOf(a) != UnitTypes::None || upgradeOf(a) != UpgradeTypes::None; }
}  // namespace

ExecutorShared& executorShared() {
    static ExecutorShared* s = new ExecutorShared();  // 프로세스 종료 때 소멸자를 돌리지 않는다(스레드 join 중 교착 방지)
    return *s;
}

BuildExecutor::BuildExecutor()
    : sh_(executorShared()), server_(sh_.server), serverStarted_(sh_.serverStarted),
      lastId_(sh_.lastId), lastReply_(sh_.lastReply) {}
// 서버는 멈추지 않는다. 게임이 끝나면 BWAPI가 이 객체를 지우고 다음 게임에서 새로 만들지만 연결은 유지된다.
BuildExecutor::~BuildExecutor() = default;

// ------------------------------------------------------------------ 수명
void BuildExecutor::onStart() {
    inGame_ = true;
    endFrame_ = -1;
    zealotsCompleted_ = 0;
    cyberCores_ = 0;
    commandLog_.clear();
    workerPatch_.clear();
    patches_.clear();
    watches_.clear();
    mainNexus_ = nullptr;
    wantRestart_ = false;
    lastWaitFrame_ = 0;
    badTiles_.clear();
    walkGrid_.clear();
    placeFailFrame_.clear();
    groundDist_.clear();
    expansionCache_ = TilePositions::Invalid;
    expansionCacheDepots_ = -1;
    gameId_ = std::to_string(static_cast<long long>(std::time(nullptr))) + "-" + std::to_string(++sh_.games);
    rallyMode_ = 0;
    rallyManual_ = rallyNow_ = Positions::Invalid;
    lastRallyFrame_ = -1000;
    // 이전 모듈 객체가 reset 을 받고 게임을 재시작한 경우: 목표·시드를 넘겨받는다(응답은 아래에서)
    if (sh_.resetPending) {
        target_ = sh_.resetTarget;
        seed_ = sh_.resetSeed;
        pending_ = Pending();
        pending_.active = true;
        pending_.id = sh_.resetId;
        pending_.type = "reset";
        sh_.resetPending = false;
    }

    waitEvery_ = std::atoi(envOr("BUILD_EXEC_WAIT_EVERY", "200").c_str());
    frameSkip_ = std::atoi(envOr("BUILD_EXEC_FRAME_SKIP", "0").c_str());
    gui_ = envOr("BUILD_EXEC_GUI", "0") == "1";
    logPath_ = envOr("BUILD_EXEC_LOG", "build_exec_log.jsonl");
    maxFrames_ = std::atoi(envOr("BUILD_EXEC_MAX_FRAMES", "40000").c_str());
    issuedSupply_ = Broodwar->self()->supplyUsed();
    curSpeed_ = -1;

    if (!serverStarted_) {
        std::string host = envOr("BUILD_EXEC_HOST", "0.0.0.0");
        int port = std::atoi(envOr("BUILD_EXEC_PORT", "15800").c_str());
        if (port <= 0) port = kDefaultPort;
        serverStarted_ = server_.start(host, port);
        Broodwar->printf("BuildExecutor: %s %s:%d", serverStarted_ ? "listening" : server_.lastError().c_str(), host.c_str(), port);
    }

    Broodwar->enableFlag(Flag::UserInput);  // 디버그용 수동 조작 허용. 학습 중에는 손대지 않는다
    setupSpeed();
#ifdef OPENBW
    // OpenBW 포크 전용. 같은 시드 + 같은 명령열 = 같은 결과를 노린다. 원본 1.16.1은 bwapi.ini의 seed_override로 고정한다.
    if (seed_ >= 0) Broodwar->setRandomSeed(static_cast<unsigned>(seed_));
#endif

    for (auto u : Broodwar->self()->getUnits())
        if (u->getType().isResourceDepot()) mainNexus_ = u;
    if (Broodwar->enemy()) enemyStart_ = Broodwar->enemy()->getStartLocation();
    if (enemyStart_ == TilePositions::Unknown || enemyStart_ == TilePositions::None) {
        // 적 위치를 모르면 맵 중앙을 향한다
        enemyStart_ = TilePosition(Broodwar->mapWidth() / 2, Broodwar->mapHeight() / 2);
    }
    assignMinerals();

    // 이전 에피소드가 reset을 기다리다 재시작된 경우: 첫 프레임 관측을 돌려준다
    if (pending_.active && pending_.type == "reset") {
        lastId_ = pending_.id;
        lastReply_ = obsJson(pending_.id, true, false, -1, "");
        reply(lastReply_);
        pending_ = Pending();
        episodeActive_ = true;
    }
}

void BuildExecutor::onEnd(bool) {
    inGame_ = false;
}

void BuildExecutor::setupSpeed() {
    Broodwar->setLocalSpeed(0);
    Broodwar->setFrameSkip(frameSkip_);
    Broodwar->setGUI(gui_);
    Broodwar->setCommandOptimizationLevel(0);  // 명령을 합치지 않는다. 한 프레임 한 명령의 기록을 지킨다
}

// ------------------------------------------------------------------ 매 프레임
void BuildExecutor::onFrame() {
    if (!inGame_) return;
    if (server_.takeDisconnectEvent() && pending_.active) {
        pending_ = Pending();  // 상대가 끊겼다. 대기 명령 취소
    }
    handleMessages();

    // 프레임 블로킹: 에피소드 중 명령이 없으면 다음 메시지가 올 때까지 이 프레임에서 멈춘다.
    // AI의 생각 시간·네트워크 지연이 게임 시간에 섞이지 않는다. 끊기면 풀린다.
    while (!live_ && episodeActive_ && !pending_.active && endFrame_ < 0 && server_.connected() && !wantRestart_) {
        std::string line;
        if (server_.waitLine(line, blockTimeoutMs_)) handleMessage(line);
        if (server_.takeDisconnectEvent()) { pending_ = Pending(); episodeActive_ = false; }
    }

    if (wantRestart_) {
        wantRestart_ = false;
#ifdef OPENBW
        // OpenBW: restartGame()이 동작하지 않는다(BUGS.txt). 게임을 떠나면 BWAPILauncher가
        // auto_restart != OFF 일 때 같은 설정으로 다음 게임을 만든다(MPQ는 다시 읽지 않음).
        Broodwar->leaveGame();
#else
        Broodwar->restartGame();  // 싱글 플레이어에서만 동작. onEnd → onStart 순으로 다시 들어온다
#endif
        return;
    }

    checkBuildWatches();
    autoMine();
    if (live_) {
        if (Broodwar->getFrameCount() % 1200 == 0) badTiles_.clear();  // 거부 자리는 일시적일 수 있다(유닛이 서 있던 경우)
        processRequests();
        if (Broodwar->getFrameCount() - lastRebalanceFrame_ >= 24) { rebalanceBases(); lastRebalanceFrame_ = Broodwar->getFrameCount(); }
        if (Broodwar->getFrameCount() - lastRallyFrame_ >= 48) { updateRally(); lastRallyFrame_ = Broodwar->getFrameCount(); }
        if (rallyNow_.isValid()) {
            Broodwar->drawCircleMap(rallyNow_, 12, rallyMode_ == 1 ? Colors::Yellow : Colors::Green, false);
            Broodwar->drawTextMap(rallyNow_.x - 14, rallyNow_.y - 22, "rally%s", rallyMode_ == 1 ? "" : " (auto)");
        }
    }
    // 업그레이드 중인 건물(포지) 위에 '업그레이드 L레벨 남은초'와 작은 막대
    for (auto u : Broodwar->self()->getUnits()) {
        if (!u->isUpgrading()) continue;
        UpgradeType up = u->getUpgrade();
        int lvl = Broodwar->self()->getUpgradeLevel(up) + 1;
        int total = std::max(1, up.upgradeTime(lvl)), rem = u->getRemainingUpgradeTime();
        Position pp = u->getPosition();
        Broodwar->drawTextMap(pp.x - 40, pp.y - 36, "%s L%d %ds", up.getName().substr(8).c_str(), lvl, rem / 24);
        Broodwar->drawBoxMap(pp.x - 40, pp.y - 24, pp.x + 40, pp.y - 20, Colors::Grey, false);
        int fill = 80 * (total - rem) / total;
        if (fill > 0) Broodwar->drawBoxMap(pp.x - 39, pp.y - 23, pp.x - 40 + fill, pp.y - 21, Colors::Cyan, true);
    }
    {
        // 우측 하단: 진행 중인 업그레이드마다 막대 하나 (진행률 막대 위로 쌓는다)
        int yy = 262;
        for (auto u : Broodwar->self()->getUnits()) {
            if (!u->isUpgrading()) continue;
            UpgradeType up = u->getUpgrade();
            int lvl = Broodwar->self()->getUpgradeLevel(up) + 1;
            int total = std::max(1, up.upgradeTime(lvl)), rem = u->getRemainingUpgradeTime();
            int fill = 200 * (total - rem) / total;
            Broodwar->drawTextScreen(430, yy - 11, "%s L%d  %ds", up.c_str(), lvl, rem / 24);
            Broodwar->drawBoxScreen(430, yy, 630, yy + 6, Colors::Grey, false);
            if (fill > 0) Broodwar->drawBoxScreen(431, yy + 1, 430 + fill, yy + 5, Colors::Cyan, true);
            yy -= 22;
        }
    }
    if (!progressText_.empty()) {
        // 우측 하단(하단 UI 패널 바로 위): 글 한 줄 + 막대
        const int x0 = 430, y0 = 286, w = 200, hgt = 8;
        Broodwar->drawTextScreen(x0, y0 - 12, "%s", progressText_.c_str());
        if (progressPermille_ >= 0) {
            Broodwar->drawBoxScreen(x0, y0, x0 + w, y0 + hgt, Colors::Grey, false);
            int fill = w * progressPermille_ / 1000;
            if (fill > 0) Broodwar->drawBoxScreen(x0 + 1, y0 + 1, x0 + fill, y0 + hgt - 1, Colors::Green, true);
        }
    }
    if (!hudText_.empty()) {
        int y = 4;
        size_t start = 0;
        while (start <= hudText_.size()) {
            size_t end = hudText_.find('|', start);
            std::string line = hudText_.substr(start, end == std::string::npos ? std::string::npos : end - start);
            Broodwar->drawTextScreen(4, y, "%s", line.c_str());
            y += 12;
            if (end == std::string::npos) break;
            start = end + 1;
        }
    }

    // 에피소드 중에는 최대 속도, 대기 중에는 보통 속도(창이 응답하고 CPU 를 덜 쓴다)
    int wantSpeed = live_ ? -1 : ((episodeActive_ || pending_.active) ? 0 : 42);  // 라이브: 게임 기본 속도
    if (wantSpeed != curSpeed_) { Broodwar->setLocalSpeed(wantSpeed); curSpeed_ = wantSpeed; }

    if (pending_.active && pending_.type == "step") {
        // 안전장치: 실행 불가능한 명령(인구·자원이 영원히 안 되는 경우)으로 게임이 끝없이 돌지 않게 한다
        if (Broodwar->getFrameCount() > maxFrames_) {
            finishPending(false, "frame limit " + std::to_string(maxFrames_));
            return;
        }
        if (pending_.awaitingEnd) {
            // 마지막 질럿 명령은 완성까지 기다렸다가 done=true, end_frame과 함께 응답한다 (SimBackend와 같은 의미)
            if (endFrame_ >= 0) finishPending(true, "");
            else if (Broodwar->getFrameCount() - lastWaitFrame_ >= waitEvery_) {
                lastWaitFrame_ = Broodwar->getFrameCount();
                mj::Writer w;
                w.key("type").value("wait").key("id").value(pending_.id).key("frame").value(lastWaitFrame_).key("reason").value("awaiting last zealot");
                reply(w.str());
            }
            return;
        }
        if (pending_.action == 8) {
            if (Broodwar->getFrameCount() >= pending_.untilFrame) {
                // 에피소드가 끝난 뒤의 대기도 허용한다(측정용). done 은 endFrame_ 로 판단된다
                std::string out = obsJson(pending_.id, true, endFrame_ >= 0, endFrame_, "");
                lastId_ = pending_.id;
                lastReply_ = out;
                pending_ = Pending();
                reply(out);
            }
            return;
        }
        if (endFrame_ >= 0) {
            finishPending(false, "episode already finished");
            return;
        }
        std::string why;
        if (tryExecute(pending_.action, why)) {
            int frame = Broodwar->getFrameCount();
            commandLog_.push_back(pending_.action);
            logObservation(pending_.action, frame);
            int zealotsIssued = static_cast<int>(std::count(commandLog_.begin(), commandLog_.end(), 3));
            if (pending_.action == 3 && zealotsIssued >= target_) {
                pending_.awaitingEnd = true;  // 종료 프레임은 onUnitComplete가 정한다
                lastWaitFrame_ = frame;
            } else {
                finishPending(true, "");
            }
        } else if (!why.empty() && why.rfind("fatal:", 0) == 0) {
            // 영원히 불가능한 명령(인구 한도 초과, 선행 건물 없음, 반복 거부)은 기다리지 않고 바로 accepted=false 로 응답한다
            finishPending(false, why.substr(6));
        } else if (Broodwar->getFrameCount() - lastWaitFrame_ >= waitEvery_) {
            lastWaitFrame_ = Broodwar->getFrameCount();
            mj::Writer w;
            w.key("type").value("wait").key("id").value(pending_.id).key("frame").value(lastWaitFrame_).key("reason").value(why);
            reply(w.str());
        }
    }
}

// ------------------------------------------------------------------ 이벤트
void BuildExecutor::onUnitCreate(Unit unit) {
    if (unit->getPlayer() != Broodwar->self()) return;
    // 건설 확인은 checkBuildWatches()가 건물 수로 한다. 여기서는 디버그 출력만
    if (unit->getType().isBuilding()) Broodwar->printf("placed %s at frame %d", unit->getType().c_str(), Broodwar->getFrameCount());
}

void BuildExecutor::onUnitComplete(Unit unit) {
    if (unit->getPlayer() != Broodwar->self()) return;
    UnitType t = unit->getType();
    if (t == UnitTypes::Protoss_Probe) {
        // 새 일꾼 배정 (A1): 일꾼/덩이 비율이 가장 낮은 완성 기지의 덩이 중 가장 덜 붐비는 곳 (분배 규칙: 2배수 채운 뒤 3배수)
        if (!patches_.empty()) {
            Unit nearNexus = nullptr;
            double bestRatio = 1e9;
            for (auto d : Broodwar->self()->getUnits()) {
                if (!d->getType().isResourceDepot() || !d->isCompleted()) continue;
                int pc = 0, wc = 0;
                for (auto m : patches_) if (m->exists() && m->getResources() > 0 && m->getDistance(d) < 320) ++pc;
                for (auto& kv : workerPatch_) if (kv.second && kv.second->exists() && kv.second->getDistance(d) < 320) ++wc;
                if (pc == 0) continue;
                double ratio = static_cast<double>(wc) / pc;
                if (ratio < bestRatio) { bestRatio = ratio; nearNexus = d; }
            }
            size_t best = 0;
            int bestLoad = 1 << 30;
            for (size_t i = 0; i < patches_.size(); ++i) {
                if (nearNexus && patches_[i]->getDistance(nearNexus) >= 320) continue;
                int load = 0;
                for (auto& kv : workerPatch_) if (kv.second == patches_[i]) ++load;
                if (load < bestLoad) { bestLoad = load; best = i; }
            }
            workerPatch_[unit->getID()] = patches_[best];
            unit->gather(patches_[best]);
        }
    } else if (t == UnitTypes::Protoss_Zealot) {
        ++zealotsCompleted_;
        if (target_ > 0 && zealotsCompleted_ >= target_ && endFrame_ < 0) {
            endFrame_ = Broodwar->getFrameCount();
            logObservation(9, endFrame_);
            Broodwar->printf("target %d reached at frame %d", target_, endFrame_);
            if (pending_.active && pending_.type == "step") {
                if (pending_.awaitingEnd) finishPending(true, "");
                else finishPending(false, "target reached before command");
            }
            episodeActive_ = false;
        }
    } else if (t == UnitTypes::Protoss_Cybernetics_Core) {
        ++cyberCores_;
    } else if (t == UnitTypes::Protoss_Nexus && unit != mainNexus_) {
        rebalanceWorkers(unit);
    } else if (t == UnitTypes::Protoss_Assimilator) {
        // 가스 일꾼 3기: 가장 가까운 미네랄 일꾼(건설 중·가스 중 제외). 이후 A1·A2 는 가스 일꾼을 건드리지 않는다
        std::vector<Unit> cands;
        for (auto u : Broodwar->self()->getUnits())
            if (u->getType().isWorker() && u->isCompleted() && !isBuilder(u) && !u->isGatheringGas() && !u->isConstructing())
                cands.push_back(u);
        std::sort(cands.begin(), cands.end(), [&](Unit a, Unit b) { return a->getDistance(unit) < b->getDistance(unit); });
        for (size_t i = 0; i < cands.size() && i < 3; ++i) cands[i]->gather(unit);
        Broodwar->printf("assimilator done: %d workers to gas", static_cast<int>(std::min<size_t>(3, cands.size())));
    }
}

void BuildExecutor::onUnitDestroy(Unit unit) {
    workerPatch_.erase(unit->getID());
    for (auto& w : watches_) if (w.builder == unit) w.builder = nullptr;
    if (unit->getPlayer() == Broodwar->self()) {
        if (unit->getType().isBuilding()) ++lostBuildings_; else ++lostUnits_;
        lastLossFrame_ = Broodwar->getFrameCount();
    }
}

void BuildExecutor::onSendText(std::string text) {
    if (text == "/status") {
        Broodwar->printf("frame %d target %d zealots %d pending %s", Broodwar->getFrameCount(), target_, zealotsCompleted_, pending_.active ? pending_.type.c_str() : "-");
        return;
    }
    // 사람이 채팅창에 친 글을 클라이언트에 그대로 전달한다 (라이브 모드의 목표 입력 통로: 예 "질럿 3")
    Broodwar->sendText("%s", text.c_str());
    if (server_.connected()) {
        mj::Writer w;
        w.key("type").value("text").key("frame").value(Broodwar->getFrameCount()).key("text").value(text);
        reply(w.str());
    }
}

// ------------------------------------------------------------------ 프로토콜
void BuildExecutor::handleMessages() {
    std::string line;
    // 한 프레임에 여러 줄을 처리한다(상태 조회가 명령 뒤에 밀리지 않게). 단 step은 하나만 받는다
    for (int n = 0; n < 16 && server_.pollLine(line); ++n) handleMessage(line);
}

void BuildExecutor::handleMessage(const std::string& line) {
    mj::Object m;
    if (!mj::parseObject(line, m)) { sendError(-1, "JSON 오류", false); return; }
    std::string type = m["type"].asString();
    int id = m.count("id") ? m["id"].asInt(-1) : -1;

    if ((type == "step" || type == "reset") && id >= 0 && id == lastId_) {
        reply(lastReply_);  // 같은 id 재전송: 명령을 두 번 내리지 않는다
        return;
    }
    if (type == "hello") {
        if (m["version"].asInt() != kProtocolVersion) { sendError(id, "version 1 필요", true); return; }
        mj::Writer w;
        w.key("type").value("hello").key("id").value(id).key("version").value(kProtocolVersion);
#ifdef OPENBW
        w.key("backend").value("openbw");
#else
        w.key("backend").value("bwapi-1.16.1");
#endif
        w.key("game").value("bw");
        w.key("actions").raw("{\"0\":\"worker\",\"1\":\"pylon\",\"2\":\"gateway\",\"3\":\"zealot\",\"5\":\"assimilator\","
                             "\"6\":\"core\",\"7\":\"dragoon\",\"10\":\"citadel\",\"11\":\"archives\",\"12\":\"high_templar\","
                             "\"13\":\"dark_templar\",\"4\":\"nexus\",\"14\":\"forge\",\"15\":\"up_weapons\","
                             "\"16\":\"up_armor\",\"17\":\"up_shields\",\"8\":\"wait\"}");
        w.key("latency_frames").value(Broodwar->getLatencyFrames());
        w.key("end_includes_lag").value(false);
        w.key("live_v2").value(true);  // request / observe / cancel 지원
        reply(w.str());
    } else if (type == "reset") {
        target_ = m["target"].asInt(0);
        if (target_ <= 0) { sendError(id, "target 필요", false); return; }
        seed_ = m.count("seed") ? m["seed"].asInt(-1) : -1;
        // 라이브 모드(사람과 함께): 게임을 재시작하지도 멈추지도 않는다. target 은 게임 시작부터 센 절대 질럿 수.
        // 보통 속도·화면 켬. 사람의 채팅은 text 메시지로 전달된다.
        if (m.count("live") && m["live"].kind == mj::Value::Bool && m["live"].b) {
            if (pending_.active && pending_.type == "step") { sendError(id, "busy: 이전 명령 대기 중", false); return; }
            live_ = true;
            endFrame_ = -1;
            pending_ = Pending();
            Broodwar->setGUI(true);
            Broodwar->setLocalSpeed(-1);
            curSpeed_ = -1;
            lastId_ = id;
            lastReply_ = obsJson(id, true, false, -1, "");
            reply(lastReply_);
            episodeActive_ = true;
            return;
        }
        live_ = false;
        pending_ = Pending();
        pending_.active = true;
        pending_.id = id;
        pending_.type = "reset";
        episodeActive_ = false;
        if (Broodwar->getFrameCount() > 0 || !commandLog_.empty() || endFrame_ >= 0) {
            // 게임 재시작. BWAPI가 이 객체를 지우고 새로 만들므로 응답에 필요한 값은 공유 상태에 둔다
            sh_.resetPending = true;
            sh_.resetId = id;
            sh_.resetTarget = target_;
            sh_.resetSeed = seed_;
            wantRestart_ = true;  // 다음 onStart에서 응답
        } else {
            lastId_ = id;
            lastReply_ = obsJson(id, true, false, -1, "");
            reply(lastReply_);
            pending_ = Pending();
            episodeActive_ = true;
        }
    } else if (type == "step") {
        if (pending_.active) { sendError(id, "busy: 이전 명령 대기 중", false); return; }
        int action = m["action"].asInt(-1);
        if (action == 9) { reply(obsJson(id, false, true, endFrame_, "ended by agent")); return; }
        if (action != 8 && !knownAction(action)) { sendError(id, "모르는 action", false); return; }
        if (action == 8) {
            // 대기: frames 프레임 뒤의 관측을 돌려준다(측정·대기용). 명령열 기록에는 넣지 않는다
            int frames = m.count("frames") ? m["frames"].asInt(0) : waitEvery_;
            if (frames <= 0) { sendError(id, "frames 필요", false); return; }
            pending_ = Pending();
            pending_.active = true;
            pending_.id = id;
            pending_.type = "step";
            pending_.action = 8;
            pending_.sinceFrame = Broodwar->getFrameCount();
            pending_.untilFrame = pending_.sinceFrame + frames;
            lastWaitFrame_ = pending_.sinceFrame;
            return;
        }
        pending_ = Pending();
        pending_.active = true;
        pending_.id = id;
        pending_.type = "step";
        pending_.action = action;
        pending_.sinceFrame = Broodwar->getFrameCount();
        lastWaitFrame_ = pending_.sinceFrame;
    } else if (type == "stop") {
        pending_ = Pending();
        episodeActive_ = false;
        mj::Writer w;
        w.key("type").value("status").key("id").value(id).key("stopped").value(true);
        reply(w.str());
    } else if (type == "request") {
        // 라이브 v2: 비동기 요청. 즉시 ack 하고 실행은 실행기가 책임진다(순서대로, 조건이 되는 첫 프레임에)
        int action = m["action"].asInt(-1);
        mj::Writer w;
        w.key("type").value("ack").key("id").value(id);
        if (!live_) { w.key("accepted").value(false).key("reason").value("live mode only"); reply(w.str()); return; }
        if (!knownAction(action)) { w.key("accepted").value(false).key("reason").value("unknown action"); reply(w.str()); return; }
        Request r;
        // 실행기가 고유 id 를 매긴다 (클라이언트 메시지 id 는 재접속 때 겹칠 수 있다)
        r.id = ++sh_.nextRequestId; r.action = action; r.state = "queued"; r.frameIn = Broodwar->getFrameCount();
        requests_.push_back(r);
        w.key("accepted").value(true).key("request_id").value(r.id);
        reply(w.str());
    } else if (type == "observe") {
        reply(snapshotJson(id));
    } else if (type == "cancel") {
        // 아직 실행하지 않은(queued) 요청을 지운다. request_id 가 있으면 그것만, 없으면 전부. 이미 나간 건설은 실행기가 끝까지 책임진다
        int rid = m.count("request_id") ? m["request_id"].asInt(-1) : -1;
        int n = 0;
        for (auto& r : requests_)
            if (r.state == "queued" && (rid < 0 || r.id == rid)) { r.state = "failed"; r.reason = "cancelled"; r.doneFrame = Broodwar->getFrameCount(); ++n; }
        mj::Writer w;
        w.key("type").value("status").key("id").value(id).key("cancelled").value(n);
        reply(w.str());
    } else if (type == "army") {
        // 전체 병력 명령. op=attack: 일꾼·건물 제외 모든 완성 병력이 적 본진(모르면 보이는 적 건물, 그것도 없으면 맵 중앙)으로 공격 이동
        std::string op = m["op"].asString();
        int sent = 0;
        if (op == "attack") {
            Position target = enemyStart_.isValid() ? Position(enemyStart_) : Position(Broodwar->mapWidth() * 16, Broodwar->mapHeight() * 16);
            if (Broodwar->enemy()) {
                Unit nearest = nullptr;
                for (auto e : Broodwar->enemy()->getUnits())
                    if (e->exists() && e->getType().isBuilding() && mainNexus_ && (!nearest || e->getDistance(mainNexus_) < nearest->getDistance(mainNexus_))) nearest = e;
                if (nearest) target = nearest->getPosition();
            }
            for (auto u : Broodwar->self()->getUnits())
                if (u->isCompleted() && !u->getType().isWorker() && !u->getType().isBuilding() && u->canAttackMove()) { u->attack(target); ++sent; }
        }
        mj::Writer w;
        w.key("type").value("status").key("id").value(id).key("op").value(op).key("units").value(sent);
        reply(w.str());
    } else if (type == "debug") {
        // 시험용(라이브): 사람의 행동을 흉내 낸다. spend = 요청 밖에서 명령(사람이 돈 씀), cancel_building = 건설 중인 건물 취소(손실),
        // attack_own = 자기 병력으로 자기 건물 공격(손실 유도)
        std::string op = m["op"].asString();
        std::string ut = m["unit_type"].asString();
        std::string result = "noop";
        if (op == "spend") {
            // 사람은 예비 자원을 지키지 않는다: 예비를 잠시 0 으로 두고 실행해야 '예비 해제' 시험이 성립한다
            // (2026-11-08: 시험 지출이 예비를 지켜 남는 돈만 써서 해제가 확인되지 않았다)
            std::string why;
            int keepM = reserveMinerals_, keepG = reserveGas_;
            reserveMinerals_ = reserveGas_ = 0;
            bool ok = tryExecute(m["action"].asInt(-1), why);
            reserveMinerals_ = keepM;
            reserveGas_ = keepG;
            result = ok ? "spent" : ("refused: " + why);
        } else if (op == "cancel_building") {
            for (auto u : Broodwar->self()->getUnits())
                if (u->getType().isBuilding() && !u->isCompleted() && (ut.empty() || std::string(u->getType().c_str()) == ut)) { u->cancelConstruction(); result = std::string("cancelled ") + u->getType().c_str(); break; }
        } else if (op == "attack_own") {
            Unit target = nullptr;
            for (auto u : Broodwar->self()->getUnits())
                if (u->getType().isBuilding() && u->isCompleted() && std::string(u->getType().c_str()) == ut && u != mainNexus_) { target = u; break; }
            int n = m["attackers"].asInt(4), sent = 0;
            if (target)
                for (auto u : Broodwar->self()->getUnits())
                    if (sent < n && !u->getType().isBuilding() && !u->getType().isWorker() && u->isCompleted()) { u->attack(target); ++sent; }
            result = target ? ("attacking with " + std::to_string(sent)) : "no target";
        }
        mj::Writer w;
        w.key("type").value("status").key("id").value(id).key("debug").value(result);
        reply(w.str());
    } else if (type == "rally") {
        // 집결지. op=here: 지금 화면 중앙(사람이 보고 있는 곳, 땅으로 갈 수 있는 가장 가까운 타일), auto: 자동 규칙, off: 관리 끔(게이트 집결지 해제)
        std::string op = m["op"].asString();
        if (op == "here") {
            Position sc = Broodwar->getScreenPosition() + Position(320, 180);  // 화면 640x480 중 아래 콘솔을 뺀 지도 영역의 중앙
            Position snapped = snapReachable(sc, 8);
            if (snapped.isValid()) { rallyMode_ = 1; rallyManual_ = snapped; }
        } else if (op == "auto") {
            rallyMode_ = 0;
        } else if (op == "off") {
            rallyMode_ = 2;
            rallyNow_ = Positions::Invalid;
            for (auto u : Broodwar->self()->getUnits())
                if (u->getType() == UnitTypes::Protoss_Gateway && u->isCompleted()) u->setRallyPoint(u);
        }
        lastRallyFrame_ = -1000;  // 다음 프레임에 바로 반영
        mj::Writer w;
        w.key("type").value("status").key("id").value(id).key("op").value(op).key("mode").value(rallyMode_)
         .key("x").value(rallyMode_ == 1 ? rallyManual_.x : -1).key("y").value(rallyMode_ == 1 ? rallyManual_.y : -1);
        reply(w.str());
    } else if (type == "rebalance") {
        // 가장 최근 완성된 멀티 넥서스로 본진 초과 일꾼을 옮긴다 (사람이 직접 지은 멀티도 됨)
        Unit depot = nullptr;
        for (auto u : Broodwar->self()->getUnits())
            if (u->getType() == UnitTypes::Protoss_Nexus && u->isCompleted() && u != mainNexus_ && (!depot || u->getID() > depot->getID())) depot = u;
        if (depot) rebalanceWorkers(depot);
        mj::Writer w;
        w.key("type").value("status").key("id").value(id).key("rebalanced").value(depot != nullptr);
        reply(w.str());
    } else if (type == "progress") {
        // 우측 하단 진행 막대. frac 0~1 (1000분율 정수로 받는다), text 한 줄
        progressText_ = m["text"].asString();
        progressPermille_ = std::max(-1, std::min(1000, m["permille"].asInt(-1)));
        mj::Writer w;
        w.key("type").value("status").key("id").value(id).key("progress").value(true);
        reply(w.str());
    } else if (type == "hud") {
        // 화면 왼쪽 위에 띄울 상태 글(클라이언트가 갱신). 줄바꿈은 '|'
        hudText_ = m["text"].asString();
        mj::Writer w;
        w.key("type").value("status").key("id").value(id).key("hud").value(true);
        reply(w.str());
    } else if (type == "reserve") {
        // 예비 자원: 이 양은 쓰지 않는다 (사람이 쓸 몫). 명령 시점 판정에서 뺀다
        reserveMinerals_ = std::max(0, m["minerals"].asInt(0));
        reserveGas_ = std::max(0, m["gas"].asInt(0));
        mj::Writer w;
        w.key("type").value("status").key("id").value(id).key("reserve_minerals").value(reserveMinerals_).key("reserve_gas").value(reserveGas_);
        reply(w.str());
    } else if (type == "status") {
        mj::Writer w;
        w.key("type").value("status").key("id").value(id).key("frame").value(Broodwar->getFrameCount())
         .key("target").value(target_).key("zealots").value(zealotsCompleted_)
         .key("pending").value(pending_.active ? pending_.type : std::string("-"))
         .key("fps").value(Broodwar->getFPS()).key("latency_frames").value(Broodwar->getLatencyFrames());
        reply(w.str());
    } else if (type == "bye") {
        pending_ = Pending();
        episodeActive_ = false;
    } else {
        sendError(id, "모르는 type " + type, false);
    }
}

void BuildExecutor::reply(const std::string& json) { server_.sendLine(json); }

void BuildExecutor::sendError(int id, const std::string& msg, bool fatal) {
    mj::Writer w;
    w.key("type").value("error").key("id").value(id).key("message").value(msg).key("fatal").value(fatal);
    reply(w.str());
}

void BuildExecutor::finishPending(bool accepted, const std::string& error) {
    bool done = endFrame_ >= 0 || !accepted;
    std::string out = obsJson(pending_.id, accepted, done, endFrame_, error);
    lastId_ = pending_.id;
    lastReply_ = out;
    pending_ = Pending();
    if (done) episodeActive_ = false;  // 다음 reset까지 프레임 블로킹 해제 (게임은 그냥 흘러간다)
    reply(out);
}

std::vector<int> BuildExecutor::stateVector() const {
    Player me = Broodwar->self();
    // [minerals, gas, supply_used, supply_cap, workers, nexus, tech, gateways, zealots, iteration]
    return {me->minerals(), me->gas(), me->supplyUsed() / 2, me->supplyTotal() / 2,
            countCompleted(UnitTypes::Protoss_Probe), countAll(UnitTypes::Protoss_Nexus), cyberCores_,
            countAll(UnitTypes::Protoss_Gateway), zealotsCompleted_, Broodwar->getFrameCount()};
}

// ---- 라이브 v2
BuildExecutor::Request* BuildExecutor::findRequest(int id) {
    if (id < 0) return nullptr;
    for (auto& r : requests_) if (r.id == id) return &r;
    return nullptr;
}

// 큐의 첫 요청을 조건이 되는 첫 프레임에 실행한다(순서 보존). 건물은 놓일 때까지 issued, 유닛은 큐 진입이 done.
void BuildExecutor::processRequests() {
    Request* r = nullptr;
    for (auto& x : requests_) if (x.state == "queued") { r = &x; break; }
    if (!r) { pending_.retries = 0; return; }
    int frame = Broodwar->getFrameCount();
    size_t before = watches_.size();
    std::string why;
    if (tryExecute(r->action, why)) {
        commandLog_.push_back(r->action);
        logObservation(r->action, frame);
        if (typeOf(r->action).isBuilding()) {
            r->state = "issued";
            r->issuedFrame = frame;
            r->reason = "";
            if (watches_.size() > before) watches_.back().requestId = r->id;
        } else {
            r->state = "done";
            r->issuedFrame = r->doneFrame = frame;
            r->reason = "";
        }
        pending_.retries = 0;
    } else if (why.rfind("fatal:", 0) == 0) {
        r->state = "failed";
        r->reason = why.substr(6);
        r->doneFrame = frame;
        pending_.retries = 0;
    } else {
        r->reason = why;  // 대기 사유 (minerals, supply, X not complete ...)
        lastWhy_ = why;
        // 맨 앞이 돈이 아닌 것을 기다리면(건물 완성, 포지 사용 중, 정찰 대기 ...) 뒤의 일꾼·파일런 요청 하나를
        // 맨 앞 요청 비용을 남긴 채 먼저 실행한다. 목표 순서는 제어 루프가 지키므로(목표 하나씩 보냄) 이 범위면 안전하다
        bool resourceWait = why == "minerals" || why == "gas" || why == "supply" || why.rfind("nexus queue", 0) == 0;
        if (!resourceWait) {
            UnitType ht = typeOf(r->action);
            UpgradeType hu = upgradeOf(r->action);
            int holdM = ht != UnitTypes::None ? ht.mineralPrice() : (hu != UpgradeTypes::None ? hu.mineralPrice(Broodwar->self()->getUpgradeLevel(hu) + 1) : 0);
            for (auto& x : requests_) {
                if (&x == r || x.state != "queued" || (x.action != 0 && x.action != 1)) continue;
                reserveMinerals_ += holdM;
                size_t before2 = watches_.size();
                std::string why2;
                bool ok = tryExecute(x.action, why2);
                reserveMinerals_ -= holdM;
                if (ok) {
                    commandLog_.push_back(x.action);
                    if (typeOf(x.action).isBuilding()) { x.state = "issued"; x.issuedFrame = frame; if (watches_.size() > before2) watches_.back().requestId = x.id; }
                    else { x.state = "done"; x.issuedFrame = x.doneFrame = frame; }
                    x.reason = "";
                } else {
                    x.reason = why2;
                }
                break;  // 한 프레임에 하나만
            }
        }
    }
    // 오래된 완료·실패 요청은 정리 (최근 64개만 보관)
    if (requests_.size() > 64) {
        size_t keep = 0;
        for (auto& x : requests_) if (x.state == "queued" || x.state == "issued") ++keep;
        while (requests_.size() > 64 && requests_.size() > keep) {
            bool erased = false;
            for (size_t i = 0; i < requests_.size(); ++i)
                if (requests_[i].state == "done" || requests_[i].state == "failed") { requests_.erase(requests_.begin() + static_cast<long>(i)); erased = true; break; }
            if (!erased) break;
        }
    }
}

std::string BuildExecutor::requestsJson() const {
    std::string out = "[";
    bool first = true;
    for (auto& r : requests_) {
        mj::Writer j;
        j.key("id").value(r.id).key("action").value(r.action).key("state").value(r.state).key("reason").value(r.reason)
         .key("frame_in").value(r.frameIn).key("issued_frame").value(r.issuedFrame).key("done_frame").value(r.doneFrame);
        out += std::string(first ? "" : ",") + j.str();
        first = false;
    }
    return out + "]";
}

// 건물 상태: {"pylon":{"ready":n,"building":[남은],"pending":[경과]}, ...} — techJson 과 같은 꼴, 전 종류
std::string BuildExecutor::buildingsJson() const {
    struct E { const char* key; UnitType t; } list[] = {
        {"nexus", UnitTypes::Protoss_Nexus}, {"pylon", UnitTypes::Protoss_Pylon}, {"gateway", UnitTypes::Protoss_Gateway},
        {"assimilator", UnitTypes::Protoss_Assimilator}, {"core", UnitTypes::Protoss_Cybernetics_Core},
        {"citadel", UnitTypes::Protoss_Citadel_of_Adun}, {"archives", UnitTypes::Protoss_Templar_Archives},
        {"forge", UnitTypes::Protoss_Forge}};
    int frame = Broodwar->getFrameCount();
    std::string out = "{";
    bool first = true;
    for (auto& e : list) {
        std::vector<int> building, pending;
        int ready = 0;
        for (auto u : Broodwar->self()->getUnits())
            if (u->getType() == e.t) { if (u->isCompleted()) ++ready; else building.push_back(u->getRemainingBuildTime()); }
        for (auto& w : watches_) if (w.type == e.t) pending.push_back(frame - w.issuedFrame);
        mj::Writer w;
        w.key("ready").value(ready).key("building").intArray(building).key("pending").intArray(pending);
        out += std::string(first ? "" : ",") + "\"" + e.key + "\":" + w.str();
        first = false;
    }
    return out + "}";
}

// 업그레이드 상태: {"weapons":{"level":n,"max":3,"upgrading":bool,"remaining":f}, "armor":..., "shields":...}
std::string BuildExecutor::upgradesJson() const {
    struct E { const char* key; UpgradeType u; } list[] = {
        {"weapons", UpgradeTypes::Protoss_Ground_Weapons}, {"armor", UpgradeTypes::Protoss_Ground_Armor}, {"shields", UpgradeTypes::Protoss_Plasma_Shields}};
    Player me = Broodwar->self();
    std::string out = "{";
    bool first = true;
    for (auto& e : list) {
        int remaining = 0;
        for (auto u : me->getUnits()) if (u->isUpgrading() && u->getUpgrade() == e.u) remaining = u->getRemainingUpgradeTime();
        mj::Writer w;
        w.key("level").value(me->getUpgradeLevel(e.u)).key("max").value(me->getMaxUpgradeLevel(e.u))
         .key("upgrading").value(me->isUpgrading(e.u)).key("remaining").value(remaining);
        out += std::string(first ? "" : ",") + "\"" + e.key + "\":" + w.str();
        first = false;
    }
    return out + "}";
}

// 완전한 스냅샷. 계획은 이것만 보고 세운다. 내부 누적값 없이 매번 게임에서 계산한다.
std::string BuildExecutor::snapshotJson(int id) {
    Player me = Broodwar->self();
    int frame = Broodwar->getFrameCount();
    int reservedM = 0, reservedG = 0;
    for (auto& w : watches_) { reservedM += w.type.mineralPrice(); reservedG += w.type.gasPrice(); }
    // 일꾼 분류
    int wTotal = 0, wMin = 0, wGas = 0, wBuild = 0, wIdle = 0;
    for (auto u : me->getUnits()) {
        if (!u->getType().isWorker() || !u->isCompleted()) continue;
        ++wTotal;
        if (isBuilder(u) || u->isConstructing()) ++wBuild;
        else if (u->isGatheringGas() || u->isCarryingGas()) ++wGas;
        else if (u->isGatheringMinerals() || u->isCarryingMinerals()) ++wMin;
        else if (u->isIdle()) ++wIdle;
    }
    // 기지
    std::string bases = "[";
    bool firstB = true;
    for (auto d : me->getUnits()) {
        if (!d->getType().isResourceDepot()) continue;
        int pc = 0, wc = 0;
        for (auto m : Broodwar->getMinerals()) if (m->exists() && m->getResources() > 0 && m->getDistance(d) < 320) ++pc;
        for (auto& kv : workerPatch_) if (kv.second && kv.second->exists() && kv.second->getDistance(d) < 320) ++wc;
        mj::Writer b;
        b.key("id").value(d->getID()).key("done").value(d->isCompleted()).key("remaining").value(d->isCompleted() ? 0 : d->getRemainingBuildTime())
         .key("x").value(d->getTilePosition().x).key("y").value(d->getTilePosition().y).key("patches").value(pc).key("workers").value(wc)
         .key("queue").value(static_cast<int>(d->getTrainingQueue().size())).key("queue_remaining").value(d->getTrainingQueue().empty() ? 0 : d->getRemainingTrainTime());
        bases += std::string(firstB ? "" : ",") + b.str();
        firstB = false;
    }
    bases += "]";
    // 게이트 큐, 병력 수(완성 + 생산 중)
    std::vector<int> gateQueue, gateRemaining;
    std::map<std::string, int> done, prod;
    const char* names[] = {"zealot", "dragoon", "high_templar", "dark_templar", "probe"};
    UnitType types[] = {UnitTypes::Protoss_Zealot, UnitTypes::Protoss_Dragoon, UnitTypes::Protoss_High_Templar, UnitTypes::Protoss_Dark_Templar, UnitTypes::Protoss_Probe};
    for (int k = 0; k < 5; ++k) { done[names[k]] = 0; prod[names[k]] = 0; }
    for (auto u : me->getUnits()) {
        for (int k = 0; k < 5; ++k) if (u->getType() == types[k] && u->isCompleted()) ++done[names[k]];
        if (u->getType() == UnitTypes::Protoss_Gateway && u->isCompleted() && u->isPowered()) {
            int q = static_cast<int>(u->getTrainingQueue().size());
            gateQueue.push_back(q);
            gateRemaining.push_back(q > 0 ? u->getRemainingTrainTime() : 0);
        }
        if (u->getType().isBuilding())
            for (auto qt : u->getTrainingQueue())
                for (int k = 0; k < 5; ++k) if (qt == types[k]) ++prod[names[k]];
    }
    std::string units = "{";
    for (int k = 0; k < 5; ++k)
        units += std::string(k ? "," : "") + "\"" + names[k] + "\":{\"done\":" + std::to_string(done[names[k]]) + ",\"in_production\":" + std::to_string(prod[names[k]])
               + ",\"dead\":" + std::to_string(me->deadUnitCount(types[k])) + "}";
    units += "}";
    // 위협: 자기 건물 반경 800px 안의 적 유닛(보이는 것)
    int enemiesNear = 0;
    if (Broodwar->enemy()) {
        for (auto e : Broodwar->enemy()->getUnits()) {
            if (!e->exists() || e->getType().isBuilding()) continue;
            for (auto b : me->getUnits())
                if (b->getType().isBuilding() && e->getDistance(b) < 800) { ++enemiesNear; break; }
        }
    }
    mj::Writer w;
    w.key("type").value("snapshot").key("id").value(id).key("frame").value(frame).key("live").value(live_).key("game_id").value(gameId_)
     .key("rally").raw(std::string("{\"mode\":\"") + (rallyMode_ == 0 ? "auto" : rallyMode_ == 1 ? "manual" : "off") + "\",\"x\":"
                       + std::to_string(rallyNow_.isValid() ? rallyNow_.x : -1) + ",\"y\":" + std::to_string(rallyNow_.isValid() ? rallyNow_.y : -1) + "}")
     .key("state").intArray(stateVector())
     .key("minerals").value(me->minerals()).key("gas").value(me->gas())
     .key("reserved_minerals").value(reservedM + reserveMinerals_).key("reserved_gas").value(reservedG + reserveGas_)
     .key("reserve_minerals").value(reserveMinerals_).key("reserve_gas").value(reserveGas_)
     .key("supply_used").value(me->supplyUsed() / 2).key("supply_in_use").value(supplyInUse() / 2).key("supply_total").value(me->supplyTotal() / 2)
     .key("workers").raw("{\"total\":" + std::to_string(wTotal) + ",\"minerals\":" + std::to_string(wMin) + ",\"gas\":" + std::to_string(wGas)
                         + ",\"building\":" + std::to_string(wBuild) + ",\"idle\":" + std::to_string(wIdle) + "}")
     .key("bases").raw(bases)
     .key("buildings").raw(buildingsJson())
     .key("gate_queue").intArray(gateQueue).key("gate_remaining").intArray(gateRemaining)
     .key("units").raw(units)
     .key("upgrades").raw(upgradesJson())
     .key("requests").raw(requestsJson())
     .key("watches").raw(watchesJson())
     .key("abandoned").raw(abandonedJson())
     .key("threat").raw("{\"enemies_near\":" + std::to_string(enemiesNear) + ",\"lost_units\":" + std::to_string(lostUnits_)
                        + ",\"lost_buildings\":" + std::to_string(lostBuildings_) + ",\"last_loss_frame\":" + std::to_string(lastLossFrame_) + "}");
    return w.str();
}

// 일꾼 분배 규칙(사용자 결정): 어시밀레이터마다 가스 3기 유지. 미네랄은 기지마다 덩이 2배수를 먼저 채우고 3배수까지.
// 3배수를 넘는 기지 → 2배수 미만 기지로, 모두 2배수 이상이면 3배수 미만 기지로. 한 번에 4기까지만 옮긴다.
// p 근처(반경 radius 타일)에서 본진에서 땅으로 갈 수 있는(BFS 거리 있음) 가장 가까운 타일 중심. 없으면 Invalid
Position BuildExecutor::snapReachable(Position p, int radius) const {
    const std::vector<int>& gd = groundDistance();
    const int W = Broodwar->mapWidth(), H = Broodwar->mapHeight();
    if (gd.empty() || !p.isValid()) return Positions::Invalid;
    TilePosition c0(p);
    int best = -1, bestD = 1 << 30;
    for (int dy = -radius; dy <= radius; ++dy)
        for (int dx = -radius; dx <= radius; ++dx) {
            int x = c0.x + dx, y = c0.y + dy;
            if (x < 0 || y < 0 || x >= W || y >= H || gd[static_cast<size_t>(y * W + x)] < 0) continue;
            int d = dx * dx + dy * dy;
            if (d < bestD) { bestD = d; best = y * W + x; }
        }
    if (best < 0) return Positions::Invalid;
    return Position(TilePosition(best % W, best / W)) + Position(16, 16);
}

// 자동 집결지 규칙 (2026-11-08):
//  - 멀티(본진 밖 넥서스, 짓는 중 포함)가 있으면: 본진에서 땅으로 가장 가까운 멀티 넥서스에서 적 본진 쪽으로 4타일
//  - 없으면: 본진 → 앞마당 자리 땅 길의 한가운데 (보통 본진 언덕길 근처)
// 지형 분석 라이브러리 없이 BFS 땅 거리만 쓴다. 맞지 않으면 rally 명령으로 화면 중앙을 지정한다
Position BuildExecutor::rallyAuto() const {
    const std::vector<int>& gd = groundDistance();
    const int W = Broodwar->mapWidth(), H = Broodwar->mapHeight();
    if (gd.empty() || !mainNexus_) return Positions::Invalid;
    // 넥서스(4x3) 둘레에서 BFS 거리가 가장 작은 타일 (넥서스 타일 자체도 정적 지형으로는 걸을 수 있다)
    auto nearest = [&](TilePosition tp, int* outIdx) {
        int best = 1 << 30, idx = -1;
        for (int dy = -2; dy <= 4; ++dy)
            for (int dx = -2; dx <= 5; ++dx) {
                int x = tp.x + dx, y = tp.y + dy;
                if (x < 0 || y < 0 || x >= W || y >= H) continue;
                int v = gd[static_cast<size_t>(y * W + x)];
                if (v >= 0 && v < best) { best = v; idx = y * W + x; }
            }
        if (outIdx) *outIdx = idx;
        return best;
    };
    Unit natural = nullptr;
    int natD = 1 << 30;
    for (auto u : Broodwar->self()->getUnits()) {
        if (!u->getType().isResourceDepot() || u == mainNexus_) continue;
        int d = nearest(u->getTilePosition(), nullptr);
        if (d < natD) { natD = d; natural = u; }
    }
    if (natural) {
        Position from = natural->getPosition(), to = Position(enemyStart_) + Position(64, 48);
        double len = std::max(1.0, from.getDistance(to));
        Position p(from.x + static_cast<int>((to.x - from.x) * 128.0 / len), from.y + static_cast<int>((to.y - from.y) * 128.0 / len));
        return snapReachable(p, 4);
    }
    TilePosition site = findExpansion();
    if (!site.isValid()) return Positions::Invalid;
    // 앞마당 자리에서 거리가 1씩 줄어드는 이웃을 따라 본진 쪽으로 절반만 내려간다 (최단 땅 길의 한가운데)
    int cur = -1;
    int curD = nearest(site, &cur);
    if (cur < 0) return Positions::Invalid;
    const int half = curD / 2;
    while (gd[static_cast<size_t>(cur)] > half) {
        int x = cur % W, y = cur / W, next = -1;
        const int nx[4] = {x + 1, x - 1, x, x}, ny[4] = {y, y, y + 1, y - 1};
        for (int k = 0; k < 4; ++k) {
            if (nx[k] < 0 || ny[k] < 0 || nx[k] >= W || ny[k] >= H) continue;
            int j = ny[k] * W + nx[k];
            if (gd[static_cast<size_t>(j)] == gd[static_cast<size_t>(cur)] - 1) { next = j; break; }
        }
        if (next < 0) break;
        cur = next;
    }
    return Position(TilePosition(cur % W, cur / W)) + Position(16, 16);
}

// 완성된 게이트의 집결지를 지금 규칙의 자리로 맞춘다 (다를 때만 명령: 매번 명령하면 APM 낭비)
void BuildExecutor::updateRally() {
    if (rallyMode_ == 2) return;
    Position p = rallyMode_ == 1 ? rallyManual_ : rallyAuto();
    rallyNow_ = p;
    if (!p.isValid()) return;
    for (auto u : Broodwar->self()->getUnits()) {
        if (u->getType() != UnitTypes::Protoss_Gateway || !u->isCompleted()) continue;
        Position cur = u->getRallyPosition();
        if (u->getRallyUnit() || !cur.isValid() || cur.getApproxDistance(p) > 32) u->setRallyPoint(p);
    }
}

void BuildExecutor::rebalanceBases() {
    Player me = Broodwar->self();
    // 가스 보충
    for (auto a : me->getUnits()) {
        if (a->getType() != UnitTypes::Protoss_Assimilator || !a->isCompleted()) continue;
        int gasWorkers = 0;
        for (auto u : me->getUnits()) if (u->getType().isWorker() && (u->isGatheringGas() || u->isCarryingGas()) && u->getDistance(a) < 400) ++gasWorkers;
        std::vector<Unit> cands;
        for (auto u : me->getUnits())
            if (u->getType().isWorker() && u->isCompleted() && !isBuilder(u) && !u->isConstructing() && !u->isGatheringGas() && !u->isCarryingGas()
                && !u->isCarryingMinerals() && u->getDistance(a) < 600) cands.push_back(u);
        std::sort(cands.begin(), cands.end(), [&](Unit x, Unit y) { return x->getDistance(a) < y->getDistance(a); });
        for (size_t i = 0; i < cands.size() && gasWorkers < 3; ++i, ++gasWorkers) cands[i]->gather(a);
    }
    // 기지별 미네랄 일꾼
    struct Base { Unit depot; int patches; std::vector<Unit> workers; std::vector<Unit> patchUnits; };
    std::vector<Base> bases;
    for (auto d : me->getUnits()) {
        if (!d->getType().isResourceDepot() || !d->isCompleted()) continue;
        Base b; b.depot = d; b.patches = 0;
        for (auto m : Broodwar->getMinerals()) if (m->exists() && m->getResources() > 0 && m->getDistance(d) < 320) { ++b.patches; b.patchUnits.push_back(m); }
        if (b.patches == 0) continue;
        for (auto u : me->getUnits())
            if (u->getType().isWorker() && u->isCompleted() && !isBuilder(u) && !u->isConstructing() && !u->isGatheringGas() && !u->isCarryingGas()
                && u->getDistance(d) < 400) b.workers.push_back(u);
        bases.push_back(b);
    }
    if (bases.size() < 2) return;
    int moves = 0;
    const int kMaxMoves = 12;  // 앞마당 활성화를 늦추지 않게 한 번에 넉넉히 옮긴다 (2026-11-08: 4기씩이라 늦었다)
    for (int pass = 0; pass < 2 && moves < kMaxMoves; ++pass) {
        int fillTo = pass == 0 ? 2 : 3;     // 1차: 2배수 미만 기지 채우기, 2차: 3배수 미만 기지 채우기
        int takeAbove = pass == 0 ? 2 : 3;  // 1차: 2배수 넘는 기지에서, 2차: 3배수 넘는 기지에서
        for (auto& recv : bases) {
            while (moves < kMaxMoves && static_cast<int>(recv.workers.size()) < fillTo * recv.patches) {
                Base* donor = nullptr;
                for (auto& b : bases) if (&b != &recv && static_cast<int>(b.workers.size()) > takeAbove * b.patches && (!donor || b.workers.size() > donor->workers.size())) donor = &b;
                if (!donor) break;
                // 빈손 우선
                size_t pick = 0;
                for (size_t i = 0; i < donor->workers.size(); ++i) if (!donor->workers[i]->isCarryingMinerals()) { pick = i; break; }
                Unit u = donor->workers[pick];
                Unit target = recv.patchUnits[static_cast<size_t>(moves) % recv.patchUnits.size()];
                workerPatch_[u->getID()] = target;
                u->gather(target);
                recv.workers.push_back(u);
                donor->workers.erase(donor->workers.begin() + static_cast<long>(pick));
                ++moves;
            }
        }
    }
}

// 기술 건물 상태: {"assimilator":{"ready":n,"building":[남은프레임...],"pending":[경과프레임...]}, "core":..., "citadel":..., "archives":...}
std::string BuildExecutor::techJson() const {
    struct E { const char* key; UnitType t; } list[] = {
        {"assimilator", UnitTypes::Protoss_Assimilator}, {"core", UnitTypes::Protoss_Cybernetics_Core},
        {"citadel", UnitTypes::Protoss_Citadel_of_Adun}, {"archives", UnitTypes::Protoss_Templar_Archives},
        {"nexus", UnitTypes::Protoss_Nexus}};
    int frame = Broodwar->getFrameCount();
    std::string out = "{";
    bool first = true;
    for (auto& e : list) {
        std::vector<int> building, pending;
        int ready = 0;
        for (auto u : Broodwar->self()->getUnits())
            if (u->getType() == e.t) { if (u->isCompleted()) ++ready; else building.push_back(u->getRemainingBuildTime()); }
        for (auto& w : watches_) if (w.type == e.t) pending.push_back(frame - w.issuedFrame);
        mj::Writer w;
        w.key("ready").value(ready).key("building").intArray(building).key("pending").intArray(pending);
        out += std::string(first ? "" : ",") + "\"" + e.key + "\":" + w.str();
        first = false;
    }
    return out + "}";
}

// 건설 감시 상태: [{"type":"Protoss_Citadel_of_Adun","age":f,"retries":n,"builder":"idle|moving|none"}, ...]
std::string BuildExecutor::watchesJson() const {
    std::string out = "[";
    int frame = Broodwar->getFrameCount();
    bool first = true;
    for (auto& w : watches_) {
        std::string b = !w.builder || !w.builder->exists() ? "none" : (w.builder->isIdle() ? "idle" : (w.builder->isConstructing() ? "constructing" : "moving"));
        mj::Writer j;
        j.key("type").value(w.type.c_str()).key("age").value(frame - w.issuedFrame).key("retries").value(w.retries).key("builder").value(b);
        if (w.builder && w.builder->exists()) j.key("x").value(w.builder->getTilePosition().x).key("y").value(w.builder->getTilePosition().y);
        j.key("tx").value(w.tile.x).key("ty").value(w.tile.y);
        out += std::string(first ? "" : ",") + j.str();
        first = false;
    }
    return out + "]";
}

// 포기한 건설 유형 이름 목록. 한 번 보내면 비운다
std::string BuildExecutor::abandonedJson() {
    std::string out = "[";
    for (size_t i = 0; i < abandoned_.size(); ++i) out += (i ? "," : "") + mj::quote(abandoned_[i]);
    abandoned_.clear();
    return out + "]";
}

std::string BuildExecutor::obsJson(int id, bool accepted, bool done, int endFrame, const std::string& error) {
    int frame = Broodwar->getFrameCount();
    mj::Writer w;
    w.key("type").value("obs").key("id").value(id).key("frame").value(frame).key("iteration").value(frame)
     .key("state").intArray(stateVector()).key("accepted").value(accepted).key("done").value(done);
    if (endFrame >= 0) w.key("end_frame").value(endFrame); else w.key("end_frame").null();
    if (error.empty()) w.key("error").null(); else w.key("error").value(error);
    int zIssued = 0;
    for (auto u : Broodwar->self()->getUnits())
        if (u->getType() == UnitTypes::Protoss_Gateway) zIssued += static_cast<int>(u->getTrainingQueue().size());
    // 스냅샷: 현재 상태에서 계획을 세울 수 있게 짓는 중인 건물의 남은 시간, 큐 상태를 싣는다
    std::vector<int> pylonsBuilding, gatesBuilding, gateQueue, gateRemaining;
    int nexusQueue = 0, nexusRemaining = 0, gas = 0, zealotsQueued = 0;
    for (auto u : Broodwar->self()->getUnits()) {
        UnitType t = u->getType();
        if (t == UnitTypes::Protoss_Pylon && !u->isCompleted()) pylonsBuilding.push_back(u->getRemainingBuildTime());
        else if (t == UnitTypes::Protoss_Gateway) {
            if (!u->isCompleted()) gatesBuilding.push_back(u->getRemainingBuildTime());
            else {
                int q = static_cast<int>(u->getTrainingQueue().size());
                gateQueue.push_back(q);
                gateRemaining.push_back(q > 0 ? u->getRemainingTrainTime() : 0);
                zealotsQueued += q;
            }
        } else if (t == UnitTypes::Protoss_Nexus && u->isCompleted()) {
            nexusQueue += static_cast<int>(u->getTrainingQueue().size());
            if (!u->getTrainingQueue().empty()) nexusRemaining = u->getRemainingTrainTime();
        }
    }
    gas = Broodwar->self()->gas();
    // 명령은 냈지만 아직 놓이지 않은 건설(BuildWatch): 예약 비용과 명령 뒤 경과 프레임
    std::vector<int> pylonsPending, gatesPending;
    int reserved = 0, reservedGasPending = 0;
    for (auto& bw : watches_) {
        reserved += bw.type.mineralPrice();
        reservedGasPending += bw.type.gasPrice();
        if (bw.type == UnitTypes::Protoss_Pylon) pylonsPending.push_back(frame - bw.issuedFrame);
        else if (bw.type == UnitTypes::Protoss_Gateway) gatesPending.push_back(frame - bw.issuedFrame);
    }
    mj::Writer ex;
    ex.key("gateways_ready").value(countCompleted(UnitTypes::Protoss_Gateway))
      .key("pylons_ready").value(countCompleted(UnitTypes::Protoss_Pylon))
      .key("zealots_in_production").value(zIssued)
      .key("prefix").intArray(commandLog_)
      .key("live").value(live_)
      .key("zealots_completed").value(zealotsCompleted_)
      .key("gas").value(gas)
      .key("nexus_queue").value(nexusQueue).key("nexus_remaining").value(nexusRemaining)
      .key("pylons_building").intArray(pylonsBuilding).key("gateways_building").intArray(gatesBuilding)
      .key("gate_queue").intArray(gateQueue).key("gate_remaining").intArray(gateRemaining)
      .key("reserved_minerals").value(reserved + reserveMinerals_).key("reserve_gas").value(reserveGas_)
      .key("reserved_gas").value(reservedGasPending + reserveGas_)
      .key("supply_issued").value(supplyInUse() / 2)
      .key("watches").raw(watchesJson())
      .key("abandoned").raw(abandonedJson())
      .key("tech").raw(techJson())
      .key("pylons_pending_elapsed").intArray(pylonsPending).key("gateways_pending_elapsed").intArray(gatesPending);
    w.key("extra").raw(ex.str());
    return w.str();
}

void BuildExecutor::logObservation(int action, int frame) {
    std::ofstream f(logPath_, std::ios::app);
    if (!f) return;
    mj::Writer w;
    w.key("action").value(action).key("frame").value(frame).key("state").intArray(stateVector()).key("prefix").intArray(commandLog_);
    f << w.str() << '\n';
}

// ------------------------------------------------------------------ 자동 기능
void BuildExecutor::assignMinerals() {
    if (!mainNexus_) return;
    Position base = mainNexus_->getPosition();
    for (auto m : Broodwar->getStaticMinerals())
        if (m->getDistance(base) < 320) patches_.push_back(m);
    geysers_.clear();
    for (auto g : Broodwar->getStaticGeysers())
        if (g->getDistance(base) < 400) geysers_.push_back(g);
    std::sort(patches_.begin(), patches_.end(), [&](Unit a, Unit b) {
        int da = a->getDistance(base), db = b->getDistance(base);
        return da != db ? da < db : a->getID() < b->getID();
    });
    if (patches_.empty()) return;
    std::vector<Unit> workers;
    for (auto u : Broodwar->self()->getUnits())
        if (u->getType().isWorker()) workers.push_back(u);
    std::sort(workers.begin(), workers.end(), [](Unit a, Unit b) { return a->getID() < b->getID(); });
    for (size_t i = 0; i < workers.size(); ++i) {
        Unit p = patches_[i % patches_.size()];
        workerPatch_[workers[i]->getID()] = p;
        workers[i]->gather(p);
    }
}

void BuildExecutor::autoMine() {
    for (auto u : Broodwar->self()->getUnits()) {
        if (!u->getType().isWorker() || !u->isCompleted()) continue;
        if (isBuilder(u)) continue;  // 건설 가는 일꾼은 건드리지 않는다
        if (u->isGatheringGas() || u->isCarryingGas()) continue;  // 가스 일꾼은 그대로 둔다
        if (!u->isIdle()) continue;
        auto it = workerPatch_.find(u->getID());
        Unit p = it != workerPatch_.end() ? it->second : nullptr;
        if (!p || !p->exists() || p->getResources() <= 0) {
            // 배정 덩이가 고갈됐거나 없다: 자기 기지(가장 가까운 넥서스) 근처에 남은 덩이 중 가장 가까운 것, 없으면 아무 기지의 남은 덩이
            Unit best = nullptr;
            for (auto m : Broodwar->getMinerals()) {
                if (!m->exists() || m->getResources() <= 0) continue;
                bool nearDepot = false;
                for (auto d : Broodwar->self()->getUnits())
                    if (d->getType().isResourceDepot() && d->isCompleted() && m->getDistance(d) < 320) nearDepot = true;
                if (!nearDepot) continue;
                if (!best || m->getDistance(u) < best->getDistance(u)) best = m;
            }
            p = best;
            if (p) workerPatch_[u->getID()] = p;
        }
        if (p) u->gather(p);
    }
}

int BuildExecutor::countCompleted(UnitType t) const {
    int n = 0;
    for (auto u : Broodwar->self()->getUnits()) if (u->getType() == t && u->isCompleted()) ++n;
    return n;
}

int BuildExecutor::countAll(UnitType t) const {
    int n = 0;
    for (auto u : Broodwar->self()->getUnits()) if (u->getType() == t) ++n;
    return n;
}

// 큐에서 대기 중(생산 시작 전)인 유닛의 인구. BW 의 supplyUsed() 는 생산이 시작된 유닛만 센다.
// 예전엔 실행기가 낸 명령을 누적(issuedSupply_)했는데 유닛이 죽어도 줄지 않아 인구가 남는데도 "불가"를 냈다(2026-11-08).
int BuildExecutor::queuedSupply() const {
    int s = 0;
    for (auto u : Broodwar->self()->getUnits()) {
        auto q = u->getTrainingQueue();
        for (size_t i = 1; i < q.size(); ++i) s += q[i].supplyRequired();
    }
    return s;
}

int BuildExecutor::supplyInUse() const {
    return Broodwar->self()->supplyUsed() + queuedSupply();
}

bool BuildExecutor::canAffordSupply(UnitType t) const {
    return supplyInUse() + t.supplyRequired() <= Broodwar->self()->supplyTotal();
}

Unit BuildExecutor::pickBuilder(TilePosition near, const std::vector<int>* exclude) const {
    Unit best = nullptr;
    int bestD = 1 << 30;
    Position target(near);
    for (auto u : Broodwar->self()->getUnits()) {
        if (!u->getType().isWorker() || !u->isCompleted()) continue;
        if (exclude && std::find(exclude->begin(), exclude->end(), u->getID()) != exclude->end()) continue;  // 전에 실패한 프로브
        if (u->isCarryingMinerals() || u->isConstructing()) continue;
        if (u->isGatheringGas() || u->isCarryingGas()) continue;  // 가스 일꾼(사람이 붙인 것)은 건설에 쓰지 않는다
        if (isBuilder(u)) continue;  // 다른 건설 명령을 수행하러 가는 중. 다시 고르면 그 명령이 취소된다
        int d = u->getDistance(target);
        if (d < bestD) { bestD = d; best = u; }
    }
    return best;
}

TilePosition BuildExecutor::findBuildTile(UnitType type, TilePosition anchor, int maxRadius, Unit builder, int pathMode) const {
    // 결정론적 나선 탐색. 같은 상황이면 같은 자리를 고른다 (노이즈 줄이기)
    for (int r = 0; r <= maxRadius; ++r) {
        for (int dx = -r; dx <= r; ++dx) {
            for (int dy = -r; dy <= r; ++dy) {
                if (std::max(std::abs(dx), std::abs(dy)) != r) continue;
                TilePosition t(anchor.x + dx, anchor.y + dy);
                if (!t.isValid()) continue;
                if (type.requiresPsi() && !Broodwar->hasPower(t, type)) continue;
                // checkExplored=true: 시야 밖 타일은 canBuildHere 가 통과해도 build() 가 Unbuildable_Location 으로 거부한다 (2026-11-08)
                if (!Broodwar->canBuildHere(t, type, builder, true)) continue;
                if (badTiles_.count(t.x * 10000 + t.y)) continue;  // build() 가 거부했던 자리는 다시 고르지 않는다
                // 아직 놓이지 않은 건설 명령의 자리와 겹치면 피한다 (canBuildHere 는 명령만 내린 자리를 모른다)
                bool overlaps = false;
                for (auto& w : watches_) {
                    if (!w.tile.isValid()) continue;
                    bool sepX = t.x + type.tileWidth() <= w.tile.x || w.tile.x + w.type.tileWidth() <= t.x;
                    bool sepY = t.y + type.tileHeight() <= w.tile.y || w.tile.y + w.type.tileHeight() <= t.y;
                    if (!sepX && !sepY) { overlaps = true; break; }
                }
                if (overlaps) continue;
                // 길막 방지: 이 건물을 놓아도 본진에서 바깥으로 나가는 땅길이 남고, 건물 옆에서도 나갈 수 있어야 한다
                if (pathMode == 0 && !keepsPath(t, type, true)) continue;
                if (pathMode == 1 && !keepsPath(t, type, false)) continue;
                // 자원 길을 막지 않는다: 미네랄 덩이 근처, 간헐천 근처, 넥서스-간헐천 사이 통로(가스 일꾼 왕복)를 피한다
                if (mainNexus_) {
                    Position c(t.x * 32 + type.tileWidth() * 16, t.y * 32 + type.tileHeight() * 16);
                    bool blocks = false;
                    for (auto m : patches_) if (m->getDistance(c) < 96) blocks = true;
                    Position n = mainNexus_->getPosition();
                    for (auto g : geysers_) {
                        if (g->getDistance(c) < 160) blocks = true;
                        // 점 c 와 선분 n-g 의 거리
                        Position gp = g->getPosition();
                        double vx = gp.x - n.x, vy = gp.y - n.y, wx = c.x - n.x, wy = c.y - n.y;
                        double len2 = vx * vx + vy * vy;
                        double s = len2 > 0 ? std::max(0.0, std::min(1.0, (wx * vx + wy * vy) / len2)) : 0.0;
                        double dx = c.x - (n.x + s * vx), dy = c.y - (n.y + s * vy);
                        if (dx * dx + dy * dy < 96.0 * 96.0) blocks = true;
                    }
                    if (blocks) continue;
                }
                return t;
            }
        }
    }
    return TilePositions::Invalid;
}

// 멀티 완성(또는 rebalance 메시지): 그 기지의 덩이를 등록하고, 본진에서 덩이당 2기를 넘는 일꾼을 옮긴다.
// 본진 일꾼은 (건설·가스 제외) 전부 세고, 옮길 때는 빈손을 먼저 고른다. 미네랄을 든 일꾼을 세지 않으면 초과분이 0 으로 나온다(2026-11-08).
void BuildExecutor::rebalanceWorkers(Unit depot) {
    if (!depot || !mainNexus_ || depot == mainNexus_) return;
    std::vector<Unit> newPatches;
    for (auto m : Broodwar->getStaticMinerals())
        if (m->getInitialPosition().getDistance(depot->getPosition()) < 320) {
            newPatches.push_back(m);
            if (std::find(patches_.begin(), patches_.end(), m) == patches_.end()) patches_.push_back(m);
        }
    std::sort(newPatches.begin(), newPatches.end(), [&](Unit a, Unit b) {
        return a->getInitialPosition().getDistance(depot->getPosition()) < b->getInitialPosition().getDistance(depot->getPosition()); });
    int mainPatches = 0;
    for (auto m : patches_) if (m->getInitialPosition().getDistance(mainNexus_->getPosition()) < 320) ++mainPatches;
    std::vector<Unit> mainWorkers;
    for (auto u : Broodwar->self()->getUnits())
        if (u->getType().isWorker() && u->isCompleted() && !isBuilder(u) && !u->isGatheringGas() && !u->isCarryingGas()
            && u->getDistance(mainNexus_) < 400) mainWorkers.push_back(u);
    std::stable_sort(mainWorkers.begin(), mainWorkers.end(), [](Unit a, Unit b) { return !a->isCarryingMinerals() && b->isCarryingMinerals(); });
    int excess = static_cast<int>(mainWorkers.size()) - 2 * mainPatches;
    int moved = 0;
    for (size_t i = 0; i < mainWorkers.size() && excess > 0 && !newPatches.empty(); ++i, --excess, ++moved) {
        Unit target = newPatches[i % newPatches.size()];
        workerPatch_[mainWorkers[i]->getID()] = target;
        mainWorkers[i]->gather(target);
    }
    Broodwar->printf("expansion: %d patches, main workers %d (cap %d), moved %d", static_cast<int>(newPatches.size()),
                     static_cast<int>(mainWorkers.size()), 2 * mainPatches, moved);
}

// 앞마당: 본진 밖 미네랄 무리 중 땅길이 있고 가장 가까운 것. 넥서스 자리는 무리 둘레에서 canBuildHere 를 만족하며
// 덩이·간헐천까지 거리 합이 가장 작은 타일. (BWEM 없이 단순 규칙. 결정론: 같은 맵이면 같은 자리)
TilePosition BuildExecutor::findExpansion() const {
    int depots = 0;
    for (auto u : Broodwar->self()->getUnits()) if (u->getType().isResourceDepot()) ++depots;
    for (auto& w : watches_) if (w.type.isResourceDepot()) ++depots;
    if (expansionCacheDepots_ == depots && expansionCache_.isValid()) return expansionCache_;
    expansionCache_ = computeExpansion();
    expansionCacheDepots_ = depots;
    return expansionCache_;
}

// 본진 넥서스에서 각 타일까지의 땅 거리(타일, 정적 지형 기준 BFS). 게임당 한 번 계산
const std::vector<int>& BuildExecutor::groundDistance() const {
    const int W = Broodwar->mapWidth(), H = Broodwar->mapHeight();
    if (groundDist_.size() == static_cast<size_t>(W * H) || !mainNexus_) return groundDist_;
    if (walkGrid_.size() != static_cast<size_t>(W * H)) {
        walkGrid_.assign(static_cast<size_t>(W * H), 0);
        for (int y = 0; y < H; ++y)
            for (int x = 0; x < W; ++x)
                walkGrid_[static_cast<size_t>(y * W + x)] = Broodwar->isWalkable(4 * x + 1, 4 * y + 1) && Broodwar->isWalkable(4 * x + 2, 4 * y + 1)
                    && Broodwar->isWalkable(4 * x + 1, 4 * y + 2) && Broodwar->isWalkable(4 * x + 2, 4 * y + 2);
    }
    groundDist_.assign(static_cast<size_t>(W * H), -1);
    std::vector<int> q;
    TilePosition nt = mainNexus_->getTilePosition();
    for (int y = nt.y - 1; y <= nt.y + 3; ++y)
        for (int x = nt.x - 1; x <= nt.x + 4; ++x)
            if (x >= 0 && y >= 0 && x < W && y < H && walkGrid_[static_cast<size_t>(y * W + x)] && groundDist_[static_cast<size_t>(y * W + x)] < 0) {
                groundDist_[static_cast<size_t>(y * W + x)] = 0;
                q.push_back(y * W + x);
            }
    for (size_t head = 0; head < q.size(); ++head) {
        int i = q[head], x = i % W, y = i / W, d = groundDist_[static_cast<size_t>(i)];
        const int nx[4] = {x + 1, x - 1, x, x}, ny[4] = {y, y, y + 1, y - 1};
        for (int k = 0; k < 4; ++k) {
            if (nx[k] < 0 || ny[k] < 0 || nx[k] >= W || ny[k] >= H) continue;
            size_t j = static_cast<size_t>(ny[k] * W + nx[k]);
            if (!walkGrid_[j] || groundDist_[j] >= 0) continue;
            groundDist_[j] = d + 1;
            q.push_back(static_cast<int>(j));
        }
    }
    return groundDist_;
}

TilePosition BuildExecutor::computeExpansion() const {
    if (!mainNexus_) return TilePositions::Invalid;
    Position base = mainNexus_->getPosition();
    // 이미 넥서스가 있는 곳(자기 것)은 제외
    std::vector<Position> ownDepots;
    for (auto u : Broodwar->self()->getUnits()) if (u->getType().isResourceDepot()) ownDepots.push_back(u->getPosition());
    // 명령은 냈지만 아직 놓이지 않은 넥서스 자리도 '있는 것'으로 친다 (n 을 연달아 치면 같은 자리를 두 번 고르지 않게)
    for (auto& w : watches_) if (w.type.isResourceDepot() && w.tile.isValid()) ownDepots.push_back(Position(w.tile.x * 32 + 64, w.tile.y * 32 + 48));
    // 미네랄 무리 만들기 (덩이 간 거리 200px 이내 연결)
    // 시야 밖 자원은 exists()/getResources() 가 0 이고 getType() 은 Unknown 이다. 초기 자원량·초기 위치·초기 유형을 쓴다
    // (2026-11-08 "no expansion site" 두 번: 처음엔 자원량, 다음엔 유형이 원인)
    std::vector<Unit> res;
    for (auto m : Broodwar->getStaticMinerals()) if (m->getInitialResources() > 0) res.push_back(m);
    for (auto g : Broodwar->getStaticGeysers()) res.push_back(g);
    auto posOf = [](Unit u) { return u->getInitialPosition(); };
    std::vector<int> cluster(res.size(), -1);
    int nc = 0;
    for (size_t i = 0; i < res.size(); ++i) {
        if (cluster[i] >= 0) continue;
        cluster[i] = nc;
        std::vector<size_t> stack{i};
        while (!stack.empty()) {
            size_t a = stack.back(); stack.pop_back();
            for (size_t b = 0; b < res.size(); ++b)
                if (cluster[b] < 0 && posOf(res[a]).getDistance(posOf(res[b])) < 200) { cluster[b] = nc; stack.push_back(b); }
        }
        ++nc;
    }
    TilePosition best = TilePositions::Invalid;
    double bestDist = 1e18;
    for (int k = 0; k < nc; ++k) {
        std::vector<Unit> members;
        for (size_t i = 0; i < res.size(); ++i) if (cluster[i] == k) members.push_back(res[i]);
        int minerals = 0;
        for (auto m : members) if (m->getInitialType().isMineralField()) ++minerals;
        if (minerals < 4) continue;
        Position center(0, 0);
        for (auto m : members) center += posOf(m);
        center = Position(center.x / static_cast<int>(members.size()), center.y / static_cast<int>(members.size()));
        bool taken = false;
        for (auto& d : ownDepots) if (d.getDistance(center) < 400) taken = true;
        if (taken) continue;
        // 땅 거리: 무리 중심 근처에서 BFS 거리가 있는 가장 가까운 타일. 직선 거리는 절벽 너머 기지를 '가깝다'고 본다
        const std::vector<int>& gd = groundDistance();
        double dist = 1e9;
        {
            TilePosition cc(center);
            const int W = Broodwar->mapWidth(), H = Broodwar->mapHeight();
            for (int dy = -8; dy <= 8; ++dy)
                for (int dx = -8; dx <= 8; ++dx) {
                    int x = cc.x + dx, y = cc.y + dy;
                    if (x < 0 || y < 0 || x >= W || y >= H || gd.empty()) continue;
                    int v = gd[static_cast<size_t>(y * W + x)];
                    if (v >= 0 && v < dist) dist = v;
                }
        }
        if (dist >= 1e9 || dist >= bestDist) continue;
        // 무리 둘레에서 넥서스 자리 찾기. 게임 규칙: 자원 저장소는 모든 자원과 타일 3칸 간격(변 기준). 그 안에서 자원 중심까지
        // 거리 제곱합이 가장 작은 칸(BWEM/BWTA 와 같은 기준). 예전의 '중심 거리 112px' 어림은 호 안쪽·간헐천 옆을 고르는 일이 있었다.
        TilePosition ct(center);
        TilePosition site = TilePositions::Invalid;
        double siteScore = 1e18;
        for (int dy = -12; dy <= 12; ++dy)
            for (int dx = -12; dx <= 12; ++dx) {
                TilePosition t(ct.x + dx, ct.y + dy);
                if (!t.isValid()) continue;
                bool ok = true;
                for (int y = t.y; y < t.y + 3 && ok; ++y)
                    for (int x = t.x; x < t.x + 4 && ok; ++x)
                        if (x >= Broodwar->mapWidth() || y >= Broodwar->mapHeight() || !Broodwar->isBuildable(x, y, false)) ok = false;
                if (!ok) continue;
                // 점수: 넥서스 4x3 상자와 각 자원 상자 사이의 타일 간격(체비셰프)의 합. 규칙상 최소 3칸이고, 많은 자원이 3칸에 붙을수록
                // 채취 왕복이 짧다(BWEM 의 기지 위치 점수와 같은 생각). 예전 '중심 거리 제곱합'은 2x1 미네랄·4x2 간헐천 모양을 무시해
                // 호 바깥쪽으로 밀렸다 (2026-11-08 사용자 정찰로 확인)
                double score = 0;
                for (auto m : members) {
                    TilePosition rt = m->getInitialTilePosition();
                    int rw = m->getInitialType().tileWidth(), rh = m->getInitialType().tileHeight();
                    int gx = std::max({0, rt.x - (t.x + 4), t.x - (rt.x + rw)});
                    int gy = std::max({0, rt.y - (t.y + 3), t.y - (rt.y + rh)});
                    bool okX = (t.x >= rt.x + rw + 3) || (rt.x >= t.x + 4 + 3);
                    bool okY = (t.y >= rt.y + rh + 3) || (rt.y >= t.y + 3 + 3);
                    if (!okX && !okY) { ok = false; break; }
                    double d = std::max(gx, gy);
                    score += m->getInitialType().isMineralField() ? d : 1.5 * d;  // 간헐천은 가스 왕복이 더 자주라 가중
                }
                if (!ok) continue;
                if (score < siteScore) { siteScore = score; site = t; }
            }
        // 땅길 확인은 (자원 위가 아닌) 넥서스 자리 기준으로
        if (site.isValid() && Broodwar->hasPath(base, Position(site.x * 32 + 64, site.y * 32 + 48))) {
            best = site; bestDist = dist;
            Broodwar->printf("expansion site (%d,%d) score %.1f for %d resources", site.x, site.y, siteScore, static_cast<int>(members.size()));
        }
        else Broodwar->printf("expansion cluster %d: %d minerals, site %s, path %d", k, minerals, site.isValid() ? "ok" : "none",
                              site.isValid() ? (int)Broodwar->hasPath(base, Position(site.x * 32 + 64, site.y * 32 + 48)) : -1);
    }
    Broodwar->printf("expansion: %d clusters, best %s", nc, best.isValid() ? "found" : "none");
    return best;
}

// 건물을 (t, type) 에 놓았다고 가정하고, 타일 격자 BFS 로 넥서스 주변 → 적 방향 목표까지 땅길이 있는지 본다.
// 보행 가능: 타일 가운데 2x2 미니타일(8px)이 모두 걸을 수 있을 때(경사로는 보행 가능·건설 불가라 isBuildable 로는 안 된다).
// 장애물: 모든 건물(자기·상대·중립), 미네랄·간헐천, 아직 놓이지 않은 건설 명령 자리, 그리고 새 건물.
bool BuildExecutor::keepsPath(TilePosition t, UnitType type, bool strict) const {
    const int W = Broodwar->mapWidth(), H = Broodwar->mapHeight();
    if (W <= 0 || H <= 0 || !mainNexus_) return true;
    std::vector<char> blocked(static_cast<size_t>(W * H), 0);
    auto block = [&](TilePosition tp, int tw, int th) {
        for (int y = tp.y; y < tp.y + th; ++y)
            for (int x = tp.x; x < tp.x + tw; ++x)
                if (x >= 0 && y >= 0 && x < W && y < H) blocked[static_cast<size_t>(y * W + x)] = 1;
    };
    if (walkGrid_.size() != static_cast<size_t>(W * H)) {
        walkGrid_.assign(static_cast<size_t>(W * H), 0);
        for (int y = 0; y < H; ++y)
            for (int x = 0; x < W; ++x)
                walkGrid_[static_cast<size_t>(y * W + x)] = Broodwar->isWalkable(4 * x + 1, 4 * y + 1) && Broodwar->isWalkable(4 * x + 2, 4 * y + 1)
                    && Broodwar->isWalkable(4 * x + 1, 4 * y + 2) && Broodwar->isWalkable(4 * x + 2, 4 * y + 2);
    }
    for (size_t i = 0; i < blocked.size(); ++i) if (!walkGrid_[i]) blocked[i] = 1;
    for (auto u : Broodwar->getAllUnits()) {
        UnitType ut = u->getType();
        if (ut.isBuilding() || ut.isMineralField() || ut == UnitTypes::Resource_Vespene_Geyser)
            block(u->getTilePosition(), ut.tileWidth(), ut.tileHeight());
    }
    for (auto& w : watches_) if (w.tile.isValid()) block(w.tile, w.type.tileWidth(), w.type.tileHeight());
    std::vector<char> blockedPre = blocked;  // 새 건물을 놓기 전
    block(t, type.tileWidth(), type.tileHeight());

    // 길의 폭: 드라군 같은 큰 유닛은 한 칸 틈을 못 지난다. 2x2 블록이 모두 빈 곳만 '지나갈 수 있는 자리'로 보고 BFS 한다
    // (블록의 왼쪽 위 칸을 대표로). 2026-11-08 한 칸 틈으로 드라군이 갇힌 뒤 강화.
    // strict: 2x2 블록(큰 유닛 통로). 완화: 한 칸이면 통로로 본다
    auto freeBlockIn = [&](const std::vector<char>& g, int x, int y) {
        if (x < 0 || y < 0 || x >= W || y >= H) return false;
        if (!strict) return !g[static_cast<size_t>(y * W + x)];
        if (x + 1 >= W || y + 1 >= H) return false;
        return !g[static_cast<size_t>(y * W + x)] && !g[static_cast<size_t>(y * W + x + 1)]
            && !g[static_cast<size_t>((y + 1) * W + x)] && !g[static_cast<size_t>((y + 1) * W + x + 1)];
    };
    auto freeBlock = [&](int x, int y) { return freeBlockIn(blocked, x, y); };
    // 놓기 전에 큰 유닛이 지날 수 있던 칸(어떤 2x2 빈 블록에든 속함)
    auto coverablePre = [&](int x, int y) {
        if (!strict) return freeBlockIn(blockedPre, x, y);
        for (int dx = -1; dx <= 0; ++dx)
            for (int dy = -1; dy <= 0; ++dy)
                if (freeBlockIn(blockedPre, x + dx, y + dy)) return true;
        return false;
    };
    TilePosition nt = mainNexus_->getTilePosition();
    int nw = mainNexus_->getType().tileWidth(), nh = mainNexus_->getType().tileHeight();
    std::vector<int> q;
    std::vector<char> seen(static_cast<size_t>(W * H), 0);  // 블록 대표 칸 기준
    auto push = [&](int x, int y) {
        if (!freeBlock(x, y)) return;
        size_t i = static_cast<size_t>(y * W + x);
        if (seen[i]) return;
        seen[i] = 1;
        q.push_back(static_cast<int>(i));
    };
    // 출발: 넥서스 둘레(2칸 두께)에서 시작하는 모든 빈 블록
    for (int x = nt.x - 2; x <= nt.x + nw; ++x)
        for (int y = nt.y - 2; y <= nt.y + nh; ++y) push(x, y);
    TilePosition goal = enemyStart_.isValid() ? enemyStart_ : TilePosition(W / 2, H / 2);
    bool reachedGoal = false;
    for (size_t head = 0; head < q.size(); ++head) {
        int i = q[head];
        int x = i % W, y = i / W;
        if (std::abs(x - goal.x) <= 6 && std::abs(y - goal.y) <= 6) reachedGoal = true;
        push(x + 1, y); push(x - 1, y); push(x, y + 1); push(x, y - 1);
    }
    if (!reachedGoal) return false;
    // 새 건물 둘레의 빈 칸은 전부, 그 칸을 덮는 2x2 블록 중 하나가 닿아야 한다. 아니면 그 칸은 새 건물이 만든 주머니다
    auto covered = [&](int x, int y) {
        if (!strict) return x >= 0 && y >= 0 && x < W && y < H && seen[static_cast<size_t>(y * W + x)] != 0;
        for (int dx = -1; dx <= 0; ++dx)
            for (int dy = -1; dy <= 0; ++dy) {
                int bx = x + dx, by = y + dy;
                if (bx < 0 || by < 0) continue;
                if (seen[static_cast<size_t>(by * W + bx)]) return true;
            }
        return false;
    };
    // 원래 한 칸짜리 홈(절벽·건물 옆)은 새 건물 탓이 아니다. 놓기 전에 지날 수 있던 칸이 놓은 뒤 닿지 않을 때만 주머니로 본다
    // (2026-11-08: 이 구분이 없어서 게이트 자리가 전부 떨어져 8초마다 건설 실패).
    for (int x = t.x - 1; x <= t.x + type.tileWidth(); ++x)
        for (int y = t.y - 1; y <= t.y + type.tileHeight(); ++y) {
            if (x < 0 || y < 0 || x >= W || y >= H) continue;
            if (blocked[static_cast<size_t>(y * W + x)]) continue;
            if (coverablePre(x, y) && !covered(x, y)) return false;
        }
    return true;
}

// 생산을 가장 먼저 시작할 수 있는 게이트. 짓는 중인 게이트도 후보이고, 그쪽이 더 빠르면 nullptr + waiting=true 로 기다린다
// (2026-11-08: 완성된 첫 게이트 하나에 질럿이 줄 서서 계획기가 게이트를 더 짓는 쪽을 골랐다 — 8게이트 사건)
Unit BuildExecutor::pickGateway(bool* waiting) const {
    Unit best = nullptr;
    int bestStart = 1 << 30;
    bool bestDone = false;
    for (auto u : Broodwar->self()->getUnits()) {
        if (u->getType() != UnitTypes::Protoss_Gateway) continue;
        if (u->isCompleted() && !u->isPowered()) continue;  // 파일런이 부서져 전력이 끊긴 게이트는 생산 불가 (train → Unit_Busy)
        int start;
        if (!u->isCompleted()) start = u->getRemainingBuildTime();
        else {
            int q = static_cast<int>(u->getTrainingQueue().size());
            start = q == 0 ? 0 : u->getRemainingTrainTime() + (q - 1) * 600;
        }
        if (start < bestStart || (start == bestStart && u->isCompleted() && !bestDone)) { bestStart = start; best = u; bestDone = u->isCompleted(); }
    }
    if (best && !bestDone) { if (waiting) *waiting = true; return nullptr; }
    if (waiting) *waiting = false;
    return best;
}

// 명령을 내릴 수 있으면 내리고 true. 아니면 why에 이유(접두사 "fatal:"이면 재시도 없이 실패).
bool BuildExecutor::pendingOf(UnitType t) const {
    for (auto& w : watches_) if (w.type == t) return true;
    return false;
}

// 업그레이드 (공·방·쉴드). 다음 레벨을 포지에서 시작하면 done. 2·3레벨은 아카이브 필요, 진행 중이면 끝날 때까지 기다린다
bool BuildExecutor::tryUpgrade(UpgradeType up, std::string& why) {
    Player me = Broodwar->self();
    int level = me->getUpgradeLevel(up);
    if (level >= me->getMaxUpgradeLevel(up)) { why = "fatal:upgrade maxed"; return false; }
    if (me->isUpgrading(up)) { why = "upgrading (previous level)"; return false; }
    int next = level + 1;
    UnitType req = up.whatsRequired(next);
    if (req != UnitTypes::None && countCompleted(req) == 0) {
        bool coming = countAll(req) > 0 || pendingOf(req);
        for (auto& r : requests_) if (r.state == "queued" && typeOf(r.action) == req) coming = true;
        if (!coming) { why = std::string("fatal:requires ") + req.c_str(); return false; }
        why = std::string(req.c_str()) + " not complete";
        return false;
    }
    UnitType where = up.whatUpgrades();
    if (countCompleted(where) == 0) {
        bool coming = countAll(where) > 0 || pendingOf(where);
        for (auto& r : requests_) if (r.state == "queued" && typeOf(r.action) == where) coming = true;
        if (!coming) { why = std::string("fatal:requires ") + where.c_str(); return false; }
        why = std::string(where.c_str()) + " not complete";
        return false;
    }
    int reserved = 0, reservedGas = 0;
    for (auto& w : watches_) { reserved += w.type.mineralPrice(); reservedGas += w.type.gasPrice(); }
    if (me->minerals() - reserved - reserveMinerals_ < up.mineralPrice(next)) { why = "minerals"; return false; }
    if (up.gasPrice(next) > 0) {
        if (countAll(UnitTypes::Protoss_Assimilator) == 0 && !pendingOf(UnitTypes::Protoss_Assimilator)) { why = "fatal:needs gas (no assimilator)"; return false; }
        if (me->gas() - reservedGas - reserveGas_ < up.gasPrice(next)) { why = "gas"; return false; }
    }
    Unit forge = nullptr;
    for (auto u : me->getUnits())
        if (u->getType() == where && u->isCompleted() && u->isPowered() && !u->isUpgrading() && !u->isResearching()) { forge = u; break; }
    if (!forge) {
        bool coming = countAll(where) > countCompleted(where) || pendingOf(where);
        why = coming ? std::string(where.c_str()) + " not complete" : std::string(where.c_str()) + " busy";
        return false;
    }
    if (!forge->upgrade(up)) { why = "upgrade refused: " + std::string(Broodwar->getLastError().c_str()); ++pending_.retries; return false; }
    return true;
}

bool BuildExecutor::tryExecute(int action, std::string& why) {
    Player me = Broodwar->self();
    if (upgradeOf(action) != UpgradeTypes::None) return tryUpgrade(upgradeOf(action), why);
    UnitType type = typeOf(action);
    if (type == UnitTypes::None) { why = "fatal:unknown action"; return false; }

    if (pending_.retries > kMaxBuildRetries) { why = "fatal:command refused repeatedly (last: " + lastWhy_ + ")"; return false; }

    // 스타1은 건물 비용을 명령 때가 아니라 일꾼이 도착해 놓을 때 뺀다. 아직 놓이지 않은 건설 명령의 비용(미네랄·가스)을 예약해
    // 두지 않으면 같은 돈으로 두 번 명령하게 된다 (2026-11-08 실게임: 게이트 2개 명령에 1개만 지어짐).
    int reserved = 0, reservedGas = 0;
    for (auto& w : watches_) { reserved += w.type.mineralPrice(); reservedGas += w.type.gasPrice(); }
    if (me->minerals() - reserved - reserveMinerals_ < type.mineralPrice()) { why = "minerals"; return false; }
    if (type.gasPrice() > 0) {
        if (countAll(UnitTypes::Protoss_Assimilator) == 0 && !pendingOf(UnitTypes::Protoss_Assimilator)) {
            why = "fatal:needs gas (no assimilator)"; return false;
        }
        if (me->gas() - reservedGas - reserveGas_ < type.gasPrice()) { why = "gas"; return false; }
    }
    if (type.supplyRequired() > 0 && !canAffordSupply(type)) {
        // 짓고 있는(명령만 내린 것 포함) 파일런이 모두 완성돼도 모자라면 영원히 불가능 → 즉시 실패
        int pylonsComing = countAll(UnitTypes::Protoss_Pylon) - countCompleted(UnitTypes::Protoss_Pylon);
        for (auto& w : watches_) if (w.type == UnitTypes::Protoss_Pylon) ++pylonsComing;
        // 라이브: 큐에서 차례를 기다리는 파일런 요청도 '오고 있는 것'이다. 안 세면 계획이 뒤에 둔 파일런 때문에 앞 유닛이 즉시 실패한다 (2026-11-08)
        for (auto& r : requests_) if (r.state == "queued" && r.action == 1) ++pylonsComing;
        int futureTotal = std::min(400, me->supplyTotal() + 16 * pylonsComing);  // BW 2배 단위, 최대 200
        int used = supplyInUse();
        if (me->supplyTotal() >= 400) { why = "fatal:supply maxed (200)"; return false; }  // 파일런으로 해결되지 않는다
        if (used + type.supplyRequired() > futureTotal) { why = "fatal:supply impossible (need pylon)"; return false; }
        why = "supply";
        return false;
    }
    // 선행 건물 (BWAPI requiredUnits). 짓는 중이거나 명령된 것이 있으면 기다리고, 아무것도 없으면 즉시 실패
    for (auto& kv : type.requiredUnits()) {
        UnitType req = kv.first;
        if (req == UnitTypes::Protoss_Nexus || req == UnitTypes::Protoss_Probe || req == UnitTypes::Protoss_Pylon) continue;
        if (countCompleted(req) >= 1) continue;
        bool queuedAhead = false;
        for (auto& r : requests_) if (r.state == "queued" && typeOf(r.action) == req) queuedAhead = true;
        if (countAll(req) >= 1 || pendingOf(req) || queuedAhead) { why = std::string(req.c_str()) + " not complete"; return false; }
        why = std::string("fatal:requires ") + req.c_str();
        return false;
    }
    if (type.requiresPsi() && countCompleted(UnitTypes::Protoss_Pylon) == 0) {
        why = (countAll(UnitTypes::Protoss_Pylon) || pendingOf(UnitTypes::Protoss_Pylon)) ? "pylon not complete" : "fatal:no pylon";
        return false;
    }

    if (!type.isBuilding()) {
        Unit producer = nullptr;
        if (type == UnitTypes::Protoss_Probe) {
            // 완성된 넥서스 중 큐가 가장 짧은 곳 (멀티가 있으면 두 큐를 같이 쓴다)
            for (auto u : me->getUnits())
                if (u->getType() == UnitTypes::Protoss_Nexus && u->isCompleted()
                    && (!producer || u->getTrainingQueue().size() < producer->getTrainingQueue().size())) producer = u;
            if (!producer) { why = "fatal:no nexus"; return false; }
            if (producer->getTrainingQueue().size() >= 5) { why = "nexus queue full"; return false; }
        } else {
            bool waitGate = false;
            producer = pickGateway(&waitGate);
            if (!producer) {
                bool unpowered = false;
                for (auto u : me->getUnits()) if (u->getType() == UnitTypes::Protoss_Gateway && u->isCompleted() && !u->isPowered()) unpowered = true;
                int pylonsComing = countAll(UnitTypes::Protoss_Pylon) - countCompleted(UnitTypes::Protoss_Pylon);
                for (auto& w : watches_) if (w.type == UnitTypes::Protoss_Pylon) ++pylonsComing;
                if (!waitGate && unpowered && pylonsComing == 0) { why = "fatal:gateway unpowered (need pylon)"; return false; }
                why = (waitGate || countAll(UnitTypes::Protoss_Gateway)) ? "gateway not complete" : "fatal:no gateway";
                return false;
            }
        }
        if (!producer->train(type)) { why = "train refused: " + std::string(Broodwar->getLastError().c_str()); ++pending_.retries; return false; }
        issuedSupply_ += type.supplyRequired();
        return true;
    }

    // 건물
    TilePosition anchor;
    if (type == UnitTypes::Protoss_Pylon) {
        if (!mainNexus_) { why = "fatal:no nexus"; return false; }
        TilePosition nt = mainNexus_->getTilePosition();
        int dx = enemyStart_.x > nt.x ? 1 : (enemyStart_.x < nt.x ? -1 : 0);
        int dy = enemyStart_.y > nt.y ? 1 : (enemyStart_.y < nt.y ? -1 : 0);
        int dist = countAll(UnitTypes::Protoss_Pylon) == 0 ? 5 : 7;  // SC2 봇: 첫 파일런 3, 이후 5~7 (SC1 타일 단위로 조정)
        anchor = TilePosition(nt.x + dx * dist, nt.y + dy * dist);
    } else if (type == UnitTypes::Protoss_Nexus) {
        anchor = findExpansion();
        if (!anchor.isValid()) { why = "fatal:no expansion site"; return false; }
    } else if (type == UnitTypes::Protoss_Assimilator) {
        // 아직 어시밀레이터가 없는 본진 간헐천 위에 짓는다
        Unit target = nullptr;
        for (auto g : geysers_) {
            bool taken = false;
            for (auto u : Broodwar->getUnitsOnTile(g->getTilePosition()))
                if (u->getType() == UnitTypes::Protoss_Assimilator) taken = true;
            for (auto& w : watches_) if (w.type == UnitTypes::Protoss_Assimilator && w.anchor == g->getTilePosition()) taken = true;
            if (!taken) { target = g; break; }
        }
        if (!target) { why = "fatal:no free geyser"; return false; }
        anchor = target->getTilePosition();
    } else {
        Unit pylon = nullptr;
        for (auto u : me->getUnits()) if (u->getType() == UnitTypes::Protoss_Pylon && u->isCompleted()) { pylon = u; break; }
        if (!pylon) { why = "pylon not complete"; return false; }
        anchor = pylon->getTilePosition();
    }
    Unit builder = nullptr;
    TilePosition tile;
    int before = countAll(type);
    int frameNow = Broodwar->getFrameCount();
    auto cool = placeFailFrame_.find(type.getID());
    if (cool != placeFailFrame_.end() && frameNow - cool->second < 24) { why = "no build tile (cooldown)"; return false; }
    if (!issueBuild(type, anchor, builder, tile, why)) {
        if (why == "no build tile") placeFailFrame_[type.getID()] = frameNow;
        if (why == "no build tile" && type.requiresPsi()) {
            // 전력 범위 안에 자리가 없다: 오고 있는 파일런이 없으면 기다려도 안 풀린다 → 파일런 필요를 바로 알린다
            int coming = countAll(UnitTypes::Protoss_Pylon) - countCompleted(UnitTypes::Protoss_Pylon);
            for (auto& w : watches_) if (w.type == UnitTypes::Protoss_Pylon) ++coming;
            for (auto& r : requests_) if (r.state == "queued" && r.action == 1) ++coming;
            if (coming == 0) { why = "fatal:no powered space (need pylon)"; return false; }
        }
        if (why != "scouting expansion site" && why != "waiting expansion site clear") ++pending_.retries;  // 정찰·비킴 대기는 실패로 세지 않는다
        return false;
    }
    // 명령 실행 시각은 build()를 내린 지금이다. SC2 로그도 명령 시점에 기록했다.
    // 건물이 실제로 놓이는지는 BuildWatch가 다음 프레임부터 확인하고, 응답은 지금 보낸다
    BuildWatch w;
    w.builder = builder;
    w.type = type;
    w.anchor = anchor;
    w.tile = tile;
    w.issuedFrame = Broodwar->getFrameCount();
    w.expectedCount = before;
    watches_.push_back(w);
    return true;
}

// 일꾼을 고르고 자리를 찾아 build()를 내린다. 실패하면 why에 이유.
bool BuildExecutor::issueBuild(UnitType type, TilePosition anchor, Unit& builderOut, TilePosition& tileOut, std::string& why,
                               const std::vector<int>* exclude) {
    Unit builder = pickBuilder(anchor, exclude);
    if (!builder) { why = "no free worker"; return false; }
    TilePosition tile = TilePositions::Invalid;
    if (type == UnitTypes::Protoss_Assimilator) tile = anchor;
    else if (type == UnitTypes::Protoss_Nexus) {
        // 앞마당 자리(점수 최적)에 정확히 짓는다. 안 되면 미탐사면 정찰, 아니면 비키기를 기다린다(둘 다 실패로 안 셈).
        // 예전엔 ±3칸에서 '처음 찾은' 자리로 바꿔 왼쪽 위로 치우쳤다 (2026-11-08: (94,39) 대신 (91,39)).
        // 480프레임 넘게 못 지으면 그때만 ±3칸 중 원래 자리에 가장 가까운 합법 자리로 바꾼다.
        if (Broodwar->canBuildHere(anchor, type, builder, true)) tile = anchor;
        else {
            int now = Broodwar->getFrameCount();
            if (nexusWaitSince_ < 0 || nexusWaitAnchor_ != anchor) { nexusWaitSince_ = now; nexusWaitAnchor_ = anchor; }
            if (now - nexusWaitSince_ > 480) {
                int bestD = 1 << 30;
                for (int dy = -3; dy <= 3; ++dy)
                    for (int dx = -3; dx <= 3; ++dx) {
                        TilePosition t2(anchor.x + dx, anchor.y + dy);
                        int d = dx * dx + dy * dy;
                        if (d < bestD && t2.isValid() && Broodwar->canBuildHere(t2, type, builder, true)) { bestD = d; tile = t2; }
                    }
            }
            if (!tile.isValid()) {
                bool unexplored = false;
                for (int y = anchor.y; y < anchor.y + 3; ++y)
                    for (int x = anchor.x; x < anchor.x + 4; ++x)
                        if (!Broodwar->isExplored(x, y)) unexplored = true;
                builder->move(Position(anchor.x * 32 + 64, anchor.y * 32 + 48));
                why = unexplored ? "scouting expansion site" : "waiting expansion site clear";
                return false;
            }
        }
        nexusWaitSince_ = -1;
    }
    else {
        // 기준점 후보: 요청된 앵커, 그리고 모든 완성 파일런(앵커에서 가까운 순). 엄격(2칸 통로) → 완화(1칸) → 무검사
        std::vector<TilePosition> anchors{anchor};
        std::vector<Unit> pylons;
        for (auto u : Broodwar->self()->getUnits()) if (u->getType() == UnitTypes::Protoss_Pylon && u->isCompleted()) pylons.push_back(u);
        std::sort(pylons.begin(), pylons.end(), [&](Unit a, Unit b) { return a->getDistance(Position(anchor)) < b->getDistance(Position(anchor)); });
        for (auto u : pylons) anchors.push_back(u->getTilePosition());
        for (int mode = 0; mode < 3 && !tile.isValid(); ++mode) {
            for (auto& a : anchors) {
                tile = findBuildTile(type, a, mode == 0 ? 12 : 16, builder, mode);
                if (tile.isValid()) break;
            }
            if (tile.isValid() && mode > 0) Broodwar->printf("warning: %s placed with %s path check", type.c_str(), mode == 1 ? "relaxed" : "no");
        }
    }
    if (tile == TilePositions::Invalid) { why = "no build tile"; return false; }
    if (!builder->build(type, tile)) {
        why = "build refused: " + std::string(Broodwar->getLastError().c_str());
        if (type != UnitTypes::Protoss_Assimilator && type != UnitTypes::Protoss_Nexus) badTiles_.insert(tile.x * 10000 + tile.y);
        return false;
    }
    builderOut = builder;
    tileOut = tile;
    return true;
}

bool BuildExecutor::isBuilder(Unit u) const {
    for (auto& w : watches_) if (w.builder == u) return true;
    return false;
}

// 내려진 건설 명령이 건물로 이어졌는지 본다. 막혔으면(일꾼이 놀고 건물이 없음) 다시 내린다.
void BuildExecutor::checkBuildWatches() {
    int now = Broodwar->getFrameCount();
    for (size_t i = 0; i < watches_.size();) {
        BuildWatch& w = watches_[i];
        // 놓였는지: 명령한 자리에 그 유형 건물이 생겼는가. 예전엔 '유형 수가 늘었나'로 봐서, 같은 유형을 여러 개 명령하면
        // 첫 건물 하나에 감시가 전부 풀렸다 (2026-11-08: 파일런 3개 중 1개 놓이자 예약 300이 풀리고 예비 해제 오탐)
        bool placed = false;
        if (w.tile.isValid()) {
            for (auto u : Broodwar->getUnitsOnTile(w.tile.x, w.tile.y))
                if (u->getType() == w.type && u->getPlayer() == Broodwar->self()) placed = true;
        } else {
            int sameBefore = 0;  // 이 감시보다 먼저 만든 같은 유형 감시 수
            for (size_t k = 0; k < i; ++k) if (watches_[k].type == w.type) ++sameBefore;
            placed = countAll(w.type) > w.expectedCount + sameBefore;
        }
        if (placed) {
            if (Request* r = findRequest(w.requestId)) { r->state = "done"; r->doneFrame = now; }
            watches_.erase(watches_.begin() + static_cast<long>(i));
            continue;
        }
        bool stuck = !w.builder || !w.builder->exists() || (w.builder->isIdle() && now - w.issuedFrame > Broodwar->getLatencyFrames() + 8);
        int confirm = w.type.isResourceDepot() ? kBuildConfirmFrames * 3 : kBuildConfirmFrames;
        if ((stuck || now - w.issuedFrame > confirm) && now - w.issuedFrame >= kReissueInterval) {
            if (++w.retries > kMaxBuildRetries) {
                Broodwar->printf("build %s abandoned after %d retries", w.type.c_str(), w.retries);
                abandoned_.push_back(w.type.c_str());
                if (Request* r = findRequest(w.requestId)) { r->state = "failed"; r->reason = "abandoned after " + std::to_string(w.retries) + " retries"; r->doneFrame = now; }
                watches_.erase(watches_.begin() + static_cast<long>(i));
                continue;
            }
            // 이 프로브는 못 갔다(갇혔거나 다른 일): 다음엔 다른 프로브를 고른다. 모두 실패했으면 목록을 비우고 다시 돈다
            if (w.builder && std::find(w.tried.begin(), w.tried.end(), w.builder->getID()) == w.tried.end()) w.tried.push_back(w.builder->getID());
            Unit b = nullptr;
            TilePosition tile;
            std::string why;
            // 다시 고를 때 자기 자리를 겹침으로 치지 않도록 잠시 비운다
            w.tile = TilePositions::Invalid;
            bool ok = issueBuild(w.type, w.anchor, b, tile, why, &w.tried);
            if (!ok && why == "no free worker" && !w.tried.empty()) { w.tried.clear(); ok = issueBuild(w.type, w.anchor, b, tile, why); }
            if (ok) { w.builder = b; w.tile = tile; w.issuedFrame = now; }
            else Broodwar->printf("re-issue %s failed: %s", w.type.c_str(), why.c_str());
        }
        ++i;
    }
}
