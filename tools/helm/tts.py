"""Text to speech worker for Helm. One JSON line in per request on stdin
({"text": ..., "voice": ..., "speed": ...}); the WAV comes back on stdout as a
4-byte big-endian length followed by the bytes. Kokoro runs on this Mac and
nothing is sent anywhere. Started and stopped by bin/dashboard.py."""
import io
import json
import os
import struct
import sys

out = sys.stdout.buffer
sys.stdout = sys.stderr                    # a library's stray print must not corrupt the audio stream

import soundfile as sf
from kokoro_onnx import Kokoro

models = os.path.expanduser("~/.cache/quarterdeck/models")
kokoro = Kokoro(os.path.join(models, "kokoro-v1.0.onnx"), os.path.join(models, "voices-v1.0.bin"))
out.write(struct.pack(">I", 0)); out.flush()      # ready

for line in sys.stdin:
    req = json.loads(line)
    samples, rate = kokoro.create(req["text"], voice=req.get("voice") or "af_heart",
                                  speed=float(req.get("speed") or 1.0), lang="en-us")
    buf = io.BytesIO()
    sf.write(buf, samples, rate, format="WAV", subtype="PCM_16")
    data = buf.getvalue()
    out.write(struct.pack(">I", len(data)) + data); out.flush()
