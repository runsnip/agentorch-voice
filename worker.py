"""AgentOrch's voice engine: the resident reader. Run by the bundle's own Python (python/), never the app's.

The bundle holds no model: each language is a pack downloaded on its own, into <home>/packs/<lang>, when the user
turns that language on. One engine per language, loaded the first time a line in it comes:

  vi   VieNeu-TTS v3 Turbo (Apache-2.0): Vietnamese, 25 preset voices; it also reads English with a Vietnamese voice
  en   Kokoro-82M (Apache-2.0) through kokoro-onnx (MIT), phonemes by espeak-ng (GPL-3.0, its own library): native
       American and British voices

  worker.py serve <home>              requests on stdin, one JSON line each: {"text", "lang", "voice", "file"};
                                      writes <home>/lines/<file>, answers {"file", "ok", "seconds"}; first it answers
                                      {"voices": {"<lang>": [{"name", "gender"}]}} for the packs that are installed
  worker.py fetch <home> <lang>       downloads that language's pack (model files) and reads one line to check it;
                                      prints {"progress": done, "total": n} lines, then {"ok": true} or {"error": "..."}
"""
import hashlib
import json
import os
import shutil
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))


def say(msg: dict) -> None:
    print(json.dumps(msg, ensure_ascii=False), flush=True)


# ---------------------------------------------------------------- the engines

class Vietnamese:
    def __init__(self, home: Path):
        os.environ["HF_HOME"] = str(home / "packs" / "vi" / "hf")
        from vieneu import Vieneu
        self.tts = Vieneu(backend="onnx")
        self.voices = []
        for label, name in self.tts.list_preset_voices():   # "⭐ Trúc Ly — Nữ · Bắc · …"
            parts = label.split("—", 1)
            self.voices.append({"name": name, "gender": "f" if len(parts) > 1 and parts[1].strip().startswith("Nữ") else "m"})

    def read(self, text: str, voice: str, path: str) -> None:
        known = {v["name"] for v in self.voices}
        audio = self.tts.infer(text, voice=voice) if voice in known else self.tts.infer(text)
        self.tts.save(audio, path)


class English:
    def __init__(self, home: Path):
        pack = home / "packs" / "en"
        # espeak-ng refuses data paths longer than about 160 characters: keep its data at a short one
        data = Path(os.environ.get("TMPDIR", "/tmp")).resolve() / "agentorch-espeak" / "espeak-ng-data"
        if len(str(data)) > 150:
            data = Path("/tmp/agentorch-espeak/espeak-ng-data")
        if not (data / "phontab").exists():
            import espeakng_loader
            shutil.rmtree(data.parent, ignore_errors=True)
            shutil.copytree(espeakng_loader.get_data_path(), data)
        from kokoro_onnx import EspeakConfig, Kokoro
        files = MANIFEST["locales"]["en"]["files"]
        self.tts = Kokoro(str(pack / files[0]["name"]), str(pack / files[1]["name"]), espeak_config=EspeakConfig(data_path=str(data)))
        # af_/am_ American, bf_/bm_ British; the second letter is the gender
        self.voices = [{"name": v, "gender": "f" if v[1] == "f" else "m"} for v in self.tts.get_voices() if v[:2] in ("af", "am", "bf", "bm")]

    def read(self, text: str, voice: str, path: str) -> None:
        voice = voice if any(v["name"] == voice for v in self.voices) else "af_heart"
        samples, rate = self.tts.create(text, voice=voice, speed=1.0, lang="en-gb" if voice[0] == "b" else "en-us")
        import soundfile
        soundfile.write(path, samples, rate)


ENGINES = {"vi": Vietnamese, "en": English}


def installed(home: Path, lang: str) -> bool:
    return (home / "packs" / lang / ".ready").exists()


# ---------------------------------------------------------------- fetching a language's pack

def fetch(home: Path, lang: str) -> int:
    pack = home / "packs" / lang
    pack.mkdir(parents=True, exist_ok=True)
    (pack / ".ready").unlink(missing_ok=True)
    spec = MANIFEST["locales"][lang]
    try:
        if lang == "vi":   # the engine fetches exactly the files it reads from Hugging Face, the model's own home
            say({"progress": 0, "total": 0})
        else:              # files from a release, each checked against its sha256
            total = sum(f["bytes"] for f in spec["files"])
            done = 0
            for f in spec["files"]:
                target = pack / f["name"]
                if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == f["sha256"]:
                    done += f["bytes"]
                    continue
                part, digest = target.with_suffix(".part"), hashlib.sha256()
                with urllib.request.urlopen(f["url"], timeout=60) as res, part.open("wb") as out:
                    while chunk := res.read(1 << 20):
                        out.write(chunk)
                        digest.update(chunk)
                        done += len(chunk)
                        say({"progress": done, "total": total})
                if digest.hexdigest() != f["sha256"]:
                    part.unlink(missing_ok=True)
                    raise ValueError(f"{f['name']}: wrong checksum")
                part.replace(target)
        engine = ENGINES[lang](home)
        (home / "lines").mkdir(exist_ok=True)
        engine.read(spec["check"], engine.voices[0]["name"], str(home / "lines" / f"check-{lang}.wav"))
        (pack / ".ready").write_text(MANIFEST["version"])
        say({"ok": True})
        return 0
    except Exception as e:
        say({"error": f"{type(e).__name__}: {e}"[:300]})
        return 1


# ---------------------------------------------------------------- serving

def serve(home: Path) -> int:
    lines = home / "lines"
    lines.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HUB_OFFLINE"] = "1"   # the packs are installed: reading never goes online
    engines = {}

    def engine(lang):
        if lang not in engines and installed(home, lang):
            engines[lang] = ENGINES[lang](home)
        return engines.get(lang)

    # the voices of every installed pack (this loads them, so the first line is quick)
    say({"voices": {lang: engine(lang).voices for lang in ENGINES if engine(lang)}})
    for raw in sys.stdin:
        req = {}
        try:
            req = json.loads(raw)
            name = os.path.basename(req["file"])
            eng = engine(req.get("lang") or "vi")
            if not eng:
                raise RuntimeError(f"no voice pack installed for {req.get('lang')}")
            path = str(lines / name)
            eng.read(req["text"], req.get("voice") or "", path + ".part.wav")
            os.replace(path + ".part.wav", path)
            import soundfile
            info = soundfile.info(path)
            say({"file": name, "ok": True, "seconds": round(info.frames / info.samplerate, 2)})
        except Exception as e:   # one bad line never stops the others
            say({"file": req.get("file", "") if isinstance(req, dict) else "", "ok": False, "error": str(e)[:200]})
    return 0


if __name__ == "__main__":
    cmd, home = sys.argv[1], Path(sys.argv[2])
    sys.exit(serve(home) if cmd == "serve" else fetch(home, sys.argv[3]))
