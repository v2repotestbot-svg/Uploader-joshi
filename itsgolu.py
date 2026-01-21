import os
import re
import time
import asyncio
import logging
import subprocess
import requests
from math import ceil
from pathlib import Path
from pyrogram import Client
from pyrogram.types import Message
from utils import progress_bar

# --- Helper Functions ---

def get_duration(filename):
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", filename],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=True
        )
        return float(result.stdout)
    except Exception:
        return 0

def split_large_video(file_path, max_size_mb=1900):
    size_bytes = os.path.getsize(file_path)
    max_bytes = max_size_mb * 1024 * 1024

    if size_bytes <= max_bytes:
        return [file_path]

    duration = get_duration(file_path)
    if duration == 0: return [file_path]

    parts = ceil(size_bytes / max_bytes)
    part_duration = duration / parts
    base_name = file_path.rsplit(".", 1)[0]
    output_files = []

    for i in range(parts):
        output_file = f"{base_name}_part{i+1}.mp4"
        cmd = [
            "ffmpeg", "-y", "-i", file_path,
            "-ss", str(int(part_duration * i)),
            "-t", str(int(part_duration)),
            "-c", "copy", "-map", "0", output_file
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(output_file):
            output_files.append(output_file)

    return output_files

# --- Downloading Logic ---

async def download_video(url, cmd, name):
    """
    Classplus/ClassX links ko download karne ke liye optimized version.
    """
    cookies_path = "youtube_cookies.txt"
    cookie_arg = f"--cookies {cookies_path}" if os.path.exists(cookies_path) else ""
    
    # Classplus links ke liye Referer aur User-Agent sabse zaroori hain
    headers = (
        '--add-header "Referer:https://web.classplusapp.com/" '
        '--add-header "User-Agent:Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36" '
        '--add-header "Origin:https://web.classplusapp.com"'
    )

    # Final command with Aria2c for 16x speed
    download_cmd = f'{cmd} {headers} {cookie_arg} --no-check-certificate --external-downloader aria2c --downloader-args "aria2c: -x 16 -j 32"'
    
    logging.info(f"Downloading: {name}")
    
    # Run download process
    process = subprocess.run(download_cmd, shell=True)
    
    # Retry without aria2c if it fails
    if process.returncode != 0:
        logging.warning("Aria2c failed, retrying with native downloader...")
        download_cmd = f'{cmd} {headers} {cookie_arg} --no-check-certificate'
        subprocess.run(download_cmd, shell=True)

    # Check for the downloaded file
    for ext in ['mp4', 'mkv', 'webm', 'ts']:
        if os.path.isfile(f"{name}.{ext}"):
            return f"{name}.{ext}"
        if os.path.isfile(name):
            return name
            
    return f"{name}.mp4"

# --- Uploading Logic ---

async def send_vid(bot: Client, m: Message, cc, filename, thumb, name, prog, channel_id, watermark="/d"):
    try:
        # 1. Thumbnail Setup
        temp_thumb = None
        if thumb in ["/d", "no"] or not os.path.exists(thumb):
            temp_thumb = f"thumb_{time.time()}.jpg"
            subprocess.run(f'ffmpeg -i "{filename}" -ss 00:00:05 -vframes 1 -y "{temp_thumb}"', shell=True)
            thumbnail = temp_thumb if os.path.exists(temp_thumb) else None
        else:
            thumbnail = thumb

        # 2. Upload Progress Handle
        await prog.delete()
        upload_msg = await bot.send_message(channel_id, f"📤 **Uploading:** `{name}`")
        
        # 3. Size Check & Split
        file_size = os.path.getsize(filename)
        files_to_upload = [filename]
        
        if file_size > 2000 * 1024 * 1024: # 2GB+
            await upload_msg.edit("✂️ **File is > 2GB, splitting into parts...**")
            files_to_upload = split_large_video(filename)

        # 4. Final Upload
        for up_file in files_to_upload:
            dur = int(get_duration(up_file))
            start_time = time.time()
            
            try:
                await bot.send_video(
                    chat_id=channel_id,
                    video=up_file,
                    caption=cc,
                    supports_streaming=True,
                    thumb=thumbnail,
                    duration=dur,
                    progress=progress_bar,
                    progress_args=(upload_msg, start_time)
                )
            except Exception as e:
                logging.error(f"Video upload failed: {e}")
                await bot.send_document(chat_id=channel_id, document=up_file, caption=cc)

            if os.path.exists(up_file): os.remove(up_file)

        # Cleanup
        if temp_thumb and os.path.exists(temp_thumb): os.remove(temp_thumb)
        if os.path.exists(filename): os.remove(filename)
        await upload_msg.delete()

    except Exception as e:
        logging.error(f"Send Vid Error: {e}")
        await m.reply_text(f"❌ Upload Error: {str(e)}")
        
