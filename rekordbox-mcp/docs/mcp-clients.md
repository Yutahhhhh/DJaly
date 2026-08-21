# MCP クライアント設定

以下の例では、プロジェクトを `/Users/horiyuuta/Workspace/Djaly/rekordbox-mcp`
に置いている前提です。`cwd`／`args` のパスは各環境に合わせて変更してください。
クライアントからは stdio で接続するため、サーバーの標準出力にログを出さないでください。

## 起動モード

同じ設定で `args` の `--mode` だけを変更できます。

```text
readonly: uv run rekordbox-mcp --mode readonly
xml:      uv run rekordbox-mcp --mode xml
masterdb: uv run rekordbox-mcp --mode masterdb
```

DB を自動検出できない場合は、例えば次のように追加します。

```text
--database-path /path/to/master.db --db-dir /path/to/Pioneer
```

`masterdb` で書き込む前に Rekordbox を終了し、バックアップを作成してください。

## Claude Desktop

Claude Desktop の MCP 設定（通常は `claude_desktop_config.json`）に追加します。

```json
{
  "mcpServers": {
    "rekordbox-readonly": {
      "command": "uv",
      "args": ["run", "rekordbox-mcp", "--mode", "readonly"],
      "cwd": "/Users/horiyuuta/Workspace/Djaly/rekordbox-mcp"
    }
  }
}
```

XML または直接 DB 書込み用に接続する場合は、`args` を次のいずれかに置き換えます。

```json
"args": ["run", "rekordbox-mcp", "--mode", "xml"]
```

```json
"args": ["run", "rekordbox-mcp", "--mode", "masterdb"]
```

### 環境変数をクライアント側で渡す例

```json
{
  "mcpServers": {
    "rekordbox": {
      "command": "uv",
      "args": ["run", "rekordbox-mcp", "--mode", "readonly"],
      "cwd": "/Users/horiyuuta/Workspace/Djaly/rekordbox-mcp",
      "env": {
        "REKORDBOX_DB_PATH": "/path/to/master.db",
        "REKORDBOX_MODE": "readonly"
      }
    }
  }
}
```

## Claude Code

プロジェクト直下の `.mcp.json` に記載します。

```json
{
  "mcpServers": {
    "rekordbox": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "rekordbox-mcp", "--mode", "readonly"],
      "cwd": "/Users/horiyuuta/Workspace/Djaly/rekordbox-mcp"
    }
  }
}
```

XML／masterdb は `args` のモードを変更して起動します。書込みモードは必要な作業時
だけ有効にすることを推奨します。

## Cursor

Cursor の MCP 設定（Settings の MCP またはプロジェクトの `.cursor/mcp.json`）に
次の形式を追加します。

```json
{
  "mcpServers": {
    "rekordbox": {
      "command": "uv",
      "args": ["run", "rekordbox-mcp", "--mode", "readonly"],
      "cwd": "/Users/horiyuuta/Workspace/Djaly/rekordbox-mcp"
    }
  }
}
```

クライアントによって `cwd` の扱いが異なる場合は、`args` の先頭を絶対パスの
`uv` 実行環境に合わせるか、`command` を `sh`、`args` を
`["-lc", "cd /path/to/rekordbox-mcp && uv run rekordbox-mcp --mode readonly"]`
に変更してください。
