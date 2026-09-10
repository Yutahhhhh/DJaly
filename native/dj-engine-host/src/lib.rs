//! plumdeck ネイティブ DJ エンジンホスト（Phase 0）。
//!
//! このクレートは **音を出さないシミュレータ** である。
//! 目的は、将来 Mixxx 由来の C++ ホストが実装することになる
//! コマンド／状態通知の境界を、実機なしで先に固定して検証すること。
//!
//! - [`protocol`] — ワイヤ形式（NDJSON）の型定義。
//! - [`engine`] — 権威状態機械。I/O を持たず、時刻は外から与える。
//! - [`runtime`] — 行単位のディスパッチとエラー整形。

pub mod engine;
pub mod protocol;
pub mod runtime;

pub use engine::{Engine, EngineConfig};
pub use protocol::{DeckId, Outgoing, PROTOCOL_VERSION};
pub use runtime::Runtime;
