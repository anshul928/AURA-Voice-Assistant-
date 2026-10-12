
import sounddevice as sd
import numpy as np
from scipy.signal import resample_poly
from openwakeword.model import Model

model = Model(
    wakeword_models=["hey_jarvis"],
    inference_framework="onnx"
)

print("Listening! Say Hey Jarvis clearly. AURA wake word abhi setup nahi hua hai.")
print("Stop with Ctrl+C.")

with sd.InputStream(
    device=1,
    samplerate=44100,
    channels=1,
    dtype="float32",
    blocksize=4410
) as stream:
   while True:
    audio, _ = stream.read(4410)
    audio_16k = resample_poly(audio[:, 0], 160, 441)
    audio_int16 = np.clip(
        audio_16k * 32768, -32768, 32767
    ).astype(np.int16)

    for start in range(0, len(audio_int16) - 1279, 1280):
        chunk = audio_int16[start:start + 1280]
        scores = model.predict(chunk)
        score = float(scores["hey_jarvis"])

        if score > 0.5:
            print(f"\nWAKE WORD DETECTED! Score: {score:.4f}\n")
        else:
            print(f"Score: {score:.4f}")