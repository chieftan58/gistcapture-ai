from fetch_ferriss_content import fetch_tim_ferriss_content
from email_sender import send_email

items = fetch_tim_ferriss_content()
summary = "\n\n".join(f"[{i['type'].upper()}] {i['title']}\n{i['url']}" for i in items)

send_email("GistCapture AI - Tim Ferriss Weekly Digest", summary)
