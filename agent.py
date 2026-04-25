from __future__ import annotations

import os

import uvicorn
from dotenv import load_dotenv


def main() -> None:
    load_dotenv()
    host = os.getenv("INCA_HOST", "127.0.0.1")
    port = int(os.getenv("INCA_PORT", "8088"))
    uvicorn.run("inca_voice.twilio_app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
