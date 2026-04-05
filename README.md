# BrainCache

BrainCache is a local threat intelligence learning tool for cybersecurity analysts. It fetches articles from RSS feeds and scrape sources, then guides you through a Feynman-method session on each one: you predict the attacker's approach before reading, answer Socratic questions after reading, and receive a summary of what you understood and what you need to study further. Unknown terms are automatically added to a persistent notebook with plain-language explanations. Everything runs on your machine. No API keys, no accounts, no telemetry.

## Quick start

```bash
git clone <repo>
cd braincache
cp .env.example .env
docker compose up --build
```

Open http://localhost:7337

On first run, Ollama will download the default model (~2GB). The UI will show a red flower indicator until the download completes — typically 5–15 minutes depending on connection speed.

## Requirements

- Docker and Docker Compose
- Linux desktop with audio hardware
- 8 GB RAM minimum, 16 GB recommended
- ~5 GB disk space (model + application)

## How it works

BrainCache applies the Feynman learning technique to threat intelligence reading. The core idea is that you understand something properly only when you can explain it plainly without jargon. Passive reading does not build durable knowledge. Forcing yourself to predict, explain, and summarize does.

Before reading an article, BrainCache asks you to predict what the attacker's initial access method and end goal were based on the title alone. After the article text is fetched, it generates four Socratic questions customised to the specific incident: the initial access method, the earliest detection opportunity, the single change that would have altered the outcome, and a 90-second executive briefing exercise.

Unknown terms from the title and summary are automatically added to your I Don't Know notebook with Feynman-structured entries: a hypothesis question, a plain-language explanation, a MITRE ATT&CK reference if applicable, and a resolution target — the exact sentence you must be able to say clearly to consider the term understood.

## The workflow

1. Add sources on the Sources tab — RSS feeds or scrape targets with a CSS selector.
2. Click Poll All Sources or wait for the scheduled poll (default every 6 hours).
3. New articles appear in the Feed. Click any article card to load it into the Session tab.
4. Click Start Session. BrainCache fetches the full article text and generates the pre-read question.
5. Answer the hypothesis question, then work through the four Socratic questions.
6. After the final question, a summary panel shows your strong points, knowledge gaps, and recommended notebook entries.
7. Review your I Don't Know notebook and work through entries until you can say the resolution target clearly.

## Voice interaction

TTS: Piper reads questions aloud. Each question is spoken as it appears on screen.

STT: whisper.cpp transcribes your spoken answers. When voice mode is enabled, a microphone button replaces the text area. Click the mic button or press Space to start recording. Press Space again or click to stop. The transcription appears and can be edited before submitting.

Voice status is shown in the header as two 5-petal flower indicators. Green = available, red = unavailable. Both TTS and STT must be installed inside the Docker image — the Dockerfile handles this.

If voice is unavailable, the toggle is hidden and text mode is used automatically.

**Audio troubleshooting:**

```bash
sudo usermod -aG audio $USER
# Log out and back in for the change to take effect
```

## Changing the AI model

Edit `.env`:

```
OLLAMA_MODEL=mistral
```

Then restart: `docker compose up --build`

Recommended models:

| Model | Notes |
|-------|-------|
| `llama3.2` | Default. Good balance of quality and speed. |
| `mistral` | Faster, slightly smaller context window. |
| `phi3` | Fastest. Good for weaker hardware (&lt;8 GB RAM). |
| `llama3.1` | Highest quality. Larger download (~5 GB). |

Full model list: https://ollama.com/library

## Adding sources

**RSS:** Paste any RSS or Atom feed URL and select RSS as the type.

**Scrape:** Paste a page URL, select Scrape, and provide a CSS selector that targets article link elements on that page.

To find a CSS selector: open the page in a browser, right-click an article link, choose Inspect, and note the pattern of the element and its parents. A selector like `article h2 a` or `.post-title a` is typical.

Use the Test button to verify the selector detects articles before saving the source.

## The I Don't Know notebook

Entries are created automatically during sessions for terms flagged as potentially unknown in article titles and summaries. You can also add terms manually from the notebook view.

Each entry includes a hypothesis question (what do you think this means?), a plain-language explanation with no jargon, a MITRE ATT&CK reference if applicable, three Socratic questions about the technique, and a resolution target.

Mark an entry resolved when you can say the resolution target clearly without looking. Resolved entries move to the right column and remain searchable.

Export the full notebook as a Markdown file using the Export .md button in the notebook header.

Entries link back to the source article where the term was first encountered.

## Keyboard shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+Enter` | Submit current session response |
| `Space` | Start/stop voice recording (session, voice mode only) |
| `Escape` | Dismiss toast notification |

## Configuration reference

`config.yaml` options:

| Key | Default | Description |
|-----|---------|-------------|
| `db_path` | `/app/data/braincache.db` | SQLite database path |
| `poll_interval_hours` | `6` | How often to poll all active sources |
| `piper_binary` | `/app/piper/piper` | Path to Piper TTS binary |
| `piper_model` | `/app/piper/en_US-lessac-medium.onnx` | Piper voice model |
| `whisper_binary` | `/app/whisper.cpp/main` | Path to whisper.cpp binary |
| `whisper_model` | `/app/whisper.cpp/models/ggml-base.en.bin` | Whisper model file |

## Troubleshooting

### Ollama status shows red

```bash
docker compose ps                    # check if ollama container is running
docker compose logs ollama           # check for errors
```

The model may still be downloading on first run. The indicator turns green once the model is ready.

### Voice not working

Check TTS and STT indicators in the header. If both are red:

```bash
sudo usermod -aG audio $USER         # add user to audio group, then log out/in
docker compose logs braincache | grep -i piper
docker compose logs braincache | grep -i whisper
```

### Scrape source returns 0 articles

Verify the CSS selector in browser devtools. Some sites block automated requests — try a more specific User-Agent in config. Use the Test button after any selector change.

### Sessions hang or time out

Local model inference is slow on first run while the model loads into memory. Subsequent questions in the same session are faster.

```bash
docker compose logs braincache | grep -i ollama
```

Consider switching to a smaller model in `.env` if RAM is limited. Minimum recommended: 8 GB for `llama3.2`.

### Database issues

The database lives in Docker volume `braincache-data`. To reset completely:

```bash
docker compose down -v
docker compose up --build
```

## Architecture

```
┌─────────────────────────────────┐   ┌──────────────────────┐
│  braincache                     │   │  ollama              │
│                                 │   │                      │
│  FastAPI (port 7337)            │◄──►  Local LLM inference │
│  Piper TTS                      │   │  (port 11434)        │
│  whisper.cpp STT                │   │                      │
│  SQLite (braincache-data vol)   │   │                      │
└─────────────────────────────────┘   └──────────────────────┘
```

Both services run inside Docker. No data leaves your machine. No API keys. No accounts. No telemetry.

## License

MIT
