#include "network_settings.h"
#include <QCryptographicHash>
#include <QDateTime>
#include <QJsonDocument>
#include <QMessageAuthenticationCode>
#include <QRegularExpression>
#include <QUrl>
#include <QUrlQuery>
#include <cmath>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QSaveFile>
#include <QStandardPaths>
#ifdef Q_OS_WIN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <wincrypt.h>
#endif
#ifdef __APPLE__
#include <Security/Security.h>
#endif
namespace junction {
namespace {
constexpr qint64 lifetimeMs = 30 * 60 * 1000;
constexpr int maxStoredBytes = 16384;
QJsonObject defaults() { return {{"stunUrls", QJsonArray{"stun:stun.l.google.com:19302"}}, {"turn", QJsonObject{}}}; }
bool boundedText(const QJsonValue& value, int maximum, bool required = true) {
    if (!value.isString()) return false;
    const auto s = value.toString();
    if ((required && s.isEmpty()) || s.toUtf8().size() > maximum) return false;
    for (const auto c : s) if (c.unicode() < 32 || c.unicode() == 127) return false;
    return true;
}
bool validUrl(const QJsonValue& value, bool turn) {
    if (!boundedText(value, 1024)) return false;
    const auto text = value.toString();
    const auto colon = text.indexOf(':');
    const auto scheme = text.left(colon).toLower();
    if (colon < 1 || (turn ? scheme != "turn" && scheme != "turns" : scheme != "stun")) return false;
    auto rest = text.mid(colon + 1);
    if (rest.startsWith("//")) rest = rest.mid(2);
    QUrl u(scheme + "://" + rest, QUrl::StrictMode);
    if (!u.isValid() || u.host().isEmpty() || !u.userInfo().isEmpty() || !u.path().isEmpty() || !u.fragment().isEmpty()) return false;
    if (u.port(3478) < 1 || u.port(3478) > 65535) return false;
    const auto queries = QUrlQuery(u).queryItems();
    if (queries.size() > 1) return false;
    if (!queries.isEmpty() && (!turn || queries[0].first != "transport" || (queries[0].second != "udp" && queries[0].second != "tcp" && queries[0].second != "tls"))) return false;
    return true;
}
QString validateUrls(const QJsonValue& v, bool turn, bool required) {
    if (!v.isArray() || v.toArray().size() > 8 || (required && v.toArray().isEmpty())) return "接続先は8件以内のURLで指定してください";
    for (const auto& url : v.toArray()) if (!validUrl(url, turn)) return turn ? "TURNのURLを確認してください（turn: または turns:）" : "探索用のURLを確認してください（stun:）";
    return {};
}
bool expiry(const QJsonValue& value, qint64 now, qint64* result) {
    if (!value.isDouble()) return false;
    const double n = value.toDouble();
    if (!std::isfinite(n) || std::floor(n) != n || n <= double(now) || n > double(now + 86400000LL)) return false;
    *result = qint64(n); return true;
}
QString validateConfig(const QJsonObject& config, qint64 now) {
    if (QJsonDocument(config).toJson(QJsonDocument::Compact).size() > maxStoredBytes) return "中継設定が大きすぎます";
    auto error = validateUrls(config["stunUrls"], false, false); if (!error.isEmpty()) return error;
    if (!config["turn"].isObject()) return "中継設定の形式を確認してください";
    const auto turn = config["turn"].toObject(); if (turn.isEmpty()) return {};
    error = validateUrls(turn["urls"], true, true); if (!error.isEmpty()) return error;
    const auto mode = turn["mode"].toString();
    for(auto it=turn.begin();it!=turn.end();++it){const auto key=it.key();if(key!="mode"&&key!="urls"&&(mode=="rest"?key!="secret":key!="username"&&key!="credential"&&key!="expiresAt"))return "対応していない中継設定が含まれています";}
    if (mode == "rest") {
        if (!boundedText(turn["secret"], 512) || turn["secret"].toString().toUtf8().size() < 32) return "中継サーバーと同じ32文字以上の共有シークレットを入力してください";
    } else if (mode == "temporary") {
        qint64 end = 0;
        if (!boundedText(turn["username"], 256) || !boundedText(turn["credential"], 1024)) return "発行された一時ユーザー名とパスワードを入力してください";
        if (!expiry(turn["expiresAt"], now, &end)) return "資格情報の有効期限を確認してください（期限切れ、または24時間より先です）";
        // This mode accepts TURN REST credentials with an encoded expiration,
        // not a long-lived static password relabelled as temporary by the UI.
        bool ok = false; const auto seconds = turn["username"].toString().section(':', 0, 0).toLongLong(&ok);
        if (!ok || seconds < 1 || seconds > (now + 86400000LL) / 1000 || seconds * 1000 < end - 1000) return "有効期限がユーザー名に含まれるTURN REST方式の一時資格情報を使用してください";
    } else return "対応していない中継認証方式です";
    return {};
}
#ifdef __APPLE__
CFMutableDictionaryRef keychainQuery() {
    auto q = CFDictionaryCreateMutable(kCFAllocatorDefault, 0, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    CFDictionarySetValue(q, kSecClass, kSecClassGenericPassword);
    CFDictionarySetValue(q, kSecAttrService, CFSTR("com.plumdeck.junction.network"));
    CFDictionarySetValue(q, kSecAttrAccount, CFSTR("settings-v1"));
    return q;
}
QString storeConfig(const QJsonObject& config) {
    const auto bytes = QJsonDocument(config).toJson(QJsonDocument::Compact);
    auto data = CFDataCreate(kCFAllocatorDefault, reinterpret_cast<const UInt8*>(bytes.constData()), bytes.size());
    auto query = keychainQuery();
    auto update = CFDictionaryCreateMutable(kCFAllocatorDefault, 0, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    CFDictionarySetValue(update, kSecValueData, data);
    auto status = SecItemUpdate(query, update);
    if (status == errSecItemNotFound) {
        CFDictionarySetValue(query, kSecValueData, data);
        CFDictionarySetValue(query, kSecAttrAccessible, kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly);
        status = SecItemAdd(query, nullptr);
    }
    CFRelease(data); CFRelease(update); CFRelease(query);
    return status == errSecSuccess ? QString{} : QStringLiteral("キーチェーンへ保存できません。Macの許可を確認してもう一度試してください");
}
QString eraseConfig() { auto q = keychainQuery(); const auto status = SecItemDelete(q); CFRelease(q); return status == errSecSuccess || status == errSecItemNotFound ? QString{} : QStringLiteral("キーチェーンの保存設定を削除できません"); }
#elif defined(Q_OS_WIN)
QString settingsPath() {
    return QStandardPaths::writableLocation(QStandardPaths::GenericDataLocation) + "/plumdeck/junction-network.dpapi";
}
QString storeConfig(const QJsonObject& config) {
    auto bytes = QJsonDocument(config).toJson(QJsonDocument::Compact);
    if (bytes.size() > maxStoredBytes) return "中継設定が大きすぎます";
    DATA_BLOB input{static_cast<DWORD>(bytes.size()), reinterpret_cast<BYTE*>(bytes.data())}, output{};
    if (!CryptProtectData(&input, L"Plumdeck Junction settings", nullptr, nullptr, nullptr, CRYPTPROTECT_UI_FORBIDDEN, &output)) return "Windowsのユーザー資格情報で中継設定を暗号化できません";
    const auto path = settingsPath();
    QDir().mkpath(QFileInfo(path).absolutePath());
    QSaveFile file(path);
    const bool ok = file.open(QIODevice::WriteOnly) && file.write(reinterpret_cast<const char*>(output.pbData), output.cbData) == output.cbData && file.commit();
    SecureZeroMemory(output.pbData, output.cbData); LocalFree(output.pbData);
    return ok ? QString{} : QStringLiteral("暗号化した中継設定を保存できません");
}
QString eraseConfig() {
    return !QFile::exists(settingsPath()) || QFile::remove(settingsPath()) ? QString{} : QStringLiteral("保存した中継設定を削除できません");
}
#else
QString storeConfig(const QJsonObject&) { return "この環境では安全な永続保存を利用できません。保存せず今回だけ使用してください"; }
QString eraseConfig() { return {}; }
#endif
}
NetworkSettings::NetworkSettings(bool readStored) : config_(defaults()), storageEnabled_(readStored && !qEnvironmentVariableIsSet("PLUMDECK_JUNCTION_EPHEMERAL_NETWORK")) {
#ifdef __APPLE__
    if (!storageEnabled_) return;
    auto query = keychainQuery(); CFDictionarySetValue(query, kSecReturnData, kCFBooleanTrue); CFDictionarySetValue(query, kSecMatchLimit, kSecMatchLimitOne);
    CFTypeRef result = nullptr; const auto status = SecItemCopyMatching(query, &result); CFRelease(query);
    if (status == errSecItemNotFound) return;
    if (status != errSecSuccess || !result || CFGetTypeID(result) != CFDataGetTypeID()) { if(result)CFRelease(result); storageError_="保存した中継設定を読み込めません。Macのキーチェーンの許可を確認してください"; return; }
    const auto data = static_cast<CFDataRef>(result); const auto size = CFDataGetLength(data);
    if (size > 0 && size <= maxStoredBytes) {
        const auto parsed = QJsonDocument::fromJson(QByteArray(reinterpret_cast<const char*>(CFDataGetBytePtr(data)), int(size)));
        const auto config = parsed.object();
        // Expired temporary credentials remain visible as expired; never mint
        // new validity for credentials recovered from safe storage.
        const auto end = config["turn"].toObject()["expiresAt"].toDouble();
        const auto checkTime = end > 1000 && end < double(QDateTime::currentMSecsSinceEpoch()) ? qint64(end) - 1000 : QDateTime::currentMSecsSinceEpoch();
        if (parsed.isObject() && validateConfig(config, checkTime).isEmpty()) {config_=config;saved_=true;}
        else storageError_="保存した中継設定の形式を確認してください";
    } else storageError_="保存した中継設定の形式を確認してください";
    CFRelease(result);
#elif defined(Q_OS_WIN)
    if (!storageEnabled_) return;
    QFile file(settingsPath());
    if (!file.exists()) return;
    if (!file.open(QIODevice::ReadOnly) || file.size() > maxStoredBytes + 4096) { storageError_="保存した中継設定を読み込めません"; return; }
    auto bytes=file.readAll();
    DATA_BLOB input{static_cast<DWORD>(bytes.size()), reinterpret_cast<BYTE*>(bytes.data())}, output{};
    if (!CryptUnprotectData(&input, nullptr, nullptr, nullptr, nullptr, CRYPTPROTECT_UI_FORBIDDEN, &output)) { storageError_="保存した中継設定を復号できません。保存時と同じWindowsユーザーで開いてください"; return; }
    if (output.cbData <= maxStoredBytes) {
        const auto parsed=QJsonDocument::fromJson(QByteArray(reinterpret_cast<const char*>(output.pbData), int(output.cbData)));
        const auto config=parsed.object();
        const auto end=config["turn"].toObject()["expiresAt"].toDouble();
        const auto now=QDateTime::currentMSecsSinceEpoch();
        const auto checkTime=end>1000 && end<double(now) ? qint64(end)-1000 : now;
        if (parsed.isObject() && validateConfig(config,checkTime).isEmpty()) { config_=config; saved_=true; }
        else storageError_="保存した中継設定の形式を確認してください";
    } else storageError_="保存した中継設定の形式を確認してください";
    SecureZeroMemory(output.pbData, output.cbData); LocalFree(output.pbData);
#else
    Q_UNUSED(readStored);
#endif
}
QJsonObject NetworkSettings::summary() const {
#ifdef Q_OS_WIN
    const auto storage=QStringLiteral("windows-dpapi");
#else
    const auto storage=QStringLiteral("keychain");
#endif
    QJsonObject result{{"stunUrls",config_["stunUrls"]},{"saved",saved_},{"storage",storage},{"detail",storageError_},{"errors",storageError_.isEmpty()?QJsonArray{}:QJsonArray{storageError_}}};
    auto turn = config_["turn"].toObject();
    if(!turn.isEmpty()) {
        turn.remove("secret");turn.remove("credential");
        turn["hasSecret"]=turn["mode"]=="rest";
        turn["expired"]=turn["mode"]=="temporary" && turn["expiresAt"].toDouble()<=double(QDateTime::currentMSecsSinceEpoch());
        result["turn"]=turn;
    }
    return result;
}
QString NetworkSettings::configure(const QJsonObject& input) {
    QJsonObject next{{"stunUrls",input.contains("stunUrls")?input["stunUrls"]:config_["stunUrls"]},{"turn",input.contains("turn")?input["turn"]:config_["turn"]}};
    auto turn=next["turn"].toObject();const auto old=config_["turn"].toObject();
    // Editing public settings may retain an existing secret only for the same
    // endpoint and authentication mode. A new endpoint requires explicit input.
    if(!turn.isEmpty()&&turn["mode"]==old["mode"]&&turn["urls"]==old["urls"]){
        for(const auto* key:{"secret","username","credential","expiresAt"})if(!turn.contains(key)&&old.contains(key))turn[key]=old[key];
        next["turn"]=turn;
    }
    const auto failure=validateConfig(next,QDateTime::currentMSecsSinceEpoch());if(!failure.isEmpty())return failure;
    const bool save=input["save"].toBool();const auto storage=storageEnabled_?(save?storeConfig(next):QString{}):(save?QStringLiteral("この設定インスタンスでは永続保存しません"):QString{});if(!storage.isEmpty())return storage;
    config_=next;saved_=save;storageError_.clear();return {};
}
QString NetworkSettings::clear() {const auto e=storageEnabled_?eraseConfig():QString{};if(!e.isEmpty())return e;config_=defaults();saved_=false;storageError_.clear();return {};}
QJsonArray NetworkSettings::credentials(const QString& sessionId,const QString& peerId,qint64 now,QString* error) const {
    QJsonArray result;if(!config_["stunUrls"].toArray().isEmpty())result.append(QJsonObject{{"urls",config_["stunUrls"]}});
    auto turn=config_["turn"].toObject();if(turn.isEmpty())return result;
    const auto failure=validateConfig(config_,now);if(!failure.isEmpty()){if(error)*error=failure;return {};}
    qint64 end=0;QString username,password;
    if(turn["mode"]=="rest") {
        end=now+lifetimeMs;
        const auto purpose=QCryptographicHash::hash((sessionId+":"+peerId).toUtf8(),QCryptographicHash::Sha256).toHex().left(24);
        username=QString::number(end/1000)+":plumdeck-"+QString::fromLatin1(purpose);
        password=QString::fromLatin1(QMessageAuthenticationCode::hash(username.toUtf8(),turn["secret"].toString().toUtf8(),QCryptographicHash::Sha1).toBase64());
    }else{end=qint64(turn["expiresAt"].toDouble());username=turn["username"].toString();password=turn["credential"].toString();}
    result.append(QJsonObject{{"urls",turn["urls"]},{"username",username},{"credential",password},{"expiresAt",double(end)}});return result;
}
QString validateNetworkServers(const QJsonArray& servers,qint64 now) {
    if(servers.size()>8 || QJsonDocument(servers).toJson(QJsonDocument::Compact).size()>16384)return "接続先の情報が大きすぎます";
    int count=0;
    for(const auto& entry:servers){
        if(!entry.isObject())return "接続先の情報が不正です";
        const auto o=entry.toObject();for(auto it=o.begin();it!=o.end();++it)if(it.key()!="urls"&&it.key()!="username"&&it.key()!="credential"&&it.key()!="expiresAt")return "対応していない接続先情報が含まれています";if(o.contains("secret")||o.contains("apiKey")||o.contains("privateKey"))return "共有できない秘密情報が含まれています";
        const auto urls=o["urls"].isString()?QJsonArray{o["urls"]}:o["urls"].toArray();if(urls.isEmpty()||urls.size()>8)return "接続先のURLが不正です";
        for(const auto& u:urls){if(++count>16)return "接続先が多すぎます";const bool turn=u.toString().startsWith("turn:")||u.toString().startsWith("turns:");if(!validUrl(u,turn))return "接続先のURLが不正です";
            if(turn){qint64 end=0;if(!boundedText(o["username"],256)||!boundedText(o["credential"],1024)||!expiry(o["expiresAt"],now,&end))return "中継資格情報が不正、または期限切れです";}
            else if(o.contains("credential")||o.contains("username"))return "探索先に資格情報は指定できません";
        }
    }
    return {};
}
}
