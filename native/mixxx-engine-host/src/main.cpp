#include "host.h"
#include <QCoreApplication>
#include <QSocketNotifier>
#include <cerrno>
#include <csignal>
#include <QTimer>
#ifdef Q_OS_WIN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <io.h>
#include <fcntl.h>
#else
#include <fcntl.h>
#include <unistd.h>
#endif
#ifdef PLUMDECK_WITH_MIXXX
#include <QApplication>
#endif

int main(int argc, char** argv) {
#ifdef Q_OS_WIN
    _setmode(_fileno(stdout), _O_BINARY);
#else
    std::signal(SIGPIPE, SIG_IGN);
#endif
#ifdef PLUMDECK_WITH_MIXXX
    qputenv("QT_QPA_PLATFORM", "offscreen");
    QApplication app(argc, argv); // Qt runtime only; no windows, skins or library.
#else
    QCoreApplication app(argc, argv);
#endif
    app.setApplicationName("plumdeck-mixxx-engine-host");
    Host host(makeBackend());
    constexpr qsizetype maxLine = 1024 * 1024 + 4096;
    QByteArray pending;
    bool discarding = false;
    const auto consume = [&](const char* buffer, qint64 count) {
        for (qint64 i = 0; i < count; ++i) {
            if (buffer[i] == '\n') {
                if (!discarding) host.line(pending);
                pending.clear(); discarding = false;
            } else if (!discarding) {
                pending.append(buffer[i]);
                if (pending.size() > maxLine) { pending.clear(); discarding = true; host.malformed("NDJSON line exceeds the 1 MiB params budget plus envelope allowance"); }
            }
        }
    };
    const auto eof = [&] {
        if (!pending.isEmpty() && !discarding) host.malformed("Unterminated NDJSON at EOF");
        app.quit();
    };
#ifdef Q_OS_WIN
    // QSocketNotifier cannot monitor anonymous Win32 pipes. Poll only the
    // available bytes, bounded per Qt turn so audio/control cannot be starved.
    const HANDLE pipe = GetStdHandle(STD_INPUT_HANDLE);
    if (pipe == INVALID_HANDLE_VALUE || GetFileType(pipe) != FILE_TYPE_PIPE) return 2;
    QTimer input;
    input.setInterval(2);
    QObject::connect(&input, &QTimer::timeout, &app, [&] {
        char buffer[4096];
        for (int batch = 0; batch < 16; ++batch) {
            DWORD available = 0, count = 0;
            if (!PeekNamedPipe(pipe, nullptr, 0, nullptr, &available, nullptr)) {
                input.stop();
                if (GetLastError() == ERROR_BROKEN_PIPE) eof(); else app.exit(2);
                return;
            }
            if (!available) return;
            if (!ReadFile(pipe, buffer, qMin<DWORD>(available, sizeof(buffer)), &count, nullptr)) {
                input.stop();
                if (GetLastError() == ERROR_BROKEN_PIPE) eof(); else app.exit(2);
                return;
            }
            if (!count) { input.stop(); eof(); return; }
            consume(buffer, count);
        }
    });
    input.start();
#else
    const int flags = fcntl(STDIN_FILENO, F_GETFL);
    if (flags < 0 || fcntl(STDIN_FILENO, F_SETFL, flags | O_NONBLOCK) < 0) return 2;
    QSocketNotifier input(STDIN_FILENO, QSocketNotifier::Read);
    QObject::connect(&input, &QSocketNotifier::activated, &app, [&] {
        char buffer[4096];
        for (int batch = 0; batch < 16; ++batch) {
            const auto count = read(STDIN_FILENO, buffer, sizeof(buffer));
            if (count == 0) { input.setEnabled(false); eof(); return; }
            if (count < 0) { if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR) app.exit(2); return; }
            consume(buffer, count);
        }
    });
#endif
    return app.exec();
}
