import os
import requests
import json
import markdown2
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify

app = Flask(__name__)

# --- 安全验证：确保只有你的GitHub Action能调用这个服务 ---
SECRET_TOKEN = os.environ.get("SECRET_TOKEN")

@app.route('/sync', methods=['POST'])
def sync_to_wechat():
    # 1. 安全令牌验证
    auth_header = request.headers.get('Authorization')
    if not auth_header or auth_header != f"Bearer {SECRET_TOKEN}":
        return jsonify({"error": "Unauthorized"}), 401

    # 2. 从GitHub Action接收数据
    data = request.json
    app_id = data.get("app_id")
    app_secret = data.get("app_secret")
    thumb_media_id = data.get("thumb_media_id")
    issue_title = data.get("issue_title")
    issue_body_md = data.get("issue_body")

    if not all([app_id, app_secret, thumb_media_id, issue_title, issue_body_md]):
        return jsonify({"error": "Missing required data"}), 400

    # --- 3. 调用微信API ---
    try:
        # 3.1 获取 Access Token
        token_url = f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={app_id}&secret={app_secret}"
        token_res = requests.get(token_url).json()
        if "access_token" not in token_res:
            return jsonify({"error": "Failed to get access_token", "details": token_res}), 500
        access_token = token_res["access_token"]

        # 3.2 处理Markdown和图片
        html_body = markdown2.markdown(issue_body_md, extras=["fenced-code-blocks", "tables", "cuddled-lists"])
        soup = BeautifulSoup(html_body, "html.parser")

        for img in soup.find_all("img"):
            img_url = img.get("src")
            if not img_url: continue
            try:
                img_response = requests.get(img_url)
                img_response.raise_for_status()
                files = {"media": ("image.jpg", img_response.content)}
                upload_url = f"https://api.weixin.qq.com/cgi-bin/media/uploadimg?access_token={access_token}"
                upload_res = requests.post(upload_url, files=files).json()
                if "url" in upload_res:
                    img["src"] = upload_res["url"]
            except Exception as e:
                print(f"Image processing failed for {img_url}: {e}") # 打印日志，但不中断流程

        final_html_content = str(soup)

        # 3.3 构造并上传图文素材到草稿箱
        article = {
            "title": issue_title,
            "author": "未来传媒",
            "content": final_html_content,
            "thumb_media_id": thumb_media_id,
            "show_cover_pic": 1
        }
        upload_article_url = f"https://api.weixin.qq.com/cgi-bin/draft/add?access_token={access_token}"
        payload = {"articles": [article]}
        upload_article_res = requests.post(upload_article_url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8")).json()

        if "media_id" in upload_article_res:
            return jsonify({"status": "success", "media_id": upload_article_res["media_id"]}), 200
        else:
            return jsonify({"error": "Failed to upload article to drafts", "details": upload_article_res}), 500

    except Exception as e:
        return jsonify({"error": "An unexpected error occurred", "details": str(e)}), 500

if __name__ == '__main__':
    # This part is for local testing, Render will use gunicorn
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
