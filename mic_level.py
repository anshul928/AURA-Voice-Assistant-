import sounddevice as sd
import numpy as np

print("Microphone test shuru! Ab bolo...")

with sd.InputStream(
    device=1,
    samplerate=44100,
    channels=1,
    dtype="float32"
) as stream:
    for i in range(10):
        audio, overflowed = stream.read(4410)
        level = float(np.max(np.abs(audio)))
        print("Audio level:", round(level, 4))

print("Test complete.")