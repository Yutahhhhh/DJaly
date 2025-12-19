import os
import sys
import uvicorn
import multiprocessing
import platformdirs

# PyInstaller for multiprocessing support (Windows/macOS)
multiprocessing.freeze_support()

if __name__ == "__main__":
    # アプリケーションデータディレクトリの確保
    APP_NAME = "Djaly"
    APP_AUTHOR = "DjalyDev"
    user_data = platformdirs.user_data_dir(APP_NAME, APP_AUTHOR)
    os.makedirs(user_data, exist_ok=True)

    # Librosaなどのキャッシュディレクトリをユーザーデータ配下に強制設定
    # (書き込み権限のない場所へのアクセスを防ぐため)
    os.environ["NUMBA_CACHE_DIR"] = os.path.join(user_data, ".numba_cache")
    os.environ["MPLCONFIGDIR"] = os.path.join(user_data, ".matplotlib")
    
    # ログディレクトリの設定 (backend/utils/logger.py で使用)
    os.environ["DJALY_LOG_DIR"] = os.path.join(user_data, "logs")

    # PyInstallerでバンドルされた場合のパス解決（必要に応じて）
    if getattr(sys, 'frozen', False):
        base_dir = sys._MEIPASS
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    # mainモジュールからappオブジェクトを直接インポート
    # これによりPyInstaller環境下でも正しくアプリが見つかる
    from main import app

    print(f"Starting Djaly Backend Server on port 8001...")
    print(f"User Data Directory: {user_data}")

    # サーバー起動
    # reload=False は必須 (フリーズされたアプリではリロード不可)
    # workers=1 (DuckDBの並行性のためシングルワーカー推奨)
    # 文字列 "main:app" ではなく、appオブジェクトを直接渡す
    
    # ポート番号を環境変数から取得（デフォルトは開発用の8001）
    # 本番環境ではTauri側からランダムな空きポートなどが渡されることを想定、
    # または競合しにくい固定ポート（例: 48123）を使用する
    port = int(os.environ.get("DJALY_PORT", 8001))
    
    # 既存のプロセスをチェックして終了させる (macOS/Linux)
    # Windowsでは lsof がないためスキップ (必要なら psutil を使う)
    if sys.platform != "win32":
        try:
            import subprocess
            # 指定ポートを使用しているプロセスのPIDを取得
            result = subprocess.run(
                ["lsof", "-t", f"-i:{port}"], 
                capture_output=True, 
                text=True
            )
            pids = result.stdout.strip().split('\n')
            
            my_pid = str(os.getpid())
            
            for pid in pids:
                if pid and pid != my_pid:
                    print(f"Killing existing process on port {port} (PID: {pid})...")
                    subprocess.run(["kill", "-9", pid])
        except Exception as e:
            print(f"Warning: Failed to kill existing process: {e}")

    print(f"Starting Djaly Backend Server on port {port}...")
    uvicorn.run(app, host="127.0.0.1", port=port, reload=False, workers=1)