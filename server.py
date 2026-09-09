import os
import tempfile
import subprocess
import urllib.request
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import uvicorn

app = FastAPI()

# Włączenie CORS – umożliwia komunikację ze stroną www (np. Netlify)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Dla systemu Linux (np. Render/VPS) usuń rozszerzenie ".exe" -> "piper"
PIPER_EXE = os.path.join(BASE_DIR, "piper", "piper.exe")


class TTSRequest(BaseModel):
    text: str
    model_href: str  # Przekazana ścieżka lub URL z pliku voices.txt


def ensure_model_exists(model_input: str) -> str:
    """Sprawdza, czy model istnieje lokalnie, lub pobiera go, jeśli przekazano URL."""
    # Jeśli przekazano URL (http:// lub https://)
    if model_input.startswith(("http://", "https://")):
        filename = os.path.basename(model_input)
        local_path = os.path.join(BASE_DIR, "models", filename)

        os.makedirs(os.path.join(BASE_DIR, "models"), exist_ok=True)

        # Pobieranie pliku .onnx, jeśli jeszcze go nie ma
        if not os.path.exists(local_path):
            print(f"⏳ Pobieranie modelu z {model_input}...")
            urllib.request.urlretrieve(model_input, local_path)

            # Pobieranie odpowiadającego pliku .json (wymagany przez Piper)
            json_url = model_input + ".json"
            json_path = local_path + ".json"
            if not os.path.exists(json_path):
                try:
                    urllib.request.urlretrieve(json_url, json_path)
                except Exception as e:
                    print(f"⚠️ Nie udało się pobrać pliku JSON: {e}")

        return local_path

    # Jeśli przekazano ścieżkę lokalną (np. "en_GB-jenny_dioco-medium.onnx")
    local_path = os.path.join(BASE_DIR, model_input)
    if not os.path.exists(local_path):
        raise FileNotFoundError(f"Plik modelu {local_path} nie istnieje na serwerze.")

    return local_path


@app.post("/api/tts")
async def generate_tts(request: TTSRequest):
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Tekst nie może być pusty")

    try:
        # Pobranie lub weryfikacja ścieżki do modelu .onnx
        model_path = ensure_model_exists(request.model_href)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Błąd modelu: {str(e)}")

    # Tworzenie tymczasowego pliku WAV
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    output_path = temp_file.name
    temp_file.close()

    clean_text = " ".join(request.text.split()) + "\n"

    command = [PIPER_EXE, "--model", model_path, "--output_file", output_path]

    try:
        # Generowanie pliku WAV
        subprocess.run(
            command,
            input=clean_text.encode("utf-8"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    except subprocess.CalledProcessError:
        if os.path.exists(output_path):
            os.remove(output_path)
        raise HTTPException(status_code=500, detail="Błąd wykonania Piper TTS")

    return FileResponse(output_path, media_type="audio/wav", filename="speech.wav")


if __name__ == "__main__":
    import uvicorn
    import os

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
