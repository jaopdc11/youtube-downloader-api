from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl
from typing import Optional
import subprocess
import os
import re
import requests
import tempfile

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

def extract_video_id(url):
    """Extrai o ID do vídeo do YouTube"""
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/)([^&?\n]+)',
        r'youtube\.com/embed/([^&?\n]+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def download_via_external_service(video_id: str, download_type: str, filename: str) -> bool:
    """Tenta baixar via serviço externo quando yt-dlp falha"""
    try:
        # Serviços externos como fallback
        if download_type == "audio":
            # Tenta API pública para áudio
            api_urls = [
                f"https://youtube-audio-downloader.vercel.app/api/audio?url=https://youtube.com/watch?v={video_id}",
                f"https://yt-api.cyclic.app/audio?url=https://youtube.com/watch?v={video_id}",
            ]
        else:
            # Tenta API pública para vídeo
            api_urls = [
                f"https://yt-api.cyclic.app/video?url=https://youtube.com/watch?v={video_id}",
            ]
        
        for api_url in api_urls:
            try:
                print(f"Trying external API: {api_url}")
                response = requests.get(api_url, stream=True, timeout=30)
                
                if response.status_code == 200:
                    with open(filename, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                    
                    # Verifica se o arquivo tem tamanho razoável
                    if os.path.exists(filename) and os.path.getsize(filename) > 1024:
                        print(f"Success with external API: {api_url}")
                        return True
            except Exception as e:
                print(f"External API failed: {e}")
                continue
        
        return False
    except Exception as e:
        print(f"All external services failed: {e}")
        return False

@app.post("/download")
async def download(request: DownloadRequest):
    url = str(request.url)
    download_type = request.downloadType.lower()
    final_name = request.finalName.strip() if request.finalName else "download"

    if download_type not in ("audio", "video"):
        raise HTTPException(status_code=400, detail="downloadType must be 'audio' or 'video'")

    ext = "mp4" if download_type == "video" else "mp3"
    filename = f"{final_name}.{ext}"
    video_id = extract_video_id(url)

    # Clean up old file
    if os.path.exists(filename):
        os.remove(filename)

    # PRIMEIRA TENTATIVA: yt-dlp simples (seu método original)
    try:
        print("Trying direct yt-dlp method...")
        if download_type == "video":
            cmd = ['yt-dlp', '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4', '-o', filename, url]
        else:
            cmd = ['yt-dlp', '-x', '--audio-format', 'mp3', '-o', filename, url]
        
        result = subprocess.run(
            cmd, 
            check=True, 
            capture_output=True, 
            text=True,
            timeout=120
        )
        
        if os.path.exists(filename) and os.path.getsize(filename) > 1024:
            print("Success with direct yt-dlp method!")
            
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
            raise Exception("File too small or missing")
            
    except Exception as e:
        print(f"Direct yt-dlp failed: {e}")
        
        # SEGUNDA TENTATIVA: Serviço externo
        if video_id:
            print("Trying external service...")
            success = download_via_external_service(video_id, download_type, filename)
            
            if success:
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

        # SE TUDO FALHAR
        error_msg = (
            "Failed to download the requested media. Please check the URL and try again later."
        )
        
        raise HTTPException(status_code=503, detail=error_msg)

@app.get("/ping")
async def ping():
    return {"message": "pong"}

@app.get("/")
async def root():
    return {
        "message": "YouTube Downloader API", 
        "status": "active"
    }