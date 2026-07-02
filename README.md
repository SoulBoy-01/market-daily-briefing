# Market Daily Briefing

Auditable A-share daily market briefing MVP.

## Development

```powershell
py -3.11 -m venv .venv
# If the Windows launcher cannot find 3.11, use: python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\python -m pytest
```
