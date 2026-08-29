# MCP中心アーキテクチャ

更新日: 2026-08-29

## 責務の境界

DjalyはLLMを内蔵せず、モデル名・プロバイダー・APIキーも保持しない。自然言語の解釈や分類判断には、Djaly MCPを接続したクライアント自身のLLMを使う。

Djaly側に残す処理:

- Essentia / MusiCNNによるローカル音響解析
- 楽曲・歌詞・セットリスト・ジャンル情報の読み書き
- 構造化された検索条件の検証と決定的な検索
- 音響ベクトル、BPM、Key等による決定的な類似度計算
- MCPクライアントが返したジャンル分類結果の検証・適用
- ジャンル表記揺れの決定的な検出・統一

MCPクライアント側で行う処理:

- 自然言語の検索条件をBPM、年代、Energy等へ変換
- ジャンル・サブジャンルの判定
- セットリストの方向性を構造化条件へ変換
- 歌詞からワードプレイ候補の語句を選定

## MCPワークフロー

### ジャンル分類

1. `get_genre_analysis_context` で未分類曲、既存語彙、分類ルール、Essentia特徴量を取得する。
2. MCPクライアント自身のLLMで分類する。
3. `apply_genre_analysis` または `apply_genre_analyses` で構造化結果を適用する。

### 自然言語検索

1. MCPクライアントがユーザーの表現をBPM範囲、年代、Energy等へ解釈する。
2. `search_tracks` に構造化パラメータを渡す。

### セットリスト

1. MCPクライアントが方向性を `genres` / `subgenres` / `target_*` へ解釈する。
2. `recommend_next_track` または `generate_auto_setlist` を呼ぶ。
3. 必要ならセットリスト作成・編集ツールで結果を保存する。

### 歌詞ワードプレイ

1. `get_track_lyrics` で歌詞を取得する。
2. MCPクライアント自身のLLMで検索語句を選ぶ。
3. `find_wordplay_links` にその語句を渡し、他曲の一致箇所を検索する。

## UIと設定

- SettingsはLLM設定を持たず、AI RuntimeがMCPクライアント側であることだけを表示する。
- 旧LLM設定キーはAPIから参照・更新できず、アプリ起動時にDBから削除される。
- Music LibraryとSetlist CreatorのネイティブUIは、明示的な特徴量や決定的アルゴリズムだけを使う。
- Genre ManagerはMCP分類手順と決定的な類似候補・表記整理を提供する。
- Wordplay UIは手入力した語句による検索を提供し、自動LLM抽出は行わない。

## 現在の確認項目

- MCPツールは34件。
- File ExplorerのEssentia / MusiCNN解析経路は維持。
- Djalyバックエンドから外部LLMを呼ぶコードとLLM SDK依存は削除。
- REST APIから自然言語解析・LLM解析エンドポイントは削除。
- MCPのジャンル分類、構造化検索、セットリスト、ワードプレイ契約を自動テストする。
