# -*- coding: utf-8 -*-
"""
Good News Agent - all news included, no sentiment filter
- Fetches stories from multiple RSS and Atom feeds
- Translates titles + summaries to Hebrew
- Sends HTML digest via Gmail
"""

import os
import logging
import traceback
import datetime
import requests
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import smtplib
import re

# ---------------------- Logging ----------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# ---------------------- CONFIG ----------------------
CONFIG = {
    "summary_max_chars": 280,
    "max_articles": 25,
    "rss_feeds": [
        "https://www.smithsonianmag.com/rss/travel",
        "https://www.smithsonianmag.com/rss/science-nature",
        "https://www.smithsonianmag.com/rss/arts-culture",
        "https://www.smithsonianmag.com/rss/innovation",
        "https://www.optimistdaily.com/feed",
        "https://www.goodnewsnetwork.org/feed/",
        "https://www.thegoodnewsmovement.com/feed/",
        "https://thegoodnewsherald.wordpress.com/feed/",
        "https://feeds-api.dotdashmeredith.com/v1/rss/google/90b927aa-066f-4f66-9162-a018ad8ea366",
        "http://www.shampooandbooze.com/feeds/posts/default?alt=rss",
        "https://www.contemporist.com/feed/",
        "https://www.thetarotlady.com/feed/",
        "https://www.spendwithpennies.com/feed/"
    ]
}
CONFIG["rss_feeds"] = list(dict.fromkeys(CONFIG["rss_feeds"]))  # remove duplicates

# ---------------------- Email ----------------------
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_TO = os.getenv("EMAIL_TO")

if not EMAIL_USER or not EMAIL_PASSWORD or not EMAIL_TO:
    logging.warning("Email credentials not fully set in environment. Email sending may fail.")

# ---------------------- Helpers ----------------------
def clean_html_summary(html_text):
    if not html_text:
        return ""
    text = BeautifulSoup(html_text, "html.parser").get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()

def translate_text(text, target="he"):
    if not text:
        return ""
    try:
        return GoogleTranslator(source='auto', target=target).translate(text)
    except Exception:
        return text

# ---------------------- Fetch RSS ----------------------
def fetch_rss_feed(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        r = requests.get(url, timeout=10, headers=headers)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "xml")
        items = []
        for item in soup.find_all(["item", "entry"]):
            title = item.title.text if item.title else ''
            desc = ''
            if item.find('description'):
                desc = item.description.text
            elif item.find('summary'):
                desc = item.summary.text
            link = ''
            if item.find('link'):
                link_tag = item.find('link')
                link = link_tag['href'] if link_tag.has_attr('href') else link_tag.text
            pub = item.pubDate.text if item.pubDate else (item.updated.text if item.find('updated') else '')
            items.append({'title': title, 'description': desc, 'link': link, 'pubDate': pub})
        return items
    except Exception:
        return []  # silently skip failed feeds

# ---------------------- Build HTML digest ----------------------
def build_html_digest(articles):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    parts = [
        "<!doctype html>",
        "<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<style>body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;background:#f7f7f7;color:#111;direction:rtl;margin:0;padding:20px}.container{max-width:900px;margin:0 auto;background:#fff;padding:28px;border-radius:8px;box-shadow:0 6px 18px rgba(0,0,0,0.08)}header{border-bottom:1px solid #eee;padding-bottom:14px;margin-bottom:18px}h1{font-size:28px;margin:0;text-align:center;color:#222;font-weight:700}.lead{font-size:14px;color:#666;text-align:center;margin-top:6px}.sections{display:grid;grid-template-columns:1fr 320px;grid-gap:20px}.main{padding-right:6px}.aside{background:#fafafa;padding:12px;border-radius:6px;border:1px solid #f0f0f0}.article{margin-bottom:20px;padding-bottom:12px;border-bottom:1px solid #eee}.title{font-size:18px;color:#0b3d91;margin:0 0 6px 0;font-weight:700}.meta{font-size:12px;color:#777;margin-bottom:6px}.summary{font-size:14px;color:#222;line-height:1.6;text-align:justify}a{color:#0b3d91;text-decoration:none;border-bottom:1px dotted rgba(11,61,145,0.15)}a:hover{text-decoration:underline}footer{margin-top:20px;padding-top:12px;border-top:1px solid #eee;font-size:12px;color:#666;text-align:center}@media(max-width:720px){.sections{grid-template-columns:1fr}.aside{order:2}}</style>",
        f"</head><body><div class='container'><header><h1>Good News Digest</h1><div class='lead'>עדכון — {now} | חדשות טובות מהעולם בתרגום לעברית</div></header>",
        "<div class='sections'><div class='main'>"
    ]
    if not articles:
        parts.append("<p>לא נמצאו ידיעות בזמן החיפוש. נסי להריץ שוב מאוחר יותר או הרחיבי את מקורות ה-RSS.</p>")
    else:
        for a in articles:
            title_he = translate_text(a.get("title", ""))
            summary_he = translate_text(a.get("description", "")[:CONFIG["summary_max_chars"]])
            link = a.get("link", "#")
            pub = a.get("pubDate", "")
            parts.append("<div class='article'>")
            parts.append(f"<div class='title'><a href='{link}' target='_blank'>{title_he}</a></div>")
            if pub:
                parts.append(f"<div class='meta'>{pub}</div>")
            if summary_he:
                parts.append(f"<div class='summary'>{summary_he}</div>")
            parts.append("</div>")
    parts.append("</div><aside class='aside'><h3 style='margin-top:0'>סקירה מהירה</h3>")
    parts.append(f"<p>מספר ידיעות שנאספו: {len(articles)}</p>")
    parts.append("</aside></div><footer><div>נוצר על-ידי Good News Agent — מייל יומי עם חדשות טובות</div></footer></div></body></html>")
    return "\n".join(parts)

# ---------------------- Send Email ----------------------
def send_email(html):
    if not (EMAIL_USER and EMAIL_PASSWORD and EMAIL_TO):
        logging.info("Email credentials not set; skipping email send.")
        return False
    try:
        msg = MIMEMultipart()
        msg["From"] = EMAIL_USER
        msg["To"] = EMAIL_TO
        msg["Subject"] = "Good News Digest"
        msg.attach(MIMEText("מצורף דוח החדשות הטובות להיום (לינקים ותקצירים).", "plain", "utf-8"))
        attachment = MIMEApplication(html.encode("utf-8"), _subtype="html")
        attachment.add_header("Content-Disposition", "attachment", filename="good_news_digest.html")
        msg.attach(attachment)
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASSWORD)
            server.send_message(msg)
        logging.info("Email sent to %s", EMAIL_TO)
        return True
    except Exception as e:
        logging.error("Failed to send email: %s", e)
        return False

# ---------------------- Main ----------------------
def run():
    logging.info("Good News Agent starting")
    collected = []
    try:
        for url in CONFIG["rss_feeds"]:
            items = fetch_rss_feed(url)
            if not items:
                continue
            for it in items:
                collected.append(it)
                if len(collected) >= CONFIG["max_articles"]:
                    break
            if len(collected) >= CONFIG["max_articles"]:
                break
        html = build_html_digest(collected)
        with open("good_news_digest.html", "w", encoding="utf-8") as f:
            f.write(html)
        send_email(html)
    except Exception as e:
        logging.error("Unhandled exception: %s", e)
        logging.debug(traceback.format_exc())
        err_html = f"<html><body><h3>Good News Agent - Error</h3><pre>{str(e)}\n\n{traceback.format_exc()}</pre></body></html>"
        with open("good_news_digest_error.html", "w", encoding="utf-8") as f:
            f.write(err_html)
        if EMAIL_USER and EMAIL_PASSWORD and EMAIL_TO:
            try:
                send_email(err_html)
            except Exception:
                logging.debug("Failed to send error email")
    logging.info("Good News Agent finished")

if __name__ == "__main__":
    run()
