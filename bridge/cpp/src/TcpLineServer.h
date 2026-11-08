// 줄 단위 TCP 서버. 네트워크 스레드가 받은 줄을 큐에 넣고, 게임 스레드(onFrame)가 꺼내 처리한 뒤
// 보낼 줄을 큐에 넣으면 쓰기 스레드가 전송한다. 게임 스레드는 절대 소켓에서 막히지 않는다.
// 한 번에 클라이언트 하나만 받는다(에피소드는 순차적이다). 끊기면 다음 연결을 기다린다.
#pragma once
#include <atomic>
#include <condition_variable>
#include <deque>
#include <mutex>
#include <string>
#include <thread>

class TcpLineServer {
public:
    TcpLineServer() = default;
    ~TcpLineServer();
    TcpLineServer(const TcpLineServer&) = delete;
    TcpLineServer& operator=(const TcpLineServer&) = delete;

    // host: "0.0.0.0" 등. 실패하면 false, lastError()에 이유.
    bool start(const std::string& host, int port);
    void stop();

    // 게임 스레드용
    bool pollLine(std::string& line);          // 받은 줄 하나. 없으면 false
    bool waitLine(std::string& line, int timeoutMs);  // 줄이 올 때까지 최대 timeoutMs 기다린다 (프레임 블로킹용)
    void sendLine(const std::string& line);    // '\n' 없이 넘긴다
    bool connected() const { return connected_.load(); }
    // 연결이 새로 끊겼으면 한 번 true (대기 중 명령 취소용)
    bool takeDisconnectEvent();
    const std::string& lastError() const { return error_; }

private:
    void acceptLoop();
    void readLoop(long long sock);
    void writeLoop(long long sock);
    void closeClient();

    std::string host_;
    int port_ = 0;
    long long listenSock_ = -1;
    long long clientSock_ = -1;
    std::thread acceptThread_, readThread_, writeThread_;
    std::atomic<bool> running_{false}, connected_{false}, disconnectEvent_{false};
    std::mutex inMu_, outMu_;
    std::condition_variable inCv_, outCv_;
    std::deque<std::string> inbox_, outbox_;
    std::string error_;
};
