
import sounddevice as sd
import speech_recognition as sr
import numpy as np

print("AURA: Bolna shuru karo...")

duration = 5
sample_rate = 16000

audio = sd.rec(
    int(duration * sample_rate),
    samplerate=sample_rate,
    channels=1,
    dtype="int16",
    device=1
)
sd.wait()

recognizer = sr.Recognizer()
audio_data = sr.AudioData(audio.tobytes(), sample_rate, 2)

try:
    text = recognizer.recognize_google(audio_data, language="en-IN")
    print("AURA ne suna:", text)
except sr.UnknownValueError:
    print("AURA: Voice samajh nahi aayi. Dobara try karo.")
except sr.RequestError as e:
    print("Internet ya speech service error:", e)
