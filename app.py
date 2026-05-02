from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl
from typing import Optional
import subprocess
import os
import re
import logging
import asyncio
import uuid

# Configuração mínima
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

app = FastAPI(title="YouTube Downloader")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_CONCURRENT_DOWNLOADS = 1
DOWNLOAD_TIMEOUT = 60

download_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)

class DownloadRequest(BaseModel):
    url: HttpUrl
    downloadType: str
    finalName: Optional[str] = None

def cleanup_file(filepath: str):
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
    except:
        pass

@app.post("/download")
async def download_turbo(request: DownloadRequest, background_tasks: BackgroundTasks):
    async with download_semaphore:
        start_time = asyncio.get_event_loop().time()
        
        try:
            url = str(request.url)
            download_type = request.downloadType.lower()
            
            if download_type not in ("audio", "video"):
                raise HTTPException(status_code=400, detail="Tipo deve ser 'audio' ou 'video'")

            # Nome do arquivo simples e único
            file_id = uuid.uuid4().hex[:8]
            final_name = request.finalName.strip()[:20] if request.finalName else f"dl_{file_id}"
            final_name = re.sub(r'[^\w\-_]', '', final_name)
            
            ext = "mp4" if download_type == "video" else "mp3"
            filename = f"turbo_{file_id}.{ext}"
            output_template = f"turbo_{file_id}.%(ext)s"

            # Limpeza rápida se existir
            if os.path.exists(filename):
                cleanup_file(filename)

            balanced_options = [
                '--no-mtime',
                '--no-cache-dir',
                '--no-playlist',
                '--no-warnings',
                '--socket-timeout', '15',
                '--force-ipv4',
                '--retries', '3',
                '--fragment-retries', '3',
                '--skip-unavailable-fragments',
                # YouTube bloqueia o player web (SABR / 403). Forçamos clientes
                # que ainda servem URLs diretas.
                '--extractor-args', 'youtube:player_client=android_vr,tv,web_safari',
            ]

            if download_type == "audio":
                cmd = [
                    'yt-dlp',
                    *balanced_options,
                    '-x',
                    '--audio-format', 'mp3',
                    '--audio-quality', '192K',
                    '-o', output_template,
                    url
                ]
            else:
                cmd = [
                    'yt-dlp',
                    *balanced_options,
                    '-f', 'bv*[height<=720]+ba/b[height<=720]/bv*+ba/b',
                    '--merge-output-format', 'mp4',
                    '-o', output_template,
                    url
                ]

            # EXECUÇÃO
            loop = asyncio.get_event_loop()
            
            def execute_download():
                try:
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=DOWNLOAD_TIMEOUT,
                        check=True
                    )
                    if not os.path.exists(filename):
                        logger.warning(f"arquivo esperado nao existe: {filename} | stdout={result.stdout[-500:]} stderr={result.stderr[-500:]}")
                        return False
                    if os.path.getsize(filename) <= 10240:
                        logger.warning(f"arquivo muito pequeno: {filename} ({os.path.getsize(filename)} bytes)")
                        return False
                    return True
                except subprocess.CalledProcessError as e:
                    logger.warning(f"yt-dlp falhou rc={e.returncode} stderr={(e.stderr or '')[-500:]}")
                    return False
                except subprocess.TimeoutExpired:
                    logger.warning("yt-dlp timeout no subprocess")
                    return False
                except Exception as e:
                    logger.warning(f"erro inesperado: {type(e).__name__}: {e}")
                    return False

            # DOWNLOAD ASSÍNCRONO
            success = await asyncio.wait_for(
                loop.run_in_executor(None, execute_download),
                timeout=DOWNLOAD_TIMEOUT - 2
            )

            download_time = asyncio.get_event_loop().time() - start_time

            if success:
                file_size = os.path.getsize(filename)
                logger.warning(f"✅ SUCESSO: {download_time:.2f}s, {file_size} bytes")
                
                background_tasks.add_task(cleanup_file, filename)
                
                return FileResponse(
                    path=filename,
                    filename=f"{final_name}.{ext}",
                    media_type="audio/mpeg" if download_type == "audio" else "video/mp4"
                )
            else:
                raise Exception(f"Falha no download")

        except asyncio.TimeoutError:
            download_time = asyncio.get_event_loop().time() - start_time
            logger.warning(f"⏰ TIMEOUT: {download_time:.2f}s")
            
            if 'filename' in locals():
                
                background_tasks.add_task(cleanup_file, filename)
            
            raise HTTPException(
                status_code=408,
                detail=f"Timeout: não baixou em {download_time:.1f}s (limite: {DOWNLOAD_TIMEOUT}s)"
            )
        except Exception as e:
            download_time = asyncio.get_event_loop().time() - start_time
            logger.warning(f"❌ ERRO: {download_time:.2f}s - {str(e)}")
            
            if 'filename' in locals():
                background_tasks.add_task(cleanup_file, filename)
            
            raise HTTPException(
                status_code=503,
                detail=f"Erro no download: {str(e)}"
            )

@app.get("/status")
async def status():
    return {
        "status": "ativo",
        "qualidade": "media",
        "performance": {
            "timeout_maximo_segundos": DOWNLOAD_TIMEOUT,
            "downloads_simultaneos": MAX_CONCURRENT_DOWNLOADS,
            "audio_qualidade": "192kbps",
            "video_qualidade": "até 720p"
        }
    }

@app.get("/")
async def root():
    return {"message": "🎵 YouTube Downloader - Qualidade Média"}

# Health check simples
@app.get("/health")
async def health_check():
    try:
        result = subprocess.run(['yt-dlp', '--version'], capture_output=True, timeout=3)
        return {"status": "ready", "yt_dlp": result.returncode == 0}
    except:
        return {"status": "degraded", "yt_dlp": False}