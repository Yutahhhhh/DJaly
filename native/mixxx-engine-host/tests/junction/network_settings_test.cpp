#include "harness.h"
#include "junction/network_settings.h"
#include <QDateTime>
#include <QJsonDocument>
using namespace junction;
namespace {
QJsonObject restSettings(){return {{"stunUrls",QJsonArray{}},{"save",false},{"turn",QJsonObject{{"mode","rest"},{"urls",QJsonArray{"turns:relay.example.test:5349?transport=tcp"}},{"secret","0123456789abcdef0123456789abcdef"}}}};}
}
JTEST("network-settings","REST credentials expire and isolate peer labels without exporting the administrator secret"){
 NetworkSettings settings(false);CHECK(settings.configure(restSettings()).isEmpty());QString error;
 const auto first=settings.credentials("session-test","peer-one",1800000000000LL,&error);CHECK(error.isEmpty());CHECK_EQ(first.size(),1);
 const auto row=first[0].toObject();CHECK_EQ(row["username"].toString(),QString("1800001800:plumdeck-220fc30d5e853fbac87d6f64"));CHECK_EQ(row["credential"].toString(),QString("TOSwc1tzNIJTljYuWL9+F2lEEEg="));CHECK_EQ(row["expiresAt"].toDouble(),1800001800000.0);
 const auto other=settings.credentials("session-test","peer-two",1800000000000LL);CHECK(row["username"]!=other[0].toObject()["username"]);CHECK(row["credential"]!=other[0].toObject()["credential"]);
 CHECK(!QJsonDocument(first).toJson().contains("0123456789abcdef0123456789abcdef"));CHECK(!QJsonDocument(settings.summary()).toJson().contains("secret"));
 CHECK(validateNetworkServers(first,1800000000000LL).isEmpty());CHECK(!validateNetworkServers(first,1800001800000LL).isEmpty());
}
JTEST("network-settings","invalid configuration cannot replace the previous working configuration"){
 NetworkSettings settings(false);CHECK(settings.configure(restSettings()).isEmpty());const auto previous=QJsonDocument(settings.summary()).toJson();
 for(const auto& url: {"https://relay.example.test", "turn:user:password@relay.example.test", "turn:relay.example.test/path", "turn:relay.example.test?transport=invalid"}){
  auto input=restSettings();auto turn=input["turn"].toObject();turn["urls"]=QJsonArray{url};input["turn"]=turn;CHECK(!settings.configure(input).isEmpty());CHECK_EQ(QJsonDocument(settings.summary()).toJson().toStdString(),previous.toStdString());
 }
 auto input=restSettings();auto turn=input["turn"].toObject();turn["apiKey"]="never-export";input["turn"]=turn;CHECK(!settings.configure(input).isEmpty());
 CHECK(settings.clear().isEmpty());CHECK(!settings.summary()["turn"].toObject()["configured"].toBool());
}
JTEST("network-settings","temporary credentials cannot outlive their issued username or be silently renewed"){
 NetworkSettings settings(false);const auto now=QDateTime::currentMSecsSinceEpoch(),end=(now/1000+600)*1000;
 const auto username=QString::number(end/1000)+":issued-user";
 QJsonObject turn{{"mode","temporary"},{"urls",QJsonArray{"turn:relay.example.test:3478"}},{"username",username},{"credential","temporary-test-password"},{"expiresAt",double(end)}};
 CHECK(settings.configure({{"stunUrls",QJsonArray{}},{"turn",turn},{"save",false}}).isEmpty());QString error;
 CHECK_EQ(settings.credentials("s","p",now,&error).size(),1);CHECK(error.isEmpty());CHECK(settings.credentials("s","p",end,&error).isEmpty());CHECK(!error.isEmpty());
 turn["expiresAt"]=double(end+600000);CHECK(!settings.configure({{"turn",turn}}).isEmpty());
 turn["username"]="static-user";turn["expiresAt"]=double(end);CHECK(!settings.configure({{"turn",turn}}).isEmpty());
}
JTEST("network-settings","received network settings are bounded and reject administrative or unexpiring secrets"){
 const qint64 now=1800000000000LL;
 CHECK(validateNetworkServers({QJsonObject{{"urls",QJsonArray{"stun:stun.l.google.com:19302"}}}},now).isEmpty());
 CHECK(!validateNetworkServers({QJsonObject{{"urls",QJsonArray{"turn:host:3478"}},{"username","user"},{"credential","pass"}}},now).isEmpty());
 CHECK(!validateNetworkServers({QJsonObject{{"urls",QJsonArray{"stun:host"}},{"secret","not-shared"}}},now).isEmpty());
 CHECK(!validateNetworkServers({QJsonObject{{"urls",QJsonArray{"stun:host"}},{"nested",QJsonObject{{"apiKey","not-shared"}}}}},now).isEmpty());
}
