#pragma once
#include <QString>
#include <QFile>
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

namespace platform_file {
inline int sync(int fd) {
#ifdef Q_OS_WIN
    return ::_commit(fd);
#else
    return ::fsync(fd);
#endif
}
// Open the final component without following links/reparse points. In
// particular, never downgrade the existing POSIX O_NOFOLLOW guarantee.
inline bool open(QFile& file, bool create) {
#ifdef Q_OS_WIN
    HANDLE handle = CreateFileW(reinterpret_cast<LPCWSTR>(file.fileName().utf16()),
        GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ, nullptr,
        create ? OPEN_ALWAYS : OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
    if (handle == INVALID_HANDLE_VALUE) return false;
    BY_HANDLE_FILE_INFORMATION info{};
    if (!GetFileInformationByHandle(handle, &info) ||
        (info.dwFileAttributes & (FILE_ATTRIBUTE_REPARSE_POINT | FILE_ATTRIBUTE_DIRECTORY))) {
        CloseHandle(handle);
        return false;
    }
    const int fd = _open_osfhandle(reinterpret_cast<intptr_t>(handle), _O_RDWR | _O_BINARY);
    if (fd < 0) { CloseHandle(handle); return false; }
#else
    const int fd = ::open(QFile::encodeName(file.fileName()).constData(),
        O_RDWR | O_NOFOLLOW | (create ? O_CREAT : 0), 0600);
    if (fd < 0) return false;
#endif
    if (file.open(fd, QIODevice::ReadWrite, QFileDevice::AutoCloseHandle)) return true;
#ifdef Q_OS_WIN
    _close(fd);
#else
    ::close(fd);
#endif
    return false;
}
}
