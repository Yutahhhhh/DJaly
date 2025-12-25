import os
import sys
import uvicorn
import multiprocessing
import platformdirs

# PyInstaller for multiprocessing support (Windows/macOS)
multiprocessing.freeze_support()

if __name__ == "__main__":
    # 設定の読み込みと環境変数のセットアップ
    # これを最初に行うことで、後続のインポート(librosa等)が正しいパスを使用できる
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
    from main import app

    # ポート番号を環境変数から取得（デフォルトは開発用の8001）
    # 本番環境ではTauri側からランダムな空きポートなどが渡されることを想定、
    # または競合しにくい固定ポート（例: 48123）を使用する
    port = int(os.environ.get("DJALY_PORT", settings.DJALY_PORT))

    print(f"Starting Djaly Backend Server on port {port}...")
    print(f"User Data Directory: {settings.USER_DATA_DIR}")
    
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