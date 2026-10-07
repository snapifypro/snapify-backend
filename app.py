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

    # Multiple active public instances (Invidious + Piped API)
    api_urls = [
        f"https://pipedapi.kavin.rocks/streams/{video_id}",
        f"https://api.piped.privacydev.net/streams/{video_id}",
        f"https://api.invidious.io/api/v1/videos/{video_id}",
        f"https://inv.tux.pizza/api/v1/videos/{video_id}"
    ]

    res_data = None
    used_engine = None

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }

    for endpoint in api_urls:
        try:
            res = requests.get(endpoint, headers=headers, timeout=5)
            if res.status_code == 200:
                res_data = res.json()
                used_engine = "piped" if "piped" in endpoint else "invidious"
                break
        except Exception:
            continue

    if not res_data:
        return jsonify({"error": "Video details fetch nahi ho paayi, kripya dobara try karein!"}), 500

    try:
        title = res_data.get('title', 'Audio Track')
        
        if used_engine == "piped":
            channel = res_data.get('uploader', 'YouTube')
            thumbnail = res_data.get('thumbnailUrl', f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg")
            
            audio_links = []
            video_links = []

            # Audio Streams
            audio_streams = res_data.get('audioStreams', [])
            if audio_streams:
                best_audio = audio_streams[0].get('url')
                audio_links = [
                    {"quality": "320 kbps (High Quality)", "url": best_audio},
                    {"quality": "128 kbps (Standard)", "url": best_audio}
                ]

            # Video Streams
            seen_heights = set()
            for v in res_data.get('videoStreams', []):
                quality = v.get('quality', '')
                url = v.get('url')
                if url and quality and 'p' in quality:
                    height = int(re.sub(r'\D', '', quality) or 0)
                    if height in [1080, 720, 360] and height not in seen_heights:
                        seen_heights.add(height)
                        video_links.append({
                            "quality": f"{height}p " + ("HD" if height >= 720 else "SD"),
                            "url": url
                        })

        else:  # Invidious Parse
            channel = res_data.get('author', 'YouTube')
            thumbnails = res_data.get('videoThumbnails', [])
            thumbnail = thumbnails[-1].get('url') if thumbnails else f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"

            audio_links = []
            video_links = []

            for fmt in res_data.get('adaptiveFormats', []):
                if 'audio' in fmt.get('type', ''):
                    audio_links = [
                        {"quality": "320 kbps (High Quality)", "url": fmt.get('url')},
                        {"quality": "128 kbps (Standard)", "url": fmt.get('url')}
                    ]
                    break

            for fmt in res_data.get('formatStreams', []):
                q = fmt.get('qualityLabel', '')
                if q:
                    height = int(re.sub(r'\D', '', q) or 0)
                    if height in [1080, 720, 360]:
                        video_links.append({
                            "quality": f"{height}p " + ("HD" if height >= 720 else "SD"),
                            "url": fmt.get('url')
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
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
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
