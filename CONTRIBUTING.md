# Contributing to CookDex

Thanks for your interest in contributing! CookDex is open source under the [AGPL-3.0 license](LICENSE).

## Getting Started

1. Fork the repository and clone your fork
2. Follow [Local Dev](docs/LOCAL_DEV.md) to set up your environment
3. Create a branch for your change: `git checkout -b my-feature`
4. Make your changes
5. Run the test suite: `python -m pytest`
6. Build the frontend: `cd web && npm run build`
7. Push and open a pull request

## Development Setup

```bash
pip install -e ".[dev]"
cd web && npm install && cd ..
```

See [docs/LOCAL_DEV.md](docs/LOCAL_DEV.md) for detailed instructions including Vite dev server setup for hot reloading.

## Project Structure

| Directory | Contents |
|---|---|
| `src/cookdex/` | Python backend — tasks, API client, DB client |
| `src/cookdex/webui_server/` | FastAPI web server, routers, state store |
| `web/src/` | React frontend (single `App.jsx` + component files) |
| `web/src/styles.css` | All CSS (no preprocessor) |
| `tests/` | pytest test suite |

## Guidelines

- **Tests**: All changes should pass the existing test suite. Add tests for new functionality.
- **No external UI libraries**: The frontend is built from scratch — keep it that way.
- **CSS**: All styles go in `web/src/styles.css`. Use the existing custom properties (`--accent`, `--bg`, etc.).
- **Security**: Never log secrets. Use parameterized SQL. Validate user input at system boundaries.
- **Keep it simple**: Prefer the minimum change that solves the problem. Don't add abstractions for hypothetical future needs.

## Reporting Issues

- **Bugs**: Use the [bug report template](https://github.com/thekannen/CookDex/issues/new?template=bug_report.md)
- **Features**: Use the [feature request template](https://github.com/thekannen/CookDex/issues/new?template=feature_request.md)
- **Security**: See [SECURITY.md](SECURITY.md) for responsible disclosure
