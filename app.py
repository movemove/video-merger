#!/usr/bin/env python3
import os
import uuid
import subprocess
import logging
from flask import Flask, request, send_file, jsonify

# Setup logging
logging.basicConfig(filename='/home/alice/.openclaw/workspace/double_video/access.log', 
                    level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger()

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = '/home/alice/.openclaw/workspace/double_video/uploads'
app.config['OUTPUT_FOLDER'] = '/home/alice/.openclaw/workspace/double_video/outputs'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)

FFMPEG = '/home/linuxbrew/.linuxbrew/bin/ffmpeg'

# Log all requests with details
@app.before_request
def log_request():
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    details = ""
    if request.path == '/merge' and request.method == 'POST':
        details = f" - Files: {list(request.files.keys())} - Form: {dict(request.form)}"
    elif request.path.startswith('/download/'):
        details = f" - FileID: {request.path.split('/')[-1]}"
    logger.info(f"{request.method} {request.path} - IP: {ip}{details} - UA: {request.headers.get('User-Agent', 'N/A')}")

@app.route('/')
def index():
    return send_file('templates/index.html')

@app.route('/merge', methods=['POST'])
def merge():
    count = int(request.form.get('count', 2))
    layout = request.form.get('layout', 'hstack')
    include_audio = request.form.get('includeAudio', 'true') == 'true'
    include_subtitles = request.form.get('includeSubtitles', 'true') == 'true'
    
    video_id = str(uuid.uuid4())
    paths = []
    
    for i in range(1, count + 1):
        video = request.files.get(f'video{i}')
        if not video:
            return jsonify({'success': False, 'error': f'缺少影片 {i}'})
        path = os.path.join(app.config['UPLOAD_FOLDER'], f'{video_id}_{i}.mp4')
        video.save(path)
        paths.append(path)
    
    output_path = os.path.join(app.config['OUTPUT_FOLDER'], f'{video_id}.mp4')
    
    # Build filters - use xstack for complex layouts
    if count == 2:
        if layout == 'vstack':
            filter_str = '[0:v][1:v]vstack=inputs=2[v]'
        else:
            filter_str = '[0:v][1:v]hstack=inputs=2[v]'
    elif count == 3:
        if layout == '3h':
            filter_str = '[0:v][1:v][2:v]hstack=inputs=3[v]'
        elif layout == '3v':
            filter_str = '[0:v][1:v][2:v]vstack=inputs=3[v]'
        elif layout == '1t2b':
            # 上1下2: 全部填滿，無黑色填充
            filter_str = "[0:v]scale=1080:-2[top];[1:v]scale=540:-2[bot1];[2:v]scale=540:-2[bot2];[bot1][bot2]hstack=inputs=2[bot];[top][bot]vstack=inputs=2[v]"
        elif layout == '2t1b':
            # 上2下1: 全部填滿，無黑色填充
            filter_str = "[0:v]scale=540:-2[top1];[1:v]scale=540:-2[top2];[top1][top2]hstack=inputs=2[top];[2:v]scale=1080:-2[bot];[top][bot]vstack=inputs=2[v]"
        else:
            filter_str = '[0:v][1:v][2:v]hstack=inputs=3[v]'
    else:  # 4
        filter_str = '[0:v][1:v]hstack=inputs=2[r1];[2:v][3:v]hstack=inputs=2[r2];[r1][r2]vstack=inputs=2[v]'
    
    # Build ffmpeg command
    cmd = [FFMPEG, '-i', paths[0], '-i', paths[1]]
    if count >= 3: cmd.extend(['-i', paths[2]])
    if count == 4: cmd.extend(['-i', paths[3]])
    
    # Build mapping
    if include_audio:
        # Use first video's audio
        cmd.extend(['-map', '0:v', '-map', '1:a'])
        if count >= 3: cmd.extend(['-map', '2:a'])
        if count == 4: cmd.extend(['-map', '3:a'])
    else:
        cmd.extend(['-map', '[v]', '-an'])
    
    if not include_subtitles:
        cmd.extend(['-s:s', 'mov_text'])
    
    cmd.extend(['-filter_complex', filter_str, '-c:v', 'libx264', '-preset', 'fast', '-crf', '23'])
    
    if not include_audio:
        cmd.append('-c:a')
        cmd.append('aac')
        cmd.append('-b:a')
        cmd.append('128k')
    
    cmd.extend([output_path, '-y'])
    
    result = subprocess.run(cmd, capture_output=True)
    
    for p in paths:
        if os.path.exists(p): os.remove(p)
    
    print(f"layout: {layout}, returncode: {result.returncode}")
    if result.returncode != 0:
        print(f"stderr: {result.stderr.decode()[:500]}")
        return jsonify({'success': False, 'error': result.stderr.decode()[:200]})
    
    return jsonify({'success': True, 'video_id': video_id})

@app.route('/download/<video_id>')
def download(video_id):
    return send_file(os.path.join(app.config['OUTPUT_FOLDER'], f'{video_id}.mp4'), as_attachment=True, download_name='merged_video.mp4')

if __name__ == '__main__':
    print("=" * 50)
    print("🎬 多影片合併（並排）")
    print("https://video.chiangkevin.com")
    print("=" * 50)
    app.run(host='0.0.0.0', port=5001, debug=False)
