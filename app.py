from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import requests
import re
import io
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, TIT2, TPE1, ID3NoHeaderError

app = Flask(__name__)
CORS(app)

def clean_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "", name)

def extract_video_id(url):
    # Regex to extract YouTube Video ID
    pattern = r'(?:https?:\/\/)?(?:www\.)?(?:youtube\.com\/(?:watch\?v=|embed\/|v\/|shorts\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})'
    match = re.search(pattern, url)
    if match:
        return match.group(1)
    return None

@app.route('/get-download-link', methods=['POST'])
def extract_video_info():
    data = request.get_json()
    if not data or 'url' not in data:
        return jsonify({"error": "URL Dena zaroori hai!"}), 400

    video_url = data['url'].strip()
    video_id = extract_video_id(video_url)

    if not video_id:
        return jsonify({"error": "Invalid YouTube URL!"}), 400

    # Public Invidious instances list for automatic failover/fallback
    instances = [
        f"https://api.invidious.io/api/v1/videos/{video_id}",
        f"https://invidious.nerdvpn.de/api/v1/videos/{video_id}",
        f"https://inv.tux.pizza/api/v1/videos/{video_id}"
    ]

    res_data = None
    for instance_url in instances:
        try:
            res = requests.get(instance_url, timeout=7)
            if res.status_code == 200:
                res_data = res.json()
                break
        except Exception:
            continue

    if not res_data:
        return jsonify({"error": "Video details fetch nahi ho paayi, kripya dobara try karein!"}), 500

    try:
        title = res_data.get('title', 'Audio Track')
        channel = res_data.get('author', 'YouTube')
        
        # High quality thumbnail
        thumbnails = res_data.get('videoThumbnails', [])
        thumbnail = thumbnails[-1].get('url') if thumbnails else f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"

        audio_links = []
        video_links = []
        
        adaptive_formats = res_data.get('adaptiveFormats', [])
        format_streams = res_data.get('formatStreams', [])

        # Extract Audio Stream
        best_audio_url = None
        for fmt in adaptive_formats:
            if 'audio' in fmt.get('type', ''):
                best_audio_url = fmt.get('url')
                break

        if best_audio_url:
            audio_links = [
                {"quality": "320 kbps (High Quality)", "url": best_audio_url},
                {"quality": "128 kbps (Standard)", "url": best_audio_url}
            ]

        # Extract Video Streams (1080p, 720p, 360p)
        seen_heights = set()
        for fmt in format_streams:
            quality_label = fmt.get('qualityLabel', '')
            url = fmt.get('url')
            if url and quality_label:
                res_num = re.sub(r'\D', '', quality_label)
                if res_num and int(res_num) in [1080, 720, 360] and res_num not in seen_heights:
                    seen_heights.add(res_num)
                    video_links.append({
                        "quality": f"{res_num}p " + ("HD" if int(res_num) >= 720 else "SD"),
                        "url": url
                    })

        return jsonify({
            "title": title,
            "channel": channel,
            "thumbnail": thumbnail,
            "audio_links": audio_links,
            "video_links": video_links
        })

    except Exception as e:
        return jsonify({"error": f"Error parsing video data: {str(e)}"}), 500


@app.route('/download-file', methods=['GET'])
def download_file():
    file_url = request.args.get('url')
    title = request.args.get('title', 'Track')
    artist = request.args.get('artist', 'Artist')
    thumb_url = request.args.get('thumb', '')

    if not file_url:
        return "Missing file URL", 400

    custom_filename = clean_filename(f"{title} - {artist}.mp3")

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        audio_res = requests.get(file_url, headers=headers, stream=True)
        audio_data = io.BytesIO(audio_res.content)

        image_data = None
        if thumb_url:
            try:
                img_res = requests.get(thumb_url, headers=headers)
                if img_res.status_code == 200:
                    image_data = img_res.content
            except Exception:
                pass

        try:
            tags = ID3(audio_data)
        except ID3NoHeaderError:
            tags = ID3()

        tags.add(TIT2(encoding=3, text=title))
        tags.add(TPE1(encoding=3, text=artist))

        if image_data:
            tags.add(
                APIC(
                    encoding=3,
                    mime='image/jpeg',
                    type=3,
                    desc='Cover',
                    data=image_data
                )
            )

        tags.save(audio_data)
        audio_data.seek(0)

        return send_file(
            audio_data,
            mimetype='audio/mpeg',
            as_attachment=True,
            download_name=custom_filename
        )

    except Exception as e:
        return f"Download error: {str(e)}", 500


if __name__ == '__main__':
    app.run()
