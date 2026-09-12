import os
import sys
import multiprocessing
import threading

# Bound native pools before importing the audio stack; analysis jobs control concurrency.
for thread_setting in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
                       "TF_NUM_INTRAOP_THREADS", "TF_NUM_INTEROP_THREADS"):
    os.environ.setdefault(thread_setting, "1")

# PyInstaller for multiprocessing support (Windows/macOS)
multiprocessing.freeze_support()

# The desktop reads UTF-8 from redirected pipes. Windows' legacy ANSI code
# page cannot encode Japanese profile/music paths in startup messages.
for stream in (sys.stdout, sys.stderr):
    if stream is not None and hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

if __name__ == "__main__":
    import uvicorn
    if sys.argv[1:] == ["--diagnose-light-analysis"]:
        from light_analysis_diagnostic import run
        run()
        raise SystemExit(0)

    if sys.argv[1:] == ["--diagnose-analysis"]:
        from analysis_diagnostic import run
        run()
        raise SystemExit(0)

    # 設定の読み込みと環境変数のセットアップ
    # これを最初に行うことで、後続のインポート(librosa等)が正しいパスを使用できる
    from startup_progress import report as startup_report
    startup_report("settings", "設定・保存先を読み込んでいます", 1)
    from config import settings
    settings.setup_environment()

    # アプリケーションデータディレクトリの確保
    os.makedirs(settings.USER_DATA_DIR, exist_ok=True)

    # PyInstallerでバンドルされた場合のパス解決（必要に応じて）
    if getattr(sys, 'frozen', False):
        base_dir = sys._MEIPASS
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    # mainモジュールからappオブジェクトを直接インポート
    # これによりPyInstaller環境下でも正しくアプリが見つかる
    startup_report("services", "ライブラリ・解析・再生の機能を読み込んでいます", 2)
    from main import app

    # ポート番号を環境変数から取得（デフォルトは開発用の8001）
    # 本番環境ではTauri側からランダムな空きポートなどが渡されることを想定、
    # または競合しにくい固定ポート（例: 48123）を使用する
    port = int(os.environ.get("PLUMDECK_PORT", settings.PLUMDECK_PORT))

    print(f"Starting plumdeck Backend Server on port {port}...")
    print(f"User Data Directory: {settings.USER_DATA_DIR}")
    
    # Never terminate another process to claim a port. Uvicorn reports conflicts.
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
        reload=False, workers=1, timeout_graceful_shutdown=5))
    if os.environ.get("PLUMDECK_MANAGED_SIDECAR") == "1":
        def watch_parent():
            # The desktop owns this pipe. EOF also handles a crashed desktop;
            # standalone CLI launches keep their usual signal-based lifecycle.
            try:
                for line in iter(lambda: sys.stdin.buffer.readline(1024), b""):
                    if line.strip() == b"plumdeck:shutdown":
                        break
            finally:
                server.should_exit = True
        threading.Thread(target=watch_parent, daemon=True, name="desktop-lifecycle").start()
    server.run()
