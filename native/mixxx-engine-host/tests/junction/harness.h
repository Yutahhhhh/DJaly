#pragma once
// Minimal assertion harness for the Junction core tests.
//
// Deliberately dependency-free: these tests must build in the fast seam
// configuration, without Mixxx, an audio device or GoogleTest, so that the
// protocol/clock/state-machine contracts can be exercised on every change.
#include <QString>
#include <cmath>
#include <cstdio>
#include <functional>
#include <string>
#include <vector>
#include <type_traits>

namespace jtest {

struct Case {
    std::string suite;
    std::string name;
    std::function<void()> body;
};

std::vector<Case>& registry();
int runAll(const char* filter);
void fail(const char* file, int line, const std::string& message);
[[noreturn]] void skip(const std::string& reason);

struct Registrar {
    Registrar(const char* suite, const char* name, std::function<void()> body) {
        registry().push_back({suite, name, std::move(body)});
    }
};

inline std::string show(const QString& value) { return value.toStdString(); }
inline std::string show(const std::string& value) { return value; }
inline std::string show(const char* value) { return value ? value : "(null)"; }
inline std::string show(bool value) { return value ? "true" : "false"; }
template <typename T> std::string show(const T& value) { if constexpr (std::is_enum_v<T>) return std::to_string(static_cast<std::underlying_type_t<T>>(value)); else return std::to_string(value); }

} // namespace jtest

#define JTEST_CONCAT_INNER(a, b) a##b
#define JTEST_CONCAT(a, b) JTEST_CONCAT_INNER(a, b)

/// Declares a test case. Suite and name are free-form strings.
#define JTEST(suite, name)                                                          \
    static void JTEST_CONCAT(jtest_body_, __LINE__)();                              \
    static ::jtest::Registrar JTEST_CONCAT(jtest_reg_, __LINE__){                    \
            suite, name, []() { JTEST_CONCAT(jtest_body_, __LINE__)(); }};           \
    static void JTEST_CONCAT(jtest_body_, __LINE__)()

#define CHECK(condition)                                                            \
    do {                                                                            \
        if (!(condition)) ::jtest::fail(__FILE__, __LINE__, "expected: " #condition); \
    } while (0)

#define CHECK_EQ(actual, expected)                                                  \
    do {                                                                            \
        const auto& jtest_a = (actual);                                             \
        const auto& jtest_b = (expected);                                           \
        if (!(jtest_a == jtest_b))                                                  \
            ::jtest::fail(__FILE__, __LINE__,                                       \
                    std::string(#actual) + " == " + #expected + "\n      actual:   " + \
                            ::jtest::show(jtest_a) + "\n      expected: " + ::jtest::show(jtest_b)); \
    } while (0)

#define CHECK_NEAR(actual, expected, tolerance)                                     \
    do {                                                                            \
        const double jtest_a = static_cast<double>(actual);                         \
        const double jtest_b = static_cast<double>(expected);                       \
        if (!(std::fabs(jtest_a - jtest_b) <= (tolerance)))                         \
            ::jtest::fail(__FILE__, __LINE__,                                       \
                    std::string(#actual) + " ~= " + #expected + "\n      actual:   " + \
                            std::to_string(jtest_a) + "\n      expected: " + std::to_string(jtest_b) + \
                            " +/- " + std::to_string(static_cast<double>(tolerance))); \
    } while (0)
