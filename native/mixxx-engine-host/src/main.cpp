#include "host.h"
#include <QCoreApplication>
#include <QSocketNotifier>
#include <cerrno>
#include <csignal>
#include <fcntl.h>
#include <unistd.h>
#ifdef DJALY_WITH_MIXXX
#include <QApplication>
#endif

int main(int argc, char** argv) {
    std::signal(SIGPIPE, SIG_IGN);
#ifdef DJALY_WITH_MIXXX
    qputenv("QT_QPA_PLATFORM", "offscreen");
    QApplication app(argc, argv); // Qt runtime only; no windows, skins or library.
#else
    QCoreApplication app(argc, argv);
#endif
    app.setApplicationName("djaly-mixxx-engine-host");
    Host host(makeBackend());
    constexpr qsizetype maxLine = 1024 * 1024 + 4096;
    QByteArray pending;
    bool discarding = false;
    const int flags = fcntl(STDIN_FILENO, F_GETFL);
    if (flags < 0 || fcntl(STDIN_FILENO, F_SETFL, flags | O_NONBLOCK) < 0) return 2;
    QSocketNotifier input(STDIN_FILENO, QSocketNotifier::Read);
    QObject::connect(&input, &QSocketNotifier::activated, &app, [&] {
        char buffer[4096];
        // Bounded work per turn prevents a busy input pipe starving Qt/audio control.
        for (int batch = 0; batch < 16; ++batch) {
            const auto count = read(STDIN_FILENO, buffer, sizeof(buffer));
            if (count == 0) { if (!pending.isEmpty() && !discarding) host.malformed("Unterminated NDJSON at EOF"); input.setEnabled(false); app.quit(); return; }
            if (count < 0) { if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR) app.exit(2); return; }
            for (ssize_t i = 0; i < count; ++i) {
                if (buffer[i] == '\n') {
                    if (!discarding) host.line(pending);
                    pending.clear(); discarding = false;
                } else if (!discarding) {
                    pending.append(buffer[i]);
                    if (pending.size() > maxLine) { pending.clear(); discarding = true; host.malformed("NDJSON line exceeds the 1 MiB params budget plus envelope allowance"); }
                }
            }
        }
    });
    return app.exec();
}
