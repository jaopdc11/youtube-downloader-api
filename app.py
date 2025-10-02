from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from typing import Optional
from services.downloader import download_audio, download_video
import subprocess

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

@app.get("/ping")
async def ping():
    return {"message": "pong"}

from fastapi.responses import FileResponse
import os

@app.post("/download")
async def download(request: DownloadRequest):
    url = str(request.url)  # converte para string
    download_type = request.downloadType.lower()
    final_name = request.finalName.strip() if request.finalName else None

    if download_type not in ("audio", "video"):
        raise HTTPException(status_code=400, detail="downloadType must be 'audio' or 'video'")

    if final_name == "":
        final_name = None

    ext = "mp3" if download_type == "audio" else "mp4"
    filename = f"{final_name}.{ext}" if final_name else f"download.{ext}"

    try:
        if download_type == "video":
            download_video(url, title=final_name, ext=ext)
        else:
            download_audio(url, title=final_name, ext=ext)
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"Download failed: {e}")

    if not os.path.exists(filename):
        raise HTTPException(status_code=500, detail="File not found after download")

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
