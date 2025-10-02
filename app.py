from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl
from typing import Optional
import subprocess
import os
import random
import time
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

# Lista de User-Agents rotativos
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
]

def get_random_user_agent():
    return random.choice(USER_AGENTS)

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

def get_alternative_urls(url):
    """Gera URLs alternativas para o mesmo vídeo"""
    video_id = extract_video_id(url)
    if not video_id:
        return [url]
    
    return [
        f"https://youtu.be/{video_id}",
        f"https://www.youtube.com/watch?v={video_id}",
        f"https://www.youtube.com/embed/{video_id}",
    ]

def run_yt_dlp(command, max_retries=2):
    """Executa yt-dlp com retry automático"""
    for attempt in range(max_retries):
        try:
            result = subprocess.run(
                command, 
                check=True, 
                capture_output=True, 
                text=True,
                timeout=300
            )
            return result
        except subprocess.CalledProcessError as e:
            if attempt == max_retries - 1:
                raise e
            wait_time = (2 ** attempt) + random.uniform(0, 1)
            print(f"Attempt {attempt + 1} failed, retrying in {wait_time:.2f} seconds...")
            time.sleep(wait_time)

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

    ext = "mp3" if download_type == "audio" else "mp4"
    filename = f"{final_name}.{ext}"

    # Limpa arquivo antigo se existir
    if os.path.exists(filename):
        os.remove(filename)

    # Gera URLs alternativas
    alternative_urls = get_alternative_urls(url)
    print(f"Trying URLs: {alternative_urls}")

    # Estratégias de download para tentar
    download_strategies = [
        # Estratégia 1: Configuração robusta com qualidade balanceada
        lambda u: [
            "yt-dlp",
            "--user-agent", get_random_user_agent(),
            "--referer", "https://www.youtube.com/",
            "--throttled-rate", "100K",
            "--sleep-requests", "2",
            "--sleep-interval", "3",
            "--max-sleep-interval", "8",
            "--force-ipv4",
            "--no-check-certificate",
            "-x" if download_type == "audio" else "-f",
            "mp3" if download_type == "audio" else "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]",
            "--audio-format", "mp3" if download_type == "audio" else None,
            "--audio-quality", "0" if download_type == "audio" else None,
            "--merge-output-format", "mp4" if download_type == "video" else None,
            "-o", filename,
            u
        ],
        
        # Estratégia 2: Configuração simplificada
        lambda u: [
            "yt-dlp",
            "--user-agent", get_random_user_agent(),
            "--force-ipv4",
            "--no-check-certificate",
            "-x" if download_type == "audio" else "-f",
            "mp3" if download_type == "audio" else "best[height<=480]",
            "--audio-format", "mp3" if download_type == "audio" else None,
            "-o", filename,
            u
        ],
        
        # Estratégia 3: Mínima (último recurso)
        lambda u: [
            "yt-dlp",
            "--user-agent", get_random_user_agent(),
            "-x" if download_type == "audio" else "-f",
            "best" if download_type == "audio" else "best",
            "-o", filename,
            u
        ]
    ]

    last_error = None

    # Tenta cada combinação de URL + estratégia
    for current_url in alternative_urls:
        for strategy_index, strategy in enumerate(download_strategies):
            try:
                print(f"Trying URL: {current_url} with strategy {strategy_index + 1}")
                
                # Gera o comando e remove elementos None
                command = [arg for arg in strategy(current_url) if arg is not None]
                
                run_yt_dlp(command, max_retries=2)

                # Verifica se o download foi bem-sucedido
                if os.path.exists(filename) and os.path.getsize(filename) > 1024:
                    print(f"Success with URL: {current_url} and strategy {strategy_index + 1}")
                    
                    response = FileResponse(
                        path=filename,
                        filename=filename,
                        media_type="audio/mpeg" if download_type == "audio" else "video/mp4"
                    )

                    @response.call_on_close
                    def cleanup():
                        if os.path.exists(filename):
                            os.remove(filename)

                    return response
                else:
                    # Limpa arquivo corrompido
                    if os.path.exists(filename):
                        os.remove(filename)
                    raise Exception("Downloaded file is too small or corrupted")

            except Exception as e:
                last_error = e
                print(f"Failed with URL: {current_url} and strategy {strategy_index + 1}: {e}")
                
                # Limpa arquivo se existir
                if os.path.exists(filename):
                    os.remove(filename)
                
                # Pequena pausa entre tentativas
                time.sleep(1)
                continue

    # Se todas as tentativas falharem
    error_msg = f"All download attempts failed. Last error: {str(last_error)}"
    raise HTTPException(status_code=500, detail=error_msg)