import os
import stat
import tempfile
import subprocess
import urllib.request
import sys
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import uvicorn

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

if sys.platform == "win32":
    PIPER_EXE = os.path.join(BASE_DIR, "piper", "piper.exe")
else:
    PIPER_EXE = os.path.join(BASE_DIR, "piper", "piper")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TTSRequest(BaseModel):
    text: str
    model_href: str


def ensure_model_exists(model_input: str) -> str:
    """Sprawdza, czy model istnieje lokalnie, lub pobiera go, jeśli przekazano URL."""
    if model_input.startswith(("http://", "https://")):
        filename = os.path.basename(model_input)
        models_dir = os.path.join(BASE_DIR, "models")
        local_path = os.path.join(models_dir, filename)

        os.makedirs(models_dir, exist_ok=True)

        if not os.path.exists(local_path):
            print(f"⏳ Pobieranie modelu z {model_input}...")
            urllib.request.urlretrieve(model_input, local_path)

            json_url = model_input + ".json"
            json_path = local_path + ".json"
            if not os.path.exists(json_path):
                try:
                    urllib.request.urlretrieve(json_url, json_path)
                except Exception as e:
                    print(f"⚠️ Nie udało się pobrać pliku JSON: {e}")

        return local_path

    local_path = os.path.join(BASE_DIR, model_input)
    if not os.path.exists(local_path):
        raise FileNotFoundError(f"Plik modelu {local_path} nie istnieje na serwerze.")

    return local_path


@app.post("/api/tts")
async def generate_tts(request: TTSRequest):
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Tekst nie może być pusty")

    # 1. Nadanie uprawnień do wykonywania binarki Piper na Linuksie
    if sys.platform != "win32" and os.path.exists(PIPER_EXE):
        st = os.stat(PIPER_EXE)
        os.chmod(PIPER_EXE, st.st_mode | stat.S_IEXEC)

    try:
        model_path = ensure_model_exists(request.model_href)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Błąd modelu: {str(e)}")

    # 2. Bezpieczne tworzenie ścieżki pliku wyjściowego
    fd, output_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)  # Zamknięcie uchwytu, aby Piper mógł do niego swobodnie pisać

    clean_text = " ".join(request.text.split()) + "\n"
    command = [PIPER_EXE, "--model", model_path, "--output_file", output_path]

    try:
        # Generowanie pliku WAV
        process = subprocess.run(
            command,
            input=clean_text.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
    except subprocess.CalledProcessError as err:
        if os.path.exists(output_path):
            os.remove(output_path)
        error_msg = err.stderr.decode("utf-8", errors="ignore")
        print(f"❌ Błąd Pipera: {error_msg}")
        raise HTTPException(status_code=500, detail=f"Błąd wykonania Piper TTS: {error_msg}")

    # Zwrócenie pliku audio (FastAPI automatycznie go wyśle)
    return FileResponse(
        output_path, 
        media_type="audio/wav", 
        filename="speech.wav"
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
