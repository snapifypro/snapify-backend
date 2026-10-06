from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp
import requests
import re
import io
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, TIT2, TPE1, ID3NoHeaderError

app = Flask(__name__)
CORS(app)

def clean_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "", name)

@app.route('/get-download-link', methods=['POST'])
def extract_video_info():
    data = request.get_json()
    if not data or 'url' not in data:
        return jsonify({"error": "URL Dena zaroori hai!"}), 400

    video_url = data['url'].strip()

    if "music.youtube.com" in video_url:
        video_url = video_url.replace("music.youtube.com", "www.youtube.com")

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'nocheckcertificate': True,
        'ignoreerrors': True,
        'geo_bypass': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['ios', 'android', 'mweb'],
                'skip': ['webpage', 'configs']
            }
        },
        'user_agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1',
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)

            if not info:
                return jsonify({"error": "Video details extract nahi ho paayi!"}), 400

            title = info.get('title', 'Audio Track')
            channel = info.get('uploader') or info.get('artist') or 'YouTube'
            thumbnail = info.get('thumbnail', '')

            formats = info.get('formats', [])

            best_audio = None
            for f in reversed(formats):
                if f.get('acodec') != 'none' and (f.get('vcodec') == 'none' or not f.get('vcodec')):
                    best_audio = f.get('url')
                    break

            if not best_audio:
                for f in formats:
                    if f.get('acodec') != 'none' and f.get('url'):
                        best_audio = f.get('url')
                        break

            audio_links = []
            if best_audio:
                audio_links = [
                    {"quality": "320 kbps (High Quality)", "url": best_audio},
                    {"quality": "128 kbps (Standard)", "url": best_audio}
                ]

            video_links = []
            seen_heights = set()
            for f in reversed(formats):
                if f.get('ext') == 'mp4' and f.get('url') and f.get('vcodec') != 'none':
                    res = f.get('height')
                    if res in [1080, 720, 360] and res not in seen_heights:
                        seen_heights.add(res)
                        video_links.append({
                            "quality": f"{res}p HD" if res >= 720 else f"{res}p SD",
                            "url": f.get('url')
                        })

            if not video_links:
                direct_url = info.get('url')
                if direct_url:
                    video_links.append({"quality": "720p HD", "url": direct_url})
                    video_links.append({"quality": "360p SD", "url": direct_url})

            return jsonify({
                "title": title,
                "channel": channel,
                "thumbnail": thumbnail,
                "audio_links": audio_links,
                "video_links": video_links
            })

    except Exception as e:
        return jsonify({"error": f"Video fetch nahi ho saka: {str(e)}"}), 500


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
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1'
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