# Stock Narrative Engine

**Turns live market data, news and congressional-trading signals into AI-written research briefs — on demand or on a schedule.**

Stock Narrative Engine (SNE) pulls market data, headlines and alternative signals for the sectors you choose, then has an LLM synthesise them into a concise, sourced narrative: what moved, why, and what to watch next. Output as a rich terminal report, a standalone HTML page, or a headless scheduled job that emails or messages the brief.

> Personal project, built end-to-end. Every API key is read from the environment — nothing sensitive is committed.

## Features
- **Multi-source data** — prices & fundamentals via `yfinance`; headlines via NewsAPI, Finnhub, Alpha Vantage and RSS/Atom feeds; a congressional-trading signal module.
- **Pluggable AI providers** — Anthropic Claude, OpenAI GPT, Google Gemini, or a local Ollama model; switch with `--provider`.
- **Backtesting** — a dedicated module to evaluate signals/narratives against history.
- **Flexible delivery** — rich terminal UI, HTML export, or headless JSON; optional email (SMTP / Resend) and Telegram notifications.
- **Runs unattended** — headless modes plus Windows Task Scheduler scripts for scheduled briefs.

## Architecture
```
src/
  market/         price & fundamentals ingestion
  news/           headline & RSS ingestion
  congress/       congressional-trading signal
  ai/             provider abstraction (Claude / GPT / Gemini / Ollama)
  backtest/       historical evaluation
  notifications/  email (SMTP / Resend) + Telegram
  data/           storage & models
  utils/          shared helpers
config.py         typed config — all secrets via environment variables
main.py           CLI entry point
```

## Stack
Python · yfinance · feedparser · requests · rich · Anthropic / OpenAI / Google-Generative-AI SDKs · optional Ollama.

## Quick start
```bash
pip install -r requirements.txt
cp .env.example .env        # fill in your API keys
python main.py --sectors technology artificial_intelligence crypto
```

More modes:
```bash
python main.py --quick              # RSS only, no market data
python main.py --provider openai    # choose the LLM
python main.py --html --open        # export HTML and open it
python main.py --json-only --no-rich    # headless / scheduled
python main.py --help               # all options
```

All credentials load from `.env` / environment (full list in `config.py`); none are stored in the repo.
