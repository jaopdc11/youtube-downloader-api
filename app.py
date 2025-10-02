from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl
from typing import Optional
import subprocess
import os
import random
import re

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

def update_yt_dlp():
    """Atualiza o yt-dlp no startup"""
    try:
        subprocess.run(
            ["pip", "install", "--upgrade", "yt-dlp"], 
            check=True, 
            capture_output=True,
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
    final_name = request.finalName.strip() if request.finalName else "download"

    if download_type not in ("audio", "video"):
        raise HTTPException(status_code=400, detail="downloadType must be 'audio' or 'video'")

    ext = "mp4" if download_type == "video" else "mp3"
    filename = f"{final_name}.{ext}"

    # Clean up old file
    if os.path.exists(filename):
        os.remove(filename)

    # Estratégias em ordem de tentativa
    strategies = [
        # Estratégia 1: SIMPLES - igual seu script CLI
        {
            "name": "Simple CLI method",
            "video_cmd": ['yt-dlp', '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4', '-o', filename, url],
            "audio_cmd": ['yt-dlp', '-x', '--audio-format', 'mp3', '-o', filename, url]
        },
        # Estratégia 2: AGGRESSIVA - anti-bloqueio
        {
            "name": "Anti-block method", 
            "video_cmd": [
                'yt-dlp', 
                '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                '--referer', 'https://www.youtube.com/',
                '--force-ipv4',
                '--no-check-certificate',
                '--throttled-rate', '100K',
                '--sleep-requests', '2',
                '--geo-bypass',
                '-f', 'best[height<=720]',
                '-o', filename, 
                url
            ],
            "audio_cmd": [
                'yt-dlp',
                '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                '--referer', 'https://www.youtube.com/',
                '--force-ipv4', 
                '--no-check-certificate',
                '--throttled-rate', '100K',
                '--sleep-requests', '2',
                '--geo-bypass',
                '-x', '--audio-format', 'mp3',
                '-o', filename,
                url
            ]
        },
        # Estratégia 3: URL ALTERNATIVA - youtu.be
        {
            "name": "Alternative URL method",
            "video_cmd": ['yt-dlp', '-f', 'best[height<=480]', '-o', filename, f'https://youtu.be/{extract_video_id(url)}'],
            "audio_cmd": ['yt-dlp', '-x', '--audio-format', 'mp3', '-o', filename, f'https://youtu.be/{extract_video_id(url)}']
        }
    ]

    last_error = None

    for i, strategy in enumerate(strategies):
        try:
            print(f"Trying strategy {i+1}: {strategy['name']}")
            
            if download_type == "video":
                cmd = strategy["video_cmd"]
            else:
                cmd = strategy["audio_cmd"]
            
            # Remove None values if any
            cmd = [arg for arg in cmd if arg is not None]
            
            result = subprocess.run(
                cmd, 
                check=True, 
                capture_output=True, 
                text=True,
                timeout=120
            )
            
            # Check if file was created and has reasonable size
            if os.path.exists(filename) and os.path.getsize(filename) > 1024:
                print(f"Success with strategy {i+1}")
                
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
                raise Exception("Downloaded file is too small or missing")
                
        except Exception as e:
            last_error = e
            print(f"Strategy {i+1} failed: {e}")
            
            # Clean up failed file
            if os.path.exists(filename):
                try:
                    os.remove(filename)
                except:
                    pass
            
            continue

    # If all strategies failed
    error_detail = f"All download methods failed. Last error: {str(last_error)}"
    
    # Provide helpful error message
    if "Sign in to confirm you're not a bot" in str(last_error):
        error_detail += "\n\nSOLUTION: YouTube is blocking our server IP. Please try again later.\n" \
    
    raise HTTPException(status_code=500, detail=error_detail)