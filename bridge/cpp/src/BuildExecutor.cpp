#include "BuildExecutor.h"

#include <algorithm>
#include <cstdlib>
#include <fstream>

#include "MiniJson.h"

using namespace BWAPI;
namespace mj = minijson;

namespace {
const int kProtocolVersion = 1;
const int kDefaultPort = 15800;
const int kMaxBuildRetries = 40;       // 건설 위치/명령 거부 재시도 상한 (프레임마다 1회)
const int kBuildConfirmFrames = 600;   // 건설 명령 뒤 건물이 생기지 않으면 다시 내리는 한계

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
        default: return UnitTypes::None;
    }
}
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
    while (episodeActive_ && !pending_.active && endFrame_ < 0 && server_.connected() && !wantRestart_) {
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

    // 에피소드 중에는 최대 속도, 대기 중에는 보통 속도(창이 응답하고 CPU 를 덜 쓴다)
    int wantSpeed = (episodeActive_ || pending_.active) ? 0 : 42;
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
        // 새 일꾼 배정 (A1)
        if (!patches_.empty()) {
            size_t best = 0;
            int bestLoad = 1 << 30;
            for (size_t i = 0; i < patches_.size(); ++i) {
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
    }
}

void BuildExecutor::onUnitDestroy(Unit unit) {
    workerPatch_.erase(unit->getID());
    for (auto& w : watches_) if (w.builder == unit) w.builder = nullptr;
}

void BuildExecutor::onSendText(std::string text) {
    if (text == "/status") Broodwar->printf("frame %d target %d zealots %d pending %s", Broodwar->getFrameCount(), target_, zealotsCompleted_, pending_.active ? pending_.type.c_str() : "-");
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
        w.key("actions").raw("{\"0\":\"worker\",\"1\":\"pylon\",\"2\":\"gateway\",\"3\":\"zealot\",\"8\":\"wait\"}");
        w.key("latency_frames").value(Broodwar->getLatencyFrames());
        w.key("end_includes_lag").value(false);
        reply(w.str());
    } else if (type == "reset") {
        target_ = m["target"].asInt(0);
        if (target_ <= 0) { sendError(id, "target 필요", false); return; }
        seed_ = m.count("seed") ? m["seed"].asInt(-1) : -1;
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
        if (action != 8 && (action < 0 || action > 3)) { sendError(id, "모르는 action", false); return; }
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
    mj::Writer ex;
    ex.key("gateways_ready").value(countCompleted(UnitTypes::Protoss_Gateway))
      .key("pylons_ready").value(countCompleted(UnitTypes::Protoss_Pylon))
      .key("zealots_in_production").value(zIssued)
      .key("prefix").intArray(commandLog_);
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
        if (!u->isIdle()) continue;
        auto it = workerPatch_.find(u->getID());
        Unit p = it != workerPatch_.end() ? it->second : (patches_.empty() ? nullptr : patches_[0]);
        if (p && p->exists()) u->gather(p);
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

bool BuildExecutor::canAffordSupply(UnitType t) const {
    // 실행기가 내린 명령(큐 포함)을 모두 센 값으로 판정한다. supplyUsed() 는 큐에서 대기 중인 유닛을 세지 않는다
    Player me = Broodwar->self();
    int used = std::max(me->supplyUsed(), issuedSupply_);
    return used + t.supplyRequired() <= me->supplyTotal();
}

Unit BuildExecutor::pickBuilder(TilePosition near) const {
    Unit best = nullptr;
    int bestD = 1 << 30;
    Position target(near);
    for (auto u : Broodwar->self()->getUnits()) {
        if (!u->getType().isWorker() || !u->isCompleted()) continue;
        if (u->isCarryingMinerals() || u->isConstructing()) continue;
        if (isBuilder(u)) continue;  // 다른 건설 명령을 수행하러 가는 중. 다시 고르면 그 명령이 취소된다
        int d = u->getDistance(target);
        if (d < bestD) { bestD = d; best = u; }
    }
    return best;
}

TilePosition BuildExecutor::findBuildTile(UnitType type, TilePosition anchor, int maxRadius, Unit builder) const {
    // 결정론적 나선 탐색. 같은 상황이면 같은 자리를 고른다 (노이즈 줄이기)
    for (int r = 0; r <= maxRadius; ++r) {
        for (int dx = -r; dx <= r; ++dx) {
            for (int dy = -r; dy <= r; ++dy) {
                if (std::max(std::abs(dx), std::abs(dy)) != r) continue;
                TilePosition t(anchor.x + dx, anchor.y + dy);
                if (!t.isValid()) continue;
                if (type.requiresPsi() && !Broodwar->hasPower(t, type)) continue;
                if (!Broodwar->canBuildHere(t, type, builder, false)) continue;
                // 아직 놓이지 않은 건설 명령의 자리와 겹치면 피한다 (canBuildHere 는 명령만 내린 자리를 모른다)
                bool overlaps = false;
                for (auto& w : watches_) {
                    if (!w.tile.isValid()) continue;
                    bool sepX = t.x + type.tileWidth() <= w.tile.x || w.tile.x + w.type.tileWidth() <= t.x;
                    bool sepY = t.y + type.tileHeight() <= w.tile.y || w.tile.y + w.type.tileHeight() <= t.y;
                    if (!sepX && !sepY) { overlaps = true; break; }
                }
                if (overlaps) continue;
                // 미네랄 길을 막지 않도록 넥서스-미네랄 사이는 피한다
                if (mainNexus_) {
                    Position c(t.x * 32 + type.tileWidth() * 16, t.y * 32 + type.tileHeight() * 16);
                    bool blocks = false;
                    for (auto m : patches_) if (m->getDistance(c) < 96) blocks = true;
                    if (blocks) continue;
                }
                return t;
            }
        }
    }
    return TilePositions::Invalid;
}

Unit BuildExecutor::pickGateway() const {
    Unit best = nullptr;
    int bestQ = 1 << 30, bestT = 1 << 30;
    for (auto u : Broodwar->self()->getUnits()) {
        if (u->getType() != UnitTypes::Protoss_Gateway || !u->isCompleted()) continue;
        int q = static_cast<int>(u->getTrainingQueue().size());
        int t = u->getRemainingTrainTime();
        if (q < bestQ || (q == bestQ && t < bestT)) { bestQ = q; bestT = t; best = u; }
    }
    return best;
}

// 명령을 내릴 수 있으면 내리고 true. 아니면 why에 이유(접두사 "fatal:"이면 재시도 없이 실패).
bool BuildExecutor::tryExecute(int action, std::string& why) {
    Player me = Broodwar->self();
    UnitType type = typeOf(action);
    if (type == UnitTypes::None) { why = "fatal:unknown action"; return false; }

    if (pending_.retries > kMaxBuildRetries) { why = "fatal:command refused repeatedly"; return false; }

    // 스타1은 건물 비용을 명령 때가 아니라 일꾼이 도착해 놓을 때 뺀다. 아직 놓이지 않은 건설 명령의 비용을 예약해
    // 두지 않으면 같은 돈으로 두 번 명령하게 된다 (2026-11-08 실게임: 게이트 2개 명령에 1개만 지어짐).
    int reserved = 0;
    for (auto& w : watches_) reserved += w.type.mineralPrice();
    if (me->minerals() - reserved < type.mineralPrice()) { why = "minerals"; return false; }
    if (type.supplyRequired() > 0 && !canAffordSupply(type)) {
        // 짓고 있는(명령만 내린 것 포함) 파일런이 모두 완성돼도 모자라면 영원히 불가능 → 즉시 실패
        int pylonsComing = countAll(UnitTypes::Protoss_Pylon) - countCompleted(UnitTypes::Protoss_Pylon);
        for (auto& w : watches_) if (w.type == UnitTypes::Protoss_Pylon) ++pylonsComing;
        int futureTotal = std::min(400, me->supplyTotal() + 16 * pylonsComing);  // BW 2배 단위, 최대 200
        int used = std::max(me->supplyUsed(), issuedSupply_);
        if (used + type.supplyRequired() > futureTotal) { why = "fatal:supply impossible (need pylon)"; return false; }
        why = "supply";
        return false;
    }

    if (action == 0) {
        if (!mainNexus_ || !mainNexus_->exists()) { why = "fatal:no nexus"; return false; }
        // SC2 봇과 같이 큐 적재를 허용한다(넥서스 큐 최대 5). 큐가 가득 차면 기다린다
        if (mainNexus_->getTrainingQueue().size() >= 5) { why = "nexus queue full"; return false; }
        if (!mainNexus_->train(type)) { why = "train refused: " + std::string(Broodwar->getLastError().c_str()); ++pending_.retries; return false; }
        issuedSupply_ += type.supplyRequired();
        return true;
    }
    if (action == 3) {
        Unit g = pickGateway();
        if (!g) { why = countAll(UnitTypes::Protoss_Gateway) ? "gateway not complete" : "fatal:no gateway"; return false; }
        if (!g->train(type)) { why = "train refused: " + std::string(Broodwar->getLastError().c_str()); ++pending_.retries; return false; }
        issuedSupply_ += type.supplyRequired();
        return true;
    }

    // 건물 (1 파일런, 2 게이트)
    TilePosition anchor;
    if (action == 1) {
        if (!mainNexus_) { why = "fatal:no nexus"; return false; }
        TilePosition nt = mainNexus_->getTilePosition();
        int dx = enemyStart_.x > nt.x ? 1 : (enemyStart_.x < nt.x ? -1 : 0);
        int dy = enemyStart_.y > nt.y ? 1 : (enemyStart_.y < nt.y ? -1 : 0);
        int dist = countAll(UnitTypes::Protoss_Pylon) == 0 ? 5 : 7;  // SC2 봇: 첫 파일런 3, 이후 5~7 (SC1 타일 단위로 조정)
        anchor = TilePosition(nt.x + dx * dist, nt.y + dy * dist);
    } else {
        if (countCompleted(UnitTypes::Protoss_Pylon) == 0) { why = countAll(UnitTypes::Protoss_Pylon) ? "pylon not complete" : "fatal:no pylon"; return false; }
        Unit pylon = nullptr;
        for (auto u : me->getUnits()) if (u->getType() == UnitTypes::Protoss_Pylon && u->isCompleted()) { pylon = u; break; }
        anchor = pylon->getTilePosition();
    }
    Unit builder = nullptr;
    TilePosition tile;
    int before = countAll(type);
    if (!issueBuild(type, anchor, builder, tile, why)) { ++pending_.retries; return false; }
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
bool BuildExecutor::issueBuild(UnitType type, TilePosition anchor, Unit& builderOut, TilePosition& tileOut, std::string& why) {
    Unit builder = pickBuilder(anchor);
    if (!builder) { why = "no free worker"; return false; }
    TilePosition tile = findBuildTile(type, anchor, 12, builder);
    if (tile == TilePositions::Invalid) { why = "no build tile"; return false; }
    if (!builder->build(type, tile)) { why = "build refused: " + std::string(Broodwar->getLastError().c_str()); return false; }
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
        if (countAll(w.type) > w.expectedCount) { watches_.erase(watches_.begin() + static_cast<long>(i)); continue; }
        bool stuck = !w.builder || !w.builder->exists() || (w.builder->isIdle() && now - w.issuedFrame > Broodwar->getLatencyFrames() + 8);
        if (stuck || now - w.issuedFrame > kBuildConfirmFrames) {
            if (++w.retries > kMaxBuildRetries) {
                Broodwar->printf("build %s abandoned after %d retries", w.type.c_str(), w.retries);
                watches_.erase(watches_.begin() + static_cast<long>(i));
                continue;
            }
            Unit b = nullptr;
            TilePosition tile;
            std::string why;
            // 다시 고를 때 자기 자리를 겹침으로 치지 않도록 잠시 비운다
            w.tile = TilePositions::Invalid;
            if (issueBuild(w.type, w.anchor, b, tile, why)) { w.builder = b; w.tile = tile; w.issuedFrame = now; }
            else Broodwar->printf("re-issue %s failed: %s", w.type.c_str(), why.c_str());
        }
        ++i;
    }
}
