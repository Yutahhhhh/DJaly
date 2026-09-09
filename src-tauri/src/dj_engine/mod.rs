//! ネイティブ DJ エンジン（Phase 0）との橋渡し。
//!
//! 既存の `<audio>` プレビュー再生には一切触れない。別系統として並走する。
//! 開発時は実Mixxx hostを優先し、未ビルドなら `native/dj-engine-host` の
//! 無音シミュレータへフォールバックする。状態は必ず `simulated` で識別する。
//! ワイヤ型はフロントエンドとRustホストの実装・契約テストで共有する。

pub mod commands;
pub mod supervisor;

pub use supervisor::EngineSupervisor;

pub mod midi;
pub mod jog_display;

pub mod performance_transport;
