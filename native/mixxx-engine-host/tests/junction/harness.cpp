#include "harness.h"
#include <algorithm>
#include <exception>
#include <stdexcept>

namespace jtest {
namespace {
struct Skip : std::runtime_error { using std::runtime_error::runtime_error; };
struct Failure : std::runtime_error {
    using std::runtime_error::runtime_error;
};
} // namespace

std::vector<Case>& registry() {
    static std::vector<Case> cases;
    return cases;
}

void fail(const char* file, int line, const std::string& message) {
    throw Failure(std::string(file) + ":" + std::to_string(line) + ": " + message);
}

[[noreturn]] void skip(const std::string& reason) { throw Skip(reason); }

int runAll(const char* filter) {
    auto& cases = registry();
    std::stable_sort(cases.begin(), cases.end(),
            [](const Case& a, const Case& b) { return a.suite < b.suite; });
    int passed = 0, failed = 0, skipped = 0, filtered = 0;
    std::string currentSuite;
    for (const Case& test : cases) {
        const std::string label = test.suite + " :: " + test.name;
        if (filter && *filter && label.find(filter) == std::string::npos) { ++filtered; continue; }
        if (test.suite != currentSuite) {
            currentSuite = test.suite;
            std::printf("\n# %s\n", currentSuite.c_str());
        }
        try {
            test.body();
            std::printf("  ok   %s\n", test.name.c_str());
            ++passed;
        } catch (const Skip& reason) {
            ++skipped; std::printf("  SKIP %s: %s\n", test.name.c_str(), reason.what());
        } catch (const Failure& failure) {
            std::printf("  FAIL %s\n    %s\n", test.name.c_str(), failure.what());
            ++failed;
        } catch (const std::exception& error) {
            std::printf("  FAIL %s\n    unexpected exception: %s\n", test.name.c_str(), error.what());
            ++failed;
        } catch (...) {
            std::printf("  FAIL %s\n    unexpected non-standard exception\n", test.name.c_str());
            ++failed;
        }
    }
    std::printf("\n%d passed, %d failed", passed, failed);
    if (skipped) std::printf(", %d skipped", skipped);
    if (filtered) std::printf(", %d filtered out", filtered);
    std::printf("\n");
    if (passed + failed == 0) { std::fprintf(stderr, "No tests matched the requested filter.\n"); return 1; }
    return failed == 0 ? 0 : 1;
}

} // namespace jtest

int main(int argc, char** argv) {
    return jtest::runAll(argc > 1 ? argv[1] : "");
}
