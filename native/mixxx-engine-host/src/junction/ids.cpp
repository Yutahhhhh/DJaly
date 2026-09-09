#include "ids.h"
#include <QCryptographicHash>
#include <QRandomGenerator>
#include <cstdio>

namespace junction {
namespace {
// QRandomGenerator::system() is documented to draw from the OS CSPRNG
// (getentropy/arc4random on Apple platforms). Reading /dev/urandom directly is
// kept as a fallback so a hypothetical build without the system generator
// fails closed rather than falling back to a seeded PRNG.
bool fillFromUrandom(char* out, int count) {
    std::FILE* source = std::fopen("/dev/urandom", "rb");
    if (!source) return false;
    const size_t read = std::fread(out, 1, static_cast<size_t>(count), source);
    std::fclose(source);
    return read == static_cast<size_t>(count);
}
constexpr char kUrlSafe[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
} // namespace

QByteArray secureRandomBytes(int count) {
    if (count <= 0) return {};
    QByteArray bytes(count, Qt::Uninitialized);
    if (QRandomGenerator* system = QRandomGenerator::system()) {
        system->generate(reinterpret_cast<quint32*>(bytes.data()),
                reinterpret_cast<quint32*>(bytes.data() + (count / 4) * 4));
        const int tail = count % 4;
        if (tail) {
            const quint32 extra = system->generate();
            std::memcpy(bytes.data() + count - tail, &extra, static_cast<size_t>(tail));
        }
        return bytes;
    }
    if (!fillFromUrandom(bytes.data(), count)) return {};
    return bytes;
}

QString secureRandomHex(int count) {
    return QString::fromLatin1(secureRandomBytes(count).toHex());
}

QString secureRandomToken(int count) {
    const QByteArray bytes = secureRandomBytes(count);
    QString out;
    out.reserve(bytes.size());
    for (unsigned char byte : bytes) out.append(QLatin1Char(kUrlSafe[byte & 0x3F]));
    return out;
}

bool constantTimeEquals(const QByteArray& a, const QByteArray& b) {
    // Length is not secret here (both sides are fixed-width digests or tokens
    // of a declared size), but the content comparison must not short-circuit.
    if (a.size() != b.size()) return false;
    unsigned char difference = 0;
    for (int index = 0; index < a.size(); ++index)
        difference |= static_cast<unsigned char>(a[index]) ^ static_cast<unsigned char>(b[index]);
    return difference == 0;
}

QString sha256Hex(const QByteArray& data) {
    return QString::fromLatin1(QCryptographicHash::hash(data, QCryptographicHash::Sha256).toHex());
}

} // namespace junction
