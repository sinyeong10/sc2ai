#include "TcpLineServer.h"

#include <chrono>
#include <cstring>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <ws2tcpip.h>
#pragma comment(lib, "ws2_32.lib")
typedef SOCKET sock_t;
static const sock_t kInvalid = INVALID_SOCKET;
static void closeSock(sock_t s) { closesocket(s); }
static bool initSockets() {
    static bool done = false;
    if (done) return true;
    WSADATA w;
    done = WSAStartup(MAKEWORD(2, 2), &w) == 0;
    return done;
}
#else
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include <unistd.h>
typedef int sock_t;
static const sock_t kInvalid = -1;
static void closeSock(sock_t s) { ::close(s); }
static bool initSockets() { return true; }
#endif

TcpLineServer::~TcpLineServer() { stop(); }

bool TcpLineServer::start(const std::string& host, int port) {
    if (!initSockets()) { error_ = "socket init failed"; return false; }
    host_ = host;
    port_ = port;
    sock_t s = ::socket(AF_INET, SOCK_STREAM, 0);
    if (s == kInvalid) { error_ = "socket() failed"; return false; }
    int one = 1;
    setsockopt(s, SOL_SOCKET, SO_REUSEADDR, reinterpret_cast<const char*>(&one), sizeof(one));
    sockaddr_in addr;
    std::memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons(static_cast<unsigned short>(port));
#ifdef _WIN32
    // _WIN32_WINNT=0x0501(XP, BWAPI 프로젝트와 동일)에서는 inet_pton 이 숨겨진다. IPv4 점 표기만 받으므로 inet_addr 로 충분.
    addr.sin_addr.s_addr = inet_addr(host.c_str());
    if (addr.sin_addr.s_addr == INADDR_NONE && host != "255.255.255.255") { error_ = "bad host"; closeSock(s); return false; }
#else
    if (inet_pton(AF_INET, host.c_str(), &addr.sin_addr) != 1) { error_ = "bad host"; closeSock(s); return false; }
#endif
    if (bind(s, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) != 0) { error_ = "bind() failed"; closeSock(s); return false; }
    if (listen(s, 1) != 0) { error_ = "listen() failed"; closeSock(s); return false; }
    listenSock_ = static_cast<long long>(s);
    running_ = true;
    acceptThread_ = std::thread(&TcpLineServer::acceptLoop, this);
    return true;
}

void TcpLineServer::stop() {
    if (!running_.exchange(false)) return;
    closeClient();
    if (listenSock_ != -1) { closeSock(static_cast<sock_t>(listenSock_)); listenSock_ = -1; }
    outCv_.notify_all();
    // 읽기/쓰기 스레드는 acceptLoop 만 join 한다. 여기서도 join 하면 같은 std::thread 를 두 곳에서 join 하게 되어
    // 두 번째가 system_error 를 던지고(소멸자 안이면 terminate → 0xc0000409) 게임이 죽는다. 2026-11-08 실게임에서 확인.
    if (acceptThread_.joinable() && std::this_thread::get_id() != acceptThread_.get_id()) acceptThread_.join();
}

void TcpLineServer::closeClient() {
    // 소켓만 닫는다. 읽기 스레드는 recv 가 실패해 끝나고, acceptLoop 가 그것을 join 한 뒤 쓰기 스레드도 join 한다.
    if (clientSock_ != -1) {
#ifdef _WIN32
        shutdown(static_cast<sock_t>(clientSock_), SD_BOTH);
#else
        shutdown(static_cast<sock_t>(clientSock_), SHUT_RDWR);
#endif
        closeSock(static_cast<sock_t>(clientSock_));
        clientSock_ = -1;
    }
    connected_ = false;
    outCv_.notify_all();
}

void TcpLineServer::acceptLoop() {
    while (running_) {
        sockaddr_in peer;
        socklen_t len = sizeof(peer);
        sock_t c = accept(static_cast<sock_t>(listenSock_), reinterpret_cast<sockaddr*>(&peer), &len);
        if (c == kInvalid) { if (!running_) break; continue; }
        int one = 1;
        setsockopt(c, IPPROTO_TCP, TCP_NODELAY, reinterpret_cast<const char*>(&one), sizeof(one));
        closeClient();  // 이전 클라이언트 정리
        {
            std::lock_guard<std::mutex> a(inMu_);
            std::lock_guard<std::mutex> b(outMu_);
            inbox_.clear();
            outbox_.clear();
        }
        clientSock_ = static_cast<long long>(c);
        connected_ = true;
        readThread_ = std::thread(&TcpLineServer::readLoop, this, clientSock_);
        writeThread_ = std::thread(&TcpLineServer::writeLoop, this, clientSock_);
        // 읽기 스레드가 끝날 때까지(끊길 때까지) 기다렸다가 다음 연결을 받는다
        if (readThread_.joinable()) readThread_.join();
        connected_ = false;
        disconnectEvent_ = true;
        outCv_.notify_all();
        if (writeThread_.joinable()) writeThread_.join();
        if (clientSock_ != -1) { closeSock(static_cast<sock_t>(clientSock_)); clientSock_ = -1; }
    }
}

void TcpLineServer::readLoop(long long sockll) {
    sock_t sock = static_cast<sock_t>(sockll);
    std::string buf;
    char tmp[4096];
    while (running_) {
        int n = recv(sock, tmp, sizeof(tmp), 0);
        if (n <= 0) break;
        buf.append(tmp, static_cast<size_t>(n));
        size_t pos;
        while ((pos = buf.find('\n')) != std::string::npos) {
            std::string line = buf.substr(0, pos);
            buf.erase(0, pos + 1);
            if (!line.empty() && line.back() == '\r') line.pop_back();
            if (line.empty()) continue;
            {
                std::lock_guard<std::mutex> g(inMu_);
                inbox_.push_back(line);
            }
            inCv_.notify_one();
        }
    }
    inCv_.notify_all();  // 끊김: 기다리던 게임 스레드를 깨운다
}

void TcpLineServer::writeLoop(long long sockll) {
    sock_t sock = static_cast<sock_t>(sockll);
    while (running_) {
        std::string line;
        {
            std::unique_lock<std::mutex> g(outMu_);
            outCv_.wait(g, [&] { return !outbox_.empty() || !connected_ || !running_; });
            if (outbox_.empty()) { if (!connected_ || !running_) return; continue; }
            line = outbox_.front();
            outbox_.pop_front();
        }
        line += '\n';
        size_t off = 0;
        while (off < line.size()) {
            int n = send(sock, line.data() + off, static_cast<int>(line.size() - off), 0);
            if (n <= 0) return;
            off += static_cast<size_t>(n);
        }
    }
}

bool TcpLineServer::pollLine(std::string& line) {
    std::lock_guard<std::mutex> g(inMu_);
    if (inbox_.empty()) return false;
    line = inbox_.front();
    inbox_.pop_front();
    return true;
}

bool TcpLineServer::waitLine(std::string& line, int timeoutMs) {
    std::unique_lock<std::mutex> g(inMu_);
    inCv_.wait_for(g, std::chrono::milliseconds(timeoutMs), [&] { return !inbox_.empty() || !connected_ || !running_; });
    if (inbox_.empty()) return false;
    line = inbox_.front();
    inbox_.pop_front();
    return true;
}

void TcpLineServer::sendLine(const std::string& line) {
    {
        std::lock_guard<std::mutex> g(outMu_);
        if (!connected_) return;
        outbox_.push_back(line);
    }
    outCv_.notify_one();
}

bool TcpLineServer::takeDisconnectEvent() { return disconnectEvent_.exchange(false); }
