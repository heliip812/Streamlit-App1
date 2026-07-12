# Streamlit App

[![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://app-app1-yje7wiztq2gzp4qxktfb2h.streamlit.app/)

A new Streamlit application.

**Live app:** https://app-app1-yje7wiztq2gzp4qxktfb2h.streamlit.app/

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

This app is deployed on [Streamlit Community Cloud](https://share.streamlit.io) from the `main`
branch, pointed at `app.py`. Configuration lives in `.streamlit/config.toml`. Every push to `main`
auto-redeploys the live app above.

To deploy your own copy: [![Deploy on Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://share.streamlit.io/deploy?repository=heliip812/Streamlit-App1&branch=main&mainModule=app.py)
