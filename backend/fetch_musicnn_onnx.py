"""Fetch the build-time Windows MusiCNN model and verify its exact bytes."""
from argparse import ArgumentParser
from hashlib import sha256
from pathlib import Path
from time import sleep
from urllib.request import Request, urlopen


MODEL_URLS = (
    (
        "https://essentia.upf.edu/models/feature-extractors/musicnn/"
        "msd-musicnn-1.onnx"
    ),
    (
        "https://essentia.upf.edu/models/autotagging/msd/"
        "msd-musicnn-1.onnx"
    ),
)
MODEL_SHA256 = "49668ffec47e52e94b96f45930bb46a28a1368d4bdfb5c05378fa834aca616e1"
MODEL_PATH = Path(__file__).resolve().parent / "models" / "msd-musicnn-1.onnx"
DOWNLOAD_ATTEMPTS = 5
DOWNLOAD_TIMEOUT_SECONDS = 60
RETRY_DELAYS_SECONDS = (2, 5, 10, 20)


def digest(path: Path) -> str:
    checksum = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def download(url: str, destination: Path) -> None:
    request = Request(
        url,
        headers={"User-Agent": "plumdeck-build (+https://github.com/Yutahhhhh/plumdeck)"},
    )
    with urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response, destination.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)


def main(*, verify_only: bool = False) -> None:
    if MODEL_PATH.is_file() and digest(MODEL_PATH) == MODEL_SHA256:
        print(f"Verified cached MusiCNN ONNX model: {MODEL_PATH}")
        return

    if verify_only:
        actual = digest(MODEL_PATH) if MODEL_PATH.is_file() else "missing"
        raise RuntimeError(
            f"MusiCNN ONNX model verification failed: expected {MODEL_SHA256}, got {actual}"
        )

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = MODEL_PATH.with_suffix(".onnx.download")
    temporary.unlink(missing_ok=True)
    last_error: Exception | None = None

    for attempt in range(DOWNLOAD_ATTEMPTS):
        url = MODEL_URLS[attempt % len(MODEL_URLS)]
        try:
            temporary.unlink(missing_ok=True)
            print(
                f"Downloading MusiCNN ONNX model "
                f"(attempt {attempt + 1}/{DOWNLOAD_ATTEMPTS}): {url}"
            )
            download(url, temporary)
            actual = digest(temporary)
            if actual != MODEL_SHA256:
                raise RuntimeError(
                    f"MusiCNN ONNX checksum mismatch: expected {MODEL_SHA256}, got {actual}"
                )
            temporary.replace(MODEL_PATH)
            print(f"Downloaded and verified MusiCNN ONNX model: {MODEL_PATH}")
            return
        except (OSError, RuntimeError) as error:
            last_error = error
            print(f"MusiCNN model download attempt failed: {error}")
            if attempt < DOWNLOAD_ATTEMPTS - 1:
                sleep(RETRY_DELAYS_SECONDS[attempt])
        finally:
            temporary.unlink(missing_ok=True)

    raise RuntimeError(
        f"Could not download the verified MusiCNN ONNX model after "
        f"{DOWNLOAD_ATTEMPTS} attempts"
    ) from last_error


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="verify the existing model without making a network request",
    )
    arguments = parser.parse_args()
    main(verify_only=arguments.verify_only)
