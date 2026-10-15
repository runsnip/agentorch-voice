# AgentOrch voice

The optional text-to-speech engine of [AgentOrch](https://github.com/runsnip): the characters read their lines aloud.
It runs on the user's machine (CPU), as its own process; no text leaves the machine.

- **The bundle** (`voice-<target>.tar.gz`, about 124 MB) is a standalone Python 3.12 with the libraries and
  `worker.py`. No model is in it.
- **Language packs** are downloaded on their own when the user turns a language on in AgentOrch (Tab › Settings),
  after accepting their licences:
  - **Tiếng Việt** — VieNeu-TTS v3 Turbo (Apache-2.0), about 540 MB from Hugging Face; 25 preset voices.
  - **English** — Kokoro-82M (Apache-2.0) via kokoro-onnx (MIT), about 116 MB; 28 American and British voices.
- Only preset voices are used; no one's voice is cloned.

Build for this machine: `python tools/build.py` (needs uv). Release: push a tag `v<version>` matching
`manifest.json`; GitHub Actions builds macOS (arm64, x64), Linux (x64, arm64) and Windows (x64).

Licences: this repository is Apache-2.0. The bundle ships espeak-ng and phonemizer-fork (GPL-3.0) as separate
libraries used by the reader process; see NOTICE.
