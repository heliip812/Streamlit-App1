# Streamlit App

A new Streamlit application.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```

## Run locally

```bash
streamlit run app.py
```

## Lint & test

```bash
ruff check .
pytest
```

## Deploy

This repo is structured for deployment on [Streamlit Community Cloud](https://share.streamlit.io):
point it at `app.py` on the `main` branch. Configuration lives in `.streamlit/config.toml`.
