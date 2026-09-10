"""Fetch the build-time Windows MusiCNN model and verify its exact bytes."""
from hashlib import sha256
from pathlib import Path
from urllib.request import urlopen


MODEL_URL = (
    "https://essentia.upf.edu/models/feature-extractors/musicnn/"
    "msd-musicnn-1.onnx"
)
MODEL_SHA256 = "49668ffec47e52e94b96f45930bb46a28a1368d4bdfb5c05378fa834aca616e1"
MODEL_PATH = Path(__file__).resolve().parent / "models" / "msd-musicnn-1.onnx"


def digest(path: Path) -> str:
    checksum = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def main() -> None:
    if MODEL_PATH.is_file() and digest(MODEL_PATH) == MODEL_SHA256:
        print(f"Verified cached MusiCNN ONNX model: {MODEL_PATH}")
        return

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = MODEL_PATH.with_suffix(".onnx.download")
    temporary.unlink(missing_ok=True)
    try:
        with urlopen(MODEL_URL, timeout=120) as response, temporary.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        actual = digest(temporary)
        if actual != MODEL_SHA256:
            raise RuntimeError(
                f"MusiCNN ONNX checksum mismatch: expected {MODEL_SHA256}, got {actual}")
        temporary.replace(MODEL_PATH)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Downloaded and verified MusiCNN ONNX model: {MODEL_PATH}")


if __name__ == "__main__":
    main()
