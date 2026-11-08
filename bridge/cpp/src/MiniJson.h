// 최소 JSON: protocol.md의 평평한 요청만 읽고, 응답 문자열을 만든다.
// 외부 라이브러리 없이 빌드하기 위한 것이다. 중첩 객체/배열은 값을 건너뛴다.
#pragma once
#include <cstdlib>
#include <map>
#include <sstream>
#include <string>
#include <vector>

namespace minijson {

struct Value {
    enum Kind { Null, Bool, Number, String, Skipped } kind = Null;
    bool b = false;
    double num = 0;
    std::string str;
    bool isNumber() const { return kind == Number; }
    bool isString() const { return kind == String; }
    int asInt(int dflt = 0) const { return kind == Number ? static_cast<int>(num) : dflt; }
    std::string asString(const std::string& dflt = "") const { return kind == String ? str : dflt; }
};

using Object = std::map<std::string, Value>;

inline void skipWs(const std::string& s, size_t& i) {
    while (i < s.size() && (s[i] == ' ' || s[i] == '\t' || s[i] == '\r' || s[i] == '\n')) ++i;
}

inline bool parseString(const std::string& s, size_t& i, std::string& out) {
    if (i >= s.size() || s[i] != '"') return false;
    ++i;
    out.clear();
    while (i < s.size()) {
        char c = s[i++];
        if (c == '"') return true;
        if (c == '\\' && i < s.size()) {
            char e = s[i++];
            switch (e) {
                case 'n': out += '\n'; break;
                case 't': out += '\t'; break;
                case 'r': out += '\r'; break;
                case 'u': i += 4; out += '?'; break;  // 유니코드 이스케이프는 쓰지 않는다
                default: out += e;
            }
        } else {
            out += c;
        }
    }
    return false;
}

// 중첩 값([] 또는 {})을 괄호 짝으로 건너뛴다.
inline bool skipNested(const std::string& s, size_t& i) {
    int depth = 0;
    bool inStr = false;
    for (; i < s.size(); ++i) {
        char c = s[i];
        if (inStr) {
            if (c == '\\') ++i;
            else if (c == '"') inStr = false;
            continue;
        }
        if (c == '"') inStr = true;
        else if (c == '[' || c == '{') ++depth;
        else if (c == ']' || c == '}') {
            if (--depth == 0) { ++i; return true; }
        }
    }
    return false;
}

inline bool parseValue(const std::string& s, size_t& i, Value& v) {
    skipWs(s, i);
    if (i >= s.size()) return false;
    char c = s[i];
    if (c == '"') { v.kind = Value::String; return parseString(s, i, v.str); }
    if (c == '{' || c == '[') { v.kind = Value::Skipped; return skipNested(s, i); }
    if (s.compare(i, 4, "true") == 0) { v.kind = Value::Bool; v.b = true; i += 4; return true; }
    if (s.compare(i, 5, "false") == 0) { v.kind = Value::Bool; v.b = false; i += 5; return true; }
    if (s.compare(i, 4, "null") == 0) { v.kind = Value::Null; i += 4; return true; }
    const char* begin = s.c_str() + i;
    char* end = nullptr;
    double d = std::strtod(begin, &end);
    if (end == begin) return false;
    v.kind = Value::Number;
    v.num = d;
    i += static_cast<size_t>(end - begin);
    return true;
}

// 한 줄의 최상위 객체를 읽는다. 실패하면 false.
inline bool parseObject(const std::string& s, Object& out) {
    size_t i = 0;
    skipWs(s, i);
    if (i >= s.size() || s[i] != '{') return false;
    ++i;
    out.clear();
    while (true) {
        skipWs(s, i);
        if (i < s.size() && s[i] == '}') return true;
        std::string key;
        if (!parseString(s, i, key)) return false;
        skipWs(s, i);
        if (i >= s.size() || s[i] != ':') return false;
        ++i;
        Value v;
        if (!parseValue(s, i, v)) return false;
        out[key] = v;
        skipWs(s, i);
        if (i < s.size() && s[i] == ',') { ++i; continue; }
        if (i < s.size() && s[i] == '}') return true;
        return false;
    }
}

inline std::string quote(const std::string& s) {
    std::string o = "\"";
    for (char c : s) {
        switch (c) {
            case '"': o += "\\\""; break;
            case '\\': o += "\\\\"; break;
            case '\n': o += "\\n"; break;
            case '\r': o += "\\r"; break;
            case '\t': o += "\\t"; break;
            default:
                if (static_cast<unsigned char>(c) < 0x20) o += '?';  // 제어 문자는 버린다
                else o += c;
        }
    }
    return o + "\"";
}

// 응답 작성기. 순서대로 키를 더하고 str()로 끝낸다.
class Writer {
public:
    Writer& key(const std::string& k) {
        if (!first_) out_ << ',';
        first_ = false;
        out_ << quote(k) << ':';
        return *this;
    }
    Writer& value(int v) { out_ << v; return *this; }
    Writer& value(long long v) { out_ << v; return *this; }
    Writer& value(double v) { out_ << v; return *this; }
    Writer& value(bool v) { out_ << (v ? "true" : "false"); return *this; }
    Writer& value(const char* v) { out_ << quote(v); return *this; }
    Writer& value(const std::string& v) { out_ << quote(v); return *this; }
    Writer& null() { out_ << "null"; return *this; }
    Writer& raw(const std::string& v) { out_ << v; return *this; }
    Writer& intArray(const std::vector<int>& v) {
        out_ << '[';
        for (size_t i = 0; i < v.size(); ++i) { if (i) out_ << ','; out_ << v[i]; }
        out_ << ']';
        return *this;
    }
    std::string str() const { return "{" + out_.str() + "}"; }

private:
    std::ostringstream out_;
    bool first_ = true;
};

}  // namespace minijson
