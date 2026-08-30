from flask import Flask, render_template, request, jsonify, send_file
import yt_dlp
import os
import subprocess
import json
import re
import random
from datetime import datetime
import tempfile
import shutil
import sys

app = Flask(__name__)
app.secret_key = 'alfonso-studio-secret-key'

# ========================================================
# KONFIGURASI UNTUK VERCEL
# ========================================================

# Gunakan /tmp untuk Vercel (writable)
TEMP_FOLDER = '/tmp' if os.path.exists('/tmp') else tempfile.mkdtemp()
app.config['TEMP_FOLDER'] = TEMP_FOLDER

# Cek FFmpeg
FFMPEG_AVAILABLE = False
try:
    result = subprocess.run(['ffmpeg', '-version'], capture_output=True, timeout=5)
    if result.returncode == 0:
        FFMPEG_AVAILABLE = True
        print("✅ FFmpeg tersedia")
    else:
        print("❌ FFmpeg tidak tersedia")
except:
    print("❌ FFmpeg tidak ditemukan")

# ========================================================
# ROUTES
# ========================================================

@app.route('/')
def index():
    return render_template('index.html', ffmpeg_available=FFMPEG_AVAILABLE)

@app.route('/health')
def health():
    return jsonify({
        'status': 'OK',
        'ffmpeg': FFMPEG_AVAILABLE,
        'temp_folder': TEMP_FOLDER,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/download', methods=['POST'])
def download():
    try:
        data = request.json
        url = data.get('url')
        format_type = data.get('format', 'mp3')
        
        if not url:
            return jsonify({'error': 'URL tidak boleh kosong'}), 400
        
        # Gunakan folder /tmp untuk Vercel
        output_template = os.path.join(TEMP_FOLDER, '%(title)s.%(ext)s')
        
        ydl_opts = {
            'outtmpl': output_template,
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'ignoreerrors': True,
        }
        
        if format_type == 'mp3':
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192'
                }]
            })
        else:
            ydl_opts.update({
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
            })
        
        print(f"📥 Downloading: {url[:50]}...")
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            # Cari file hasil download
            base_filename = ydl.prepare_filename(info)
            filename = base_filename
            
            if format_type == 'mp3':
                # Coba cari file mp3
                possible_names = [
                    base_filename.replace('.webm', '.mp3'),
                    base_filename.replace('.m4a', '.mp3'),
                    base_filename.replace('.webm', '.mp3').replace(' ', '_'),
                ]
                for name in possible_names:
                    if os.path.exists(name):
                        filename = name
                        break
            
            if not os.path.exists(filename):
                # Cari file terbaru di /tmp
                files = [f for f in os.listdir(TEMP_FOLDER) if f.endswith(('.mp3', '.mp4'))]
                if files:
                    files.sort(key=lambda x: os.path.getmtime(os.path.join(TEMP_FOLDER, x)), reverse=True)
                    filename = os.path.join(TEMP_FOLDER, files[0])
            
            print(f"✅ File selesai: {os.path.basename(filename)}")
            
            return jsonify({
                'success': True,
                'filename': os.path.basename(filename),
                'title': info.get('title', 'Unknown'),
                'ffmpeg': FFMPEG_AVAILABLE
            })
            
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/get_chapters', methods=['POST'])
def get_chapters():
    try:
        data = request.json
        url = data.get('url')
        
        if not url:
            return jsonify({'error': 'URL tidak boleh kosong'}), 400
        
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'ignoreerrors': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            chapters = info.get('chapters', [])
            
            clean_chapters = []
            for i, ch in enumerate(chapters):
                title = re.sub(r'[\\/*?:"<>|]', '', ch.get('title', f'Track {i+1}'))
                clean_chapters.append({
                    'seconds': ch.get('start_time', 0),
                    'title': title
                })
            
            return jsonify({
                'success': True,
                'chapters': clean_chapters,
                'title': info.get('title', 'Unknown'),
                'ffmpeg': FFMPEG_AVAILABLE
            })
            
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/split', methods=['POST'])
def split_video():
    try:
        if not FFMPEG_AVAILABLE:
            return jsonify({'error': 'FFmpeg tidak tersedia di server ini. Split tidak bisa dilakukan.'}), 400
        
        data = request.json
        url = data.get('url')
        chapters = data.get('chapters', [])
        
        if not url or not chapters:
            return jsonify({'error': 'Data tidak lengkap'}), 400
        
        # Download dulu
        temp_file = os.path.join(TEMP_FOLDER, 'master_temp')
        ydl_opts = {
            'outtmpl': temp_file + '.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            'format': 'bestaudio/best',
            'ignoreerrors': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        # Cari file yang didownload
        downloaded = None
        for f in os.listdir(TEMP_FOLDER):
            if f.startswith('master_temp') and not f.endswith('.part'):
                downloaded = os.path.join(TEMP_FOLDER, f)
                break
        
        if not downloaded:
            return jsonify({'error': 'Gagal download file'}), 500
        
        # Split chapters
        results = []
        for i, chap in enumerate(chapters[:5]):  # Limit 5 tracks untuk Vercel
            output_file = os.path.join(TEMP_FOLDER, f'track_{i+1:02d}.mp3')
            cmd = ['ffmpeg', '-y', '-ss', str(chap['seconds']), '-i', downloaded]
            
            if i < len(chapters) - 1:
                cmd.extend(['-to', str(chapters[i+1]['seconds'])])
            
            cmd.extend(['-c:a', 'libmp3lame', '-b:a', '192k', '-ar', '44100', output_file])
            
            try:
                subprocess.run(cmd, capture_output=True, timeout=60, check=True)
                results.append({
                    'filename': f'track_{i+1:02d}.mp3',
                    'title': chap['title']
                })
            except Exception as e:
                print(f"❌ Split error: {e}")
        
        # Cleanup
        if os.path.exists(downloaded):
            os.remove(downloaded)
        
        if results:
            return jsonify({
                'success': True,
                'tracks': results,
                'message': f'Berhasil split {len(results)} tracks'
            })
        else:
            return jsonify({'error': 'Gagal split tracks'}), 500
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/combine', methods=['POST'])
def combine():
    try:
        if not FFMPEG_AVAILABLE:
            return jsonify({'error': 'FFmpeg tidak tersedia di server ini. Combine tidak bisa dilakukan.'}), 400
        
        data = request.json
        video_folder = data.get('video_folder')
        audio_folder = data.get('audio_folder')
        channel_name = data.get('channel_name', 'Mix')
        max_audio = data.get('max_audio', 5)
        repeat_times = data.get('repeat_times', 1)
        
        # Karena di Vercel tidak bisa akses folder user, return error
        return jsonify({
            'error': 'Fitur combine tidak tersedia di versi web. Gunakan aplikasi desktop untuk fitur ini.'
        }), 400
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
