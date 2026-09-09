#pragma once
#include <QJsonArray>
#include <QJsonObject>
#include <QStringList>
#include <QUrl>
#include <QUrlQuery>
namespace junction {
// Native-only credentials. These URLs must never enter UI snapshots or logs.
inline QStringList iceServerUrls(const QJsonArray& servers){
    QStringList result;
    for(const auto& server:servers){const auto object=server.toObject();const auto urls=object["urls"].isString()?QJsonArray{object["urls"]}:object["urls"].toArray();
        for(const auto& value:urls){if(result.size()>=16)break;const auto text=value.toString();const auto colon=text.indexOf(':');if(colon<0)continue;
            const auto scheme=text.left(colon).toLower();if(scheme!="turn"&&scheme!="turns"&&scheme!="stun")continue;
            auto address=text.mid(colon+1);if(address.startsWith("//"))address=address.mid(2);
            if(address.isEmpty()||address.contains('@')||address.contains('#'))continue;
            const auto question=address.indexOf('?');const auto endpoint=question<0?address:address.left(question);
            QUrlQuery query(question<0?QString{}:address.mid(question+1));
            if(scheme=="turns"){
                // libdatachannel's transport=tcp overrides the turns scheme.
                // Preserve TLS explicitly when normalizing standard TURN URLs.
                query.removeAllQueryItems("transport");query.addQueryItem("transport","tls");address=endpoint+"?"+query.toString(QUrl::FullyEncoded);
            }else if(scheme=="turn"&&(query.queryItemValue("transport").isEmpty()||query.queryItemValue("transport")=="udp"))result.append("stun:"+endpoint);
            if(scheme!="stun")address=QString::fromLatin1(QUrl::toPercentEncoding(object["username"].toString()))+":"+QString::fromLatin1(QUrl::toPercentEncoding(object["credential"].toString()))+"@"+address;
            result.append(scheme+":"+address);
        }
    }
    result.removeDuplicates();return result;
}
}
