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

app = Flask(__name__)
app.secret_key = 'alfonso-studio-secret-key'

# ========================================================
# KONFIGURASI UNTUK RAILWAY
# ========================================================

# Railway bisa akses /tmp
TEMP_FOLDER = '/tmp' if os.path.exists('/tmp') else tempfile.mkdtemp()
app.config['TEMP_FOLDER'] = TEMP_FOLDER

# Cek FFmpeg (di Railway pasti AVAILABLE ✅)
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

print(f"📁 TEMP Folder: {TEMP_FOLDER}")
print(f"🎬 FFmpeg: {'AVAILABLE' if FFMPEG_AVAILABLE else 'NOT AVAILABLE'}")

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
                    'preferredquality': '320'
                }]
            })
        else:
            ydl_opts.update({
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
            })
        
        print(f"📥 Downloading: {url[:50]}...")
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            base_filename = ydl.prepare_filename(info)
            filename = base_filename
            
            if format_type == 'mp3':
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
        for i, chap in enumerate(chapters):
            output_file = os.path.join(TEMP_FOLDER, f'track_{i+1:02d}.mp3')
            cmd = ['ffmpeg', '-y', '-ss', str(chap['seconds']), '-i', downloaded]
            
            if i < len(chapters) - 1:
                cmd.extend(['-to', str(chapters[i+1]['seconds'])])
            
            cmd.extend(['-c:a', 'libmp3lame', '-b:a', '320k', '-ar', '48000', output_file])
            
            try:
                subprocess.run(cmd, capture_output=True, timeout=120, check=True)
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
        
        # Cari file video
        video_files = []
        audio_files = []
        
        # Karena di Railway, kita pakai folder yang sudah ada
        # Untuk demo, kita akan cari di folder yang disediakan user
        if os.path.exists(video_folder):
            for f in os.listdir(video_folder):
                if f.lower().endswith(('.mp4', '.mkv', '.avi', '.mov', '.webm')):
                    video_files.append(os.path.join(video_folder, f))
        
        if os.path.exists(audio_folder):
            for f in os.listdir(audio_folder):
                if f.lower().endswith(('.mp3', '.wav', '.m4a', '.flac', '.aac')):
                    audio_files.append(os.path.join(audio_folder, f))
        
        if not video_files or not audio_files:
            return jsonify({'error': 'Folder tidak valid atau kosong'}), 400
        
        # Proses combine
        results = []
        for vid in video_files[:3]:  # Limit 3 untuk demo
            selected_audios = random.sample(audio_files, min(max_audio, len(audio_files)))
            
            # Gabung audio
            combined = os.path.join(TEMP_FOLDER, f'combined_{datetime.now().strftime("%Y%m%d_%H%M%S")}.mp3')
            list_file = os.path.join(TEMP_FOLDER, 'list.txt')
            
            with open(list_file, 'w') as f:
                for a in selected_audios:
                    f.write(f"file '{a}'\n")
            
            subprocess.run(['ffmpeg', '-f', 'concat', '-safe', '0', '-i', list_file, '-c', 'copy', combined, '-y'],
                          capture_output=True, timeout=120)
            
            # Merge video + audio
            output = os.path.join(TEMP_FOLDER, f'{channel_name}_{os.path.basename(vid)}')
            cmd = ['ffmpeg', '-stream_loop', str(repeat_times), '-i', vid, '-i', combined,
                   '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'copy',
                   '-shortest', output, '-y']
            subprocess.run(cmd, capture_output=True, timeout=300)
            
            if os.path.exists(output):
                results.append({
                    'filename': os.path.basename(output),
                    'size': os.path.getsize(output) / (1024 * 1024)
                })
            
            os.remove(list_file)
            os.remove(combined)
        
        return jsonify({
            'success': True,
            'results': results,
            'message': f'Berhasil memproses {len(results)} video'
        })
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/download_file/<filename>')
def download_file(filename):
    try:
        filepath = os.path.join(TEMP_FOLDER, filename)
        if os.path.exists(filepath):
            return send_file(filepath, as_attachment=True)
        return jsonify({'error': 'File not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
