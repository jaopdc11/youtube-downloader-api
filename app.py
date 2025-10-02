from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl
from typing import Optional
import subprocess
import os

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class DownloadRequest(BaseModel):
    url: HttpUrl
    downloadType: str
    finalName: Optional[str] = None

def update_yt_dlp():
    """Atualiza o yt-dlp no startup"""
    try:
        print("Updating yt-dlp...")
        result = subprocess.run(
            ["pip", "install", "--upgrade", "yt-dlp"], 
            check=True, 
            capture_output=True, 
            text=True,
            timeout=60
        )
        print("yt-dlp updated successfully")
    except Exception as e:
        print(f"Update warning: {e}")

@app.on_event("startup")
async def startup_event():
    update_yt_dlp()

@app.get("/ping")
async def ping():
    return {"message": "pong"}

@app.post("/download")
async def download(request: DownloadRequest):
    url = str(request.url)
    download_type = request.downloadType.lower()
    final_name = request.finalName.strip() if request.finalName else None

    if download_type not in ("audio", "video"):
        raise HTTPException(status_code=400, detail="downloadType must be 'audio' or 'video'")

    # EXTAMENTE a mesma lógica do seu script CLI
    ext = "mp4" if download_type == "video" else "mp3"
    filename = f"{final_name}.{ext}" if final_name else None

    try:
        if download_type == "video":
            if filename:
                # Comando IDÊNTICO ao seu script
                subprocess.run([
                    'yt-dlp', 
                    '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4', 
                    '-o', filename, 
                    url
                ], check=True, capture_output=True, timeout=120)
            else:
                subprocess.run([
                    'yt-dlp', 
                    '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4', 
                    url
                ], check=True, capture_output=True, timeout=120)
        else:  # audio
            if filename:
                # Comando IDÊNTICO ao seu script  
                subprocess.run([
                    'yt-dlp', 
                    '-x', 
                    '--audio-format', ext, 
                    '-o', filename, 
                    url
                ], check=True, capture_output=True, timeout=120)
            else:
                subprocess.run([
                    'yt-dlp', 
                    '-x', 
                    '--audio-format', ext, 
                    url
                ], check=True, capture_output=True, timeout=120)

        # Se filename foi especificado, retorna o arquivo
        if filename and os.path.exists(filename):
            response = FileResponse(
                path=filename,
                filename=filename,
                media_type="audio/mpeg" if download_type == "audio" else "video/mp4"
            )

            @response.call_on_close
            def cleanup():
                if os.path.exists(filename):
                    try:
                        os.remove(filename)
                    except:
                        pass

            return response
        else:
            # Se não tinha filename, só confirma o download
            return {"message": "Download completed successfully"}

    except subprocess.CalledProcessError as e:
        error_msg = f"Download failed: {e.stderr.decode() if e.stderr else str(e)}"
        print(f"Error: {error_msg}")
        raise HTTPException(status_code=500, detail=error_msg)
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        print(f"Error: {error_msg}")
        raise HTTPException(status_code=500, detail=error_msg)