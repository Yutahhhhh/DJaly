#pragma once
#include <QString>
#include <sndfile.h>

inline SNDFILE* openSoundFile(const QString& path, int mode, SF_INFO* info) {
#ifdef Q_OS_WIN
    return sf_wchar_open(reinterpret_cast<const wchar_t*>(path.utf16()), mode, info);
#else
    return sf_open(path.toUtf8().constData(), mode, info);
#endif
}
