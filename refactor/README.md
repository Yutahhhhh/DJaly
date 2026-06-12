# Djaly 改修計画資料

2026-06-12 時点の `main`（v0.2.2 相当）のコードベースを精査して作成した改修資料。Codex 等のコーディングエージェントにそのまま渡せるよう、各項目に**対象ファイル・行番号・現状コード・改修後コード・検証方法**を記載している。

## 実装状況 (2026-06-12 実装完了)

全フェーズ実装済み。`pytest` 109 件パス (新規テスト `backend/tests/test_refactor_fixes.py` 12 件含む)、`tsc --noEmit` / `vite build` 成功。

| 区分 | 状態 |
|---|---|
| BUG-01〜17 | ✅ 実装済み |
| BUG-18 / BUG-19 (実装中に発見・01 ドキュメント末尾) | ✅ 実装済み |
| AI-01〜12 | ✅ 実装済み (AI-11 の energy_curve プリセットのみ未実装 ※下記) |
| UX-01〜13 | ✅ 実装済み (UX-01 は sonner の代わりに自作軽量トースト `src/components/ui/toast.tsx` を採用 ※下記) |

**意図的に仕様変更した点**:
- **UX-01**: pnpm のバージョン不整合 (packageManager=7.33.7 / store v10) で依存追加が安全にできないため、`sonner` ではなく外部依存ゼロの自作トースト (`src/components/ui/toast.tsx`) を実装。API は `toast.success/error/info` で sonner 互換に近い。pnpm 環境を直したら sonner への差し替えも容易。
- **AI-11(2)**: `energy_curve` プリセット項目はプリセットスキーマ変更を伴うため未実装 (将来課題)。多特徴量 vibe スコアと同一アーティスト連続ペナルティは実装済み。
- **AI-10(3)**: プロバイダー別モデル保存はフロント既存実装 (`{provider}_model` キー) が既に対応していたため、バックエンド側の変更は不要と判断。
- **UX-02**: vibe 解釈結果の表示は read-only バッジとして実装 (`POST /api/vibe/resolve` + Music Library のバッジ)。バッジクリックでのスライダー編集は未実装 (FilterDialog で手動調整可能なため優先度低)。

## ドキュメント構成

| ファイル | 内容 | 項目数 |
|---|---|---|
| [01-bug-fixes.md](./01-bug-fixes.md) | 潜在バグの改修（再現コード箇所と修正案） | BUG-01〜17 |
| [02-ai-accuracy.md](./02-ai-accuracy.md) | AI 返答精度・LLM 連携の改善 | AI-01〜12 |
| [03-usability.md](./03-usability.md) | ユーザビリティ改善 | UX-01〜13 |

## 全体実装ロードマップ（推奨順）

ドキュメント間で依存関係があるため、以下の順で進めると手戻りが少ない。

### フェーズ 1: 壊れている機能の修復（小さく確実な PR 向き）
1. **BUG-02** ワードプレイ削除 422（1行修正）
2. **BUG-01** similarity 誤表示（1行修正）
3. **BUG-03** subgenres フィルタ無視
4. **BUG-12** Bridge END 欠落
5. **BUG-06** メタデータ skip cache 誤登録

### フェーズ 2: LLM 基盤の堅牢化（精度問題の土台）
6. **AI-01 + AI-02** JSON 構造化出力 + temperature 引数化
7. **BUG-04** vibe パラメータの Pydantic 検証 + SQL プレースホルダ化
8. **AI-07 + BUG-07** vibe キャッシュ / resolve API 分離
9. **AI-09 + AI-10** リトライ・デフォルトモデル更新

### フェーズ 3: フロントの信頼性
10. **UX-01 + BUG-14** トースト基盤 + ApiError（多数の項目の前提）
11. **BUG-08 + UX-10** 検索レース対策とデバウンス最適化
12. **BUG-11 + UX-05** セットリスト保存の直列化と保存状態表示
13. **BUG-13 + UX-04** 解析完了フィードバック

### フェーズ 4: AI 精度の本丸
14. **AI-03 + AI-04 + BUG-10** ジャンル語彙注入・コンテキスト拡充・verified 条件修正
15. **AI-05** バックグラウンド解析のチャンクバッチ化
16. **AI-08 + UX-07** ワードプレイキーワードの永続キャッシュ

### フェーズ 5: 磨き込み
17. **UX-02** vibe 解釈結果の可視化
18. **UX-03 / UX-06 / UX-08** カウント表示・AutoTab 説明・解析ログ
19. **AI-11 / AI-12** セットリスト生成アルゴリズム強化
20. 残りの Low 項目（BUG-05/09/15/16/17、UX-09/11/12/13）

## 実装時の注意事項（Codex 向け）

- **テスト**: バックエンドは `pnpm test:backend`（= `backend/.venv/bin/pytest`）。LLM 呼び出しは `generate_text` をモックする方針が既存テスト（`backend/tests/test_genres.py` 等）に揃う。
- **DB マイグレーション**: スキーマ変更（AI-08 の `keywords_json` 等）は `backend/infra/database/schema.py` の Raw SQL マイグレーション機構に追記する。DuckDB なので `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` が使える。
- **依存追加**: Python 側は `backend/setup.sh` / requirements を確認して追記（`cachetools` 等）。フロントは `pnpm add sonner` のみ想定。
- **LLM プロバイダー**: openai / codex(CLI) / anthropic / google / ollama の5系統すべてに分岐があるため、`generate_text` のシグネチャ変更時は5分岐 + `check_llm_status` を漏れなく更新すること。
- **動作確認**: `pnpm tauri` で backend + Tauri が同時起動する。バックエンド単体は `pnpm backend:dev`（ポート 8001）。ログは `pnpm log:watch`。
- **コミット粒度**: フェーズ内の番号 1 項目 = 1 コミットを推奨。BUG-02 のような 1 行修正と AI-01 のような横断変更を混ぜない。
