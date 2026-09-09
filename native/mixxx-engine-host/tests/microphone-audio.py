"""Opt-in real CoreAudio microphone/ducking regression.

Requires numpy and sounddevice. Set DJALY_TEST_MIC_DEVICE and
DJALY_MIXXX_OUTPUT_DEVICE to TWO DISTINCT VIRTUAL audio devices. The test writes
generated tones to the mic device, records the master mix, and measures both
sources. It never chooses or captures a hardware microphone implicitly.
"""
import json
import os
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import time
import wave

import numpy as np
import sounddevice as sd

mic_device = os.environ["DJALY_TEST_MIC_DEVICE"]
output_device = os.environ["DJALY_MIXXX_OUTPUT_DEVICE"]
assert mic_device != output_device, "Separate virtual input and output required"
root = Path(__file__).resolve().parent.parent
binary = os.environ.get("DJALY_TEST_HOST", str(root / "build-upstream/djaly-mixxx-engine-host"))
directory = Path(tempfile.mkdtemp(prefix="djaly-microphone-"))
rate = 44100
frames = np.arange(rate * 60)
music = (np.sin(2 * np.pi * 223 * frames / rate) * 0.12 * 32767).astype("<i2")
fixture = directory / "music.wav"
with wave.open(str(fixture), "wb") as wav:
    wav.setparams((2, 2, rate, 0, "NONE", "not compressed"))
    wav.writeframes(np.column_stack((music, music)).tobytes())
stderr = open(directory / "host.log", "w")
child = subprocess.Popen([binary], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=stderr, text=True,
                         env={**os.environ, "DJALY_MIXXX_RECORDING_DIR": str(directory)})
replies = queue.Queue()
events = []


def read_replies():
    for line in child.stdout:
        value = json.loads(line)
        if value["kind"] == "event":
            events.append(value)
        else:
            replies.put(value)


threading.Thread(target=read_replies, daemon=True).start()
hello = None
next_id = 0


def command(op, params=None, expect_error=False):
    global next_id
    next_id += 1
    request = {"id": next_id, "op": op, "params": params or {}}
    if hello:
        request.update(engineId=hello["engineId"], sessionId=hello["sessionId"])
    child.stdin.write(json.dumps(request) + "\n")
    child.stdin.flush()
    value = replies.get(timeout=15)
    assert value["id"] == next_id, value
    assert (value["kind"] == "error") == expect_error, value
    return value.get("data", value)


def until(predicate):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = command("state.snapshot")
        if predicate(state):
            return state
        time.sleep(0.05)
    raise AssertionError("State timeout; see " + str(directory / "host.log"))


def config(**values):
    return command("audio.config.set", {"microphone": values})["microphone"]


def stop_and_verify():
    stopping = command("recording.stop")
    assert stopping["active"] and stopping["stopping"], stopping
    state = until(lambda s: not s["recording"]["active"] and not s["recording"]["stopping"])
    # Completion must mean immediately readable PCM, with no flushing delay.
    with wave.open(state["recording"]["path"], "rb") as wav:
        assert wav.getnchannels() == 2 and wav.getnframes() > rate


source_position = 0
source_active = True


def source(outdata, frame_count, _time, _status):
    global source_position
    positions = np.arange(source_position, source_position + frame_count)
    source_position += frame_count
    for channel, frequency in enumerate((997, 1777)):
        outdata[:, channel] = np.sin(2 * np.pi * frequency * positions / rate) * (0.24 if source_active else 0)


segments = []
try:
    hello = command("session.hello")
    state = until(lambda s: s["audio"]["applied"])
    assert "audio.microphone.ducking" in state["engine"]["capabilities"]
    assert state["audio"]["microphone"]["deviceId"] is None
    devices = command("audio.devices.list")["devices"]
    mic_id = next(d["id"] for d in devices if d["inputChannels"] >= 2 and d["displayName"] == mic_device)
    # Reject malformed settings before changing any current state.
    for invalid in ({"gain": -1}, {"channel": 0.5}, {"duckingStrength": 2}, {"enabled": "yes"}, {"unknown": 1}, {"enabled": True}):
        command("audio.config.set", {"microphone": invalid}, expect_error=True)
    selected = config(deviceId=mic_id, channel=0, enabled=False, gain=1)
    assert selected["applied"] and not selected["enabled"]
    command("audio.config.set", {"microphone": {"deviceId": "nonexistent-input"}}, expect_error=True)
    command("audio.config.set", {"microphone": {"channel": 255}}, expect_error=True)
    assert command("audio.config.get")["microphone"]["deviceId"] == mic_device
    command("deck.load", {"deck": "A", "track": {"trackId": "mic-test", "path": str(fixture), "durationMs": 60000}})
    until(lambda s: s["decks"]["A"]["status"] in ("ready", "paused"))
    command("deck.play", {"deck": "A"})
    with sd.OutputStream(device=mic_device, samplerate=rate, channels=2, dtype="float32", callback=source):
        command("recording.start")
        state = until(lambda s: s["recording"]["active"])
        config(deviceId=mic_device)  # Same route by display name does not reopen.
        recording = Path(state["recording"]["path"])
        record_start = time.monotonic()

        def segment(name):
            start = time.monotonic() - record_start
            time.sleep(3.0)
            segments.append((name, start + 1.8, start + 2.8))

        segment("muted")
        config(enabled=True)
        segment("mixed")
        config(duckingEnabled=True, duckingStrength=0.75)
        segment("ducked")
        command("audio.config.set", {"microphone": {"deviceId": None}}, expect_error=True)
        command("audio.config.set", {"microphone": {"channel": 1}}, expect_error=True)
        assert command("state.snapshot")["recording"]["active"]
        source_active = False
        segment("silence_restores_music")
        source_active = True
        config(enabled=False)
        segment("mute_restores_music")
        config(enabled=True, duckingEnabled=False, gain=0)
        segment("zero_gain")
        config(gain=0.5)
        segment("half_gain")
        stop_and_verify()
        time.sleep(1.3)  # Filename uniqueness cooldown only, after verifying WAV.
        before = command("state.snapshot")["decks"]["A"]["positionMs"]
        config(channel=1, gain=1)
        assert command("state.snapshot")["decks"]["A"]["positionMs"] >= before
        command("recording.start")
        channel_recording = Path(until(lambda s: s["recording"]["active"])["recording"]["path"])
        time.sleep(2)
        stop_and_verify()
        config(deviceId=None)
        assert not command("audio.config.get")["microphone"]["applied"]
    assert any(e.get("event") == "audio.config" for e in events)

    def amplitudes(file, start, end):
        with wave.open(str(file), "rb") as wav:
            assert wav.getsampwidth() == 2 and wav.getnchannels() == 2
            sr = wav.getframerate()
            samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").reshape(-1, 2)[:, 0] / 32768
        samples = samples[int(start * sr):int(end * sr)]
        assert len(samples) > sr * 0.8
        window = np.hanning(len(samples))
        spectrum = abs(np.fft.rfft(samples * window)) ** 2
        frequencies = np.fft.rfftfreq(len(samples), 1 / sr)
        # Independent devices have independent clocks: Mixxx resamples their
        # input to follow the master clock. Measure a narrow band around each
        # source instead of incorrectly requiring exactly the nominal frequency.
        return {str(hz): float(np.sqrt(4 * spectrum[abs(frequencies - hz) < 15].sum() / (len(samples) * (window ** 2).sum()))) for hz in (223, 997, 1777)}

    values = {name: amplitudes(recording, start, end) for name, start, end in segments}
    values["channel_1"] = amplitudes(channel_recording, 0.7, 1.7)
    baseline = values["muted"]["223"]
    mic = values["mixed"]["997"]
    assert baseline > 0.01 and mic > 0.04, values
    assert 0.18 < values["ducked"]["223"] / baseline < 0.34, values
    assert 0.85 < values["ducked"]["997"] / mic < 1.15, values
    for name in ("muted", "silence_restores_music", "mute_restores_music", "zero_gain"):
        assert 0.85 < values[name]["223"] / baseline < 1.15, (name, values)
        assert values[name]["997"] < mic * 0.03, (name, values)
    assert 0.42 < values["half_gain"]["997"] / mic < 0.58, values
    assert values["channel_1"]["1777"] > mic * 0.8, values
    assert values["channel_1"]["997"] < mic * 0.03, values
    report = {"passed": True, "directory": str(directory), "measurements": values}
    (directory / "result.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
finally:
    child.stdin.close()
    try:
        child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        child.kill()
    stderr.close()
