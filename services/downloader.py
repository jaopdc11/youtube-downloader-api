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
    downloadType: str  # "audio" ou "video"
    finalName: Optional[str] = None

def run_yt_dlp(command):
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"Download failed: {e}")

@app.get("/ping")
async def ping():
    return {"message": "pong"}

@app.post("/download")
async def download(request: DownloadRequest):
    url = str(request.url)
    download_type = request.downloadType.lower()
    final_name = request.finalName.strip() if request.finalName else "download"

    if download_type not in ("audio", "video"):
        raise HTTPException(status_code=400, detail="downloadType must be 'audio' or 'video'")

    ext = "mp3" if download_type == "audio" else "mp4"
    filename = f"{final_name}.{ext}"

    # Garante que não exista um resto antigo
    if os.path.exists(filename):
        os.remove(filename)

    # Comando yt-dlp
    if download_type == "video":
        run_yt_dlp([
            "yt-dlp",
            "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4",
            "-o", filename,
            url
        ])
    else:
        run_yt_dlp([
            "yt-dlp",
            "-x",
            "--audio-format", ext,
            "-o", filename,
            url
        ])

    if not os.path.exists(filename):
        raise HTTPException(status_code=500, detail="File not found after download")

    # Envia o arquivo e remove depois
    response = FileResponse(
        path=filename,
        filename=filename,
        media_type="audio/mpeg" if download_type == "audio" else "video/mp4",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

    @response.call_on_close
    def cleanup():
        os.remove(filename)

    return response
