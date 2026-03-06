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
        path = os.path.join(app.config['UPLOAD_FOLDER'], f'{video_id}_{i}.mp4')
        video.save(path)
        paths.append(path)
    
    output_path = os.path.join(app.config['OUTPUT_FOLDER'], f'{video_id}.mp4')
    
    # Simple approach - no complex filters, just concatenate video streams
    try:
        # Step 1: Convert each video to standard mp4 first
        print("Converting videos to standard format...")
        converted_paths = []
        for i, p in enumerate(paths):
            converted = os.path.join(app.config['UPLOAD_FOLDER'], f'{video_id}_conv_{i}.mp4')
            cmd = [
                FFMPEG, '-y', '-i', p,
                '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
                '-c:a', 'aac', '-b:a', '128k',
                '-movflags', '+faststart',
                converted
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=60)
            if result.returncode != 0:
                # Try without audio if conversion fails
                cmd = [
                    FFMPEG, '-y', '-i', p,
                    '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
                    '-an', '-movflags', '+faststart',
                    converted
                ]
                result = subprocess.run(cmd, capture_output=True, timeout=60)
            converted_paths.append(converted)
            print(f"Converted {i+1}/{count}")
        
        # Get duration of first video
        result = subprocess.run(
            [FFMPEG, '-i', converted_paths[0], '-f', 'null', '-'],
            capture_output=True, timeout=30
        )
        # Extract duration from stderr
        duration = None
        for line in result.stderr.decode().split('\n'):
            if 'Duration:' in line:
                try:
                    duration = line.split('Duration:')[1].split(',')[0].strip()
                except:
                    pass
        
        print(f"Merging {count} videos, layout={layout}, audio={include_audio}, duration={duration}")
        
        # Build simple ffmpeg command
        cmd = [FFMPEG, '-y']
        
        # Input files
        for p in converted_paths:
            cmd.extend(['-i', p])
        
        # Filter for stacking - scale to same resolution first
        if count == 2:
            if layout == 'vstack':
                filter_str = '[0:v]scale=1080:1920[0s];[1:v]scale=1080:1920[1s];[0s][1s]vstack=shortest=1[v]'
            else:
                filter_str = '[0:v]scale=-2:1080[0s];[1:v]scale=-2:1080[1s];[0s][1s]hstack=shortest=1[v]'
        elif count == 3:
            if layout == '3v':
                filter_str = '[0:v]scale=1080:1920[0s];[1:v]scale=1080:1920[1s];[2:v]scale=1080:1920[2s];[0s][1s][2s]vstack=shortest=1[v]'
            elif layout == '1t2b':
                filter_str = '[0:v]scale=1920:540[0s];[1:v]scale=1920:540[1s];[2:v]scale=1920:540[2s];[0s]pad=1920:540:(ow-iw)/2:0[top];[1s][2s]hstack=shortest=1[bot];[top][bot]vstack=shortest=1[v]'
            elif layout == '2t1b':
                filter_str = '[0:v]scale=1920:540[0s];[1:v]scale=1920:540[1s];[2:v]scale=1920:540[2s];[0s][1s]hstack=shortest=1[top];[2s]pad=1920:540:(ow-iw)/2:0[bot];[top][bot]vstack=shortest=1[v]'
            else:
                filter_str = '[0:v]scale=-2:1080[0s];[1:v]scale=-2:1080[1s];[2:v]scale=-2:1080[2s];[0s][1s][2s]hstack=shortest=1[v]'
        else:
            filter_str = '[0:v]scale=-2:1080[0s];[1:v]scale=-2:1080[1s];[2:v]scale=-2:1080[2s];[3:v]scale=-2:1080[3s];[0s][1s]hstack=shortest=1[top];[2s][3s]hstack=shortest=1[bot];[top][bot]vstack=shortest=1[v]'
        
        cmd.extend(['-filter_complex', filter_str, '-map', '[v]'])
        
        if include_audio:
            cmd.extend(['-map', '0:a', '-c:a', 'aac', '-b:a', '128k'])
        else:
            cmd.extend(['-an'])
        
        cmd.extend(['-c:v', 'libx264', '-preset', 'fast', '-crf', '23', output_path])
        
        print("Running:", ' '.join(cmd[:12]))
        print("Full cmd:", ' '.join(cmd))
        result = subprocess.run(cmd, capture_output=True, timeout=120)
        stderr = result.stderr.decode()
        if result.returncode != 0:
            print("Full FFmpeg error:", stderr[:2000])
        
        for p in converted_paths:
            if os.path.exists(p): os.remove(p)
        
        if result.returncode != 0:
            err = result.stderr.decode()
            print("FFmpeg error:", stderr[:2000] if stderr else err[:500])
            return jsonify({'success': False, 'error': err[:200]})
        
        # Cleanup original files
        for p in paths:
            if os.path.exists(p): os.remove(p)
        
        # Check output file
        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            return jsonify({'success': False, 'error': 'Output file is empty'})
        
        print(f"Success! Output size: {os.path.getsize(output_path)}")
        return jsonify({'success': True, 'video_id': video_id})
        
    except subprocess.TimeoutExpired:
        for p in converted_paths:
            if os.path.exists(p): os.remove(p)
        return jsonify({'success': False, 'error': '處理超時'})
    except Exception as e:
        for p in converted_paths:
            if os.path.exists(p): os.remove(p)
        return jsonify({'success': False, 'error': str(e)})

@app.route('/download/<video_id>')
def download(video_id):
    return send_file(os.path.join(app.config['OUTPUT_FOLDER'], f'{video_id}.mp4'), as_attachment=True, download_name='merged_video.mp4')

if __name__ == '__main__':
    print("=" * 50)
    print("🎬 多影片合併")
    print("https://video.chiangkevin.com")
    print("=" * 50)
    app.run(host='0.0.0.0', port=5001, debug=False)
