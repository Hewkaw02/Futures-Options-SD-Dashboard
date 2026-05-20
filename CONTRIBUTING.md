# Contributing to Futures Options S/D Dashboard

First off, thank you for considering contributing to the Futures Options S/D Dashboard! It's people like you that make this tool better for everyone.

## Getting Started

1. **Fork the repository** and clone it locally.
2. **Set up the environment**:
   ```bash
   python -m venv .venv
   # Windows
   .venv\Scripts\activate
   # macOS/Linux
   source .venv/bin/activate
   
   pip install -r requirements.txt
   ```
3. **Set up credentials**: Copy `.env.example` to `.env` and add your Tastytrade credentials.

## How to Contribute

### 🐛 Reporting Bugs
If you find a bug, please check if there is already an issue for it. If not, open a new issue using the **Bug Report** template. Please include as much detail as possible (logs, Python version, steps to reproduce).

### 💡 Suggesting Enhancements
Have an idea for a new feature or a quantitative analytics improvement? Open an issue using the **Feature Request** template.

### 💻 Pull Requests
1. Create a new branch for your feature (`git checkout -b feature/amazing-feature`).
2. Make your changes.
3. If you've modified quantitative modules (`analytics/`), ensure the math aligns with Black-76 models and standard conventions as documented in the README.
4. Commit your changes (`git commit -m 'Add amazing feature'`).
5. Push to the branch (`git push origin feature/amazing-feature`).
6. Open a Pull Request using the provided PR template.

## Code Style
* Keep the quantitative logic in the `analytics/` folder pure (no API calls, just math).
* Add type hints (`-> float`, `: dict`) to new functions.
* Document complex mathematical formulas in docstrings.

Thank you for your contributions!
