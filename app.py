#!/usr/bin/env python3
import os
import uuid
import subprocess
import logging
from flask import Flask, request, send_file, jsonify

logging.basicConfig(filename='/home/alice/.openclaw/workspace/double_video/access.log', 
                    level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger()

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = '/home/alice/.openclaw/workspace/double_video/uploads'
app.config['OUTPUT_FOLDER'] = '/home/alice/.openclaw/workspace/double_video/outputs'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)

FFMPEG = '/home/linuxbrew/.linuxbrew/bin/ffmpeg'

@app.before_request
def log_request():
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    details = ""
    if request.path == '/merge' and request.method == 'POST':
        details = f" - Files: {list(request.files.keys())} - Form: {dict(request.form)}"
    logger.info(f"{request.method} {request.path} - IP: {ip}{details}")

@app.route('/')
def index():
    return send_file('templates/index.html')

@app.route('/merge', methods=['POST'])
def merge():
    count = int(request.form.get('count', 2))
    layout = request.form.get('layout', 'hstack')
    include_audio = request.form.get('includeAudio', 'true') == 'true'
    
    video_id = str(uuid.uuid4())
    paths = []
    
    for i in range(1, count + 1):
        video = request.files.get(f'video{i}')
        if not video:
            return jsonify({'success': False, 'error': f'缺少影片 {i}'})
        ext = os.path.splitext(video.filename)[1] or '.mp4'
        path = os.path.join(app.config['UPLOAD_FOLDER'], f'{video_id}_{i}{ext}')
        video.save(path)
        paths.append(path)
    
    output_path = os.path.join(app.config['OUTPUT_FOLDER'], f'{video_id}.mp4')
    
    try:
        # Convert all videos to same resolution (1920x1080)
        converted = []
        for i, p in enumerate(paths):
            out = os.path.join(app.config['UPLOAD_FOLDER'], f'{video_id}_{i}.mp4')
            cmd = [
                FFMPEG, '-y', '-i', p,
                '-vf', 'scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2',
                '-c:v', 'libx264', '-preset', 'fast', '-crf', '23'
            ]
            if include_audio:
                cmd.extend(['-c:a', 'aac', '-b:a', '128k'])
            else:
                cmd.extend(['-an'])
            cmd.append(out)
            
            print(f"Converting {i+1}...")
            result = subprocess.run(cmd, capture_output=True, timeout=60)
            if result.returncode != 0:
                # Simpler fallback
                cmd = [FFMPEG, '-y', '-i', p, '-c:v', 'libx264', '-preset', 'fast', '-crf', '23']
                if include_audio:
                    cmd.extend(['-c:a', 'aac', '-b:a', '128k'])
                else:
                    cmd.extend(['-an'])
                cmd.append(out)
                result = subprocess.run(cmd, capture_output=True, timeout=60)
            converted.append(out)
        
        # Stack videos (side by side or top/bottom)
        if count == 2:
            if layout == 'vstack':
                filter_str = '[0:v][1:v]vstack=shortest=1[v]'
            else:  # hstack - side by side
                filter_str = '[0:v][1:v]hstack=shortest=1[v]'
        elif count == 3:
            if layout == '3v':
                filter_str = '[0:v][1:v][2:v]vstack=shortest=1[v]'
            else:  # 3h or default
                filter_str = '[0:v][1:v][2:v]hstack=shortest=1[v]'
        else:  # 4
            filter_str = '[0:v][1:v]hstack=inputs=2[top];[2:v][3:v]hstack=inputs=2[bot];[top][bot]vstack=shortest=1[v]'
        
        cmd = [FFMPEG, '-y']
        for p in converted:
            cmd.extend(['-i', p])
        cmd.extend(['-filter_complex', filter_str, '-map', '[v]'])
        if include_audio:
            cmd.extend(['-map', '0:a', '-c:a', 'aac', '-b:a', '128k'])
        else:
            cmd.extend(['-an'])
        cmd.extend(['-c:v', 'libx264', '-preset', 'fast', '-crf', '23', output_path])
        
        print(f"Merging {count} videos with {layout}...")
        result = subprocess.run(cmd, capture_output=True, timeout=120)
        
        # Cleanup
        for p in paths:
            if os.path.exists(p): os.remove(p)
        for p in converted:
            if os.path.exists(p): os.remove(p)
        
        if result.returncode != 0:
            err = result.stderr.decode()
            print("Error:", err[:300])
            return jsonify({'success': False, 'error': err[:200]})
        
        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            return jsonify({'success': False, 'error': 'Output file is empty'})
        
        print(f"Success! {os.path.getsize(output_path)} bytes")
        return jsonify({'success': True, 'video_id': video_id})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/download/<video_id>')
def download(video_id):
    return send_file(os.path.join(app.config['OUTPUT_FOLDER'], f'{video_id}.mp4'), as_attachment=True, download_name='merged_video.mp4')

if __name__ == '__main__':
    print("=" * 50)
    print("多影片合併（並排）")
    print("https://video.chiangkevin.com")
    print("=" * 50)
    app.run(host='0.0.0.0', port=5001, debug=False)
