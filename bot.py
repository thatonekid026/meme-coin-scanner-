import os, time, json, re, sqlite3, logging
from datetime import datetime, timezone
import requests
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

DB_PATH = os.getenv("DB_PATH", "signals.db")
X_BEARER = os.getenv("X_BEARER_TOKEN", "")
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "90"))
MIN_SCORE = int(os.getenv("MIN_ALERT_SCORE", "65"))
MAX_RESULTS = int(os.getenv("MAX_RESULTS", "25"))

DEFAULT_QUERIES = [
    '"meme coin" OR memecoin OR "fair launch" OR pumpfun lang:en -is:reply',
    'Solana meme OR memecoin OR "new token" lang:en -is:reply',
    '("$" OR ticker) (listing OR launch OR viral OR meme) crypto lang:en -is:reply',
    '("contract address" OR CA) memecoin lang:en -is:reply'
]
QUERIES = [q.strip() for q in os.getenv("X_QUERIES", "").split("||") if q.strip()] or DEFAULT_QUERIES

TOKEN_RE = re.compile(r'(?<![A-Za-z0-9])\$[A-Z0-9]{2,12}\b')
CA_RE = re.compile(r'\b[1-9A-HJ-NP-Za-km-z]{32,44}\b')

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS seen (
        post_id TEXT PRIMARY KEY, created_at TEXT, score INTEGER, text TEXT, url TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, post_id TEXT,
        score INTEGER, category TEXT, summary TEXT, text TEXT, url TEXT
    )""")
    conn.commit()
    return conn

def fetch_posts(query):
    if not X_BEARER:
        raise RuntimeError("Set X_BEARER_TOKEN in .env")
    url = "https://api.x.com/2/tweets/search/recent"
    params = {
        "query": query,
        "max_results": min(max(MAX_RESULTS, 10), 100),
        "tweet.fields": "created_at,public_metrics,author_id,lang",
        "expansions": "author_id",
        "user.fields": "username,verified"
    }
    r = requests.get(url, params=params, headers={"Authorization": f"Bearer {X_BEARER}"}, timeout=25)
    if r.status_code == 429:
        logging.warning("X API rate limited; backing off.")
        return []
    r.raise_for_status()
    data = r.json()
    users = {u["id"]: u for u in data.get("includes", {}).get("users", [])}
    out = []
    for p in data.get("data", []):
        p["user"] = users.get(p.get("author_id"), {})
        out.append(p)
    return out

def heuristic_analysis(post):
    text = post.get("text", "")
    metrics = post.get("public_metrics", {}) or {}
    author = post.get("user", {})
    likes = int(metrics.get("like_count", 0))
    reposts = int(metrics.get("retweet_count", 0))
    replies = int(metrics.get("reply_count", 0))
    verified = bool(author.get("verified"))
    score = 0
    score += 18 if verified else 5
    score += min(20, int((likes + reposts*2 + replies) / 15))
    score += 15 if any(k in text.lower() for k in ["launch", "listing", "viral", "breaking", "official", "partnership", "airdrop"]) else 0
    score += 10 if any(k in text.lower() for k in ["memecoin", "meme coin", "pump.fun", "solana", "token"]) else 0
    score += 8 if TOKEN_RE.findall(text) else 0
    score -= 15 if any(k in text.lower() for k in ["100x", "guaranteed", "send it", "easy money", "pump group"]) else 0
    score = max(0, min(100, score))
    category = "Potential narrative / catalyst"
    summary = text[:500].replace("\n", " ")
    flags = []
    if "guaranteed" in text.lower() or "100x" in text.lower():
        flags.append("Promotional language")
    if CA_RE.findall(text):
        flags.append("Possible contract address detected — independently verify")
    return {"score": score, "category": category, "summary": summary, "flags": flags}

def ai_analyze(post):
    if not OPENAI_KEY:
        return heuristic_analysis(post)
    prompt = f"""Analyze this public X post for an informational meme-coin news alert.
Do not recommend buying/selling. Identify factual catalyst vs hype, novelty, credibility,
potential manipulation, and risk. Return JSON only with keys score (0-100),
category, summary (max 2 sentences), flags (array), ticker_mentions (array).
Score for news value and reliability, not predicted returns.
Post: {post.get('text','')}
Author: @{post.get('user',{}).get('username','unknown')} verified={post.get('user',{}).get('verified',False)}
Metrics: {json.dumps(post.get('public_metrics',{}))}"""
    try:
        r = requests.post("https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type":"application/json"},
            json={"model": os.getenv("OPENAI_MODEL", "gpt-6-luna"), "input": prompt},
            timeout=35)
        r.raise_for_status()
        payload = r.json()
        content = ""
        for item in payload.get("output", []):
            for c in item.get("content", []):
                if c.get("type") == "output_text":
                    content += c.get("text", "")
        content = content.strip().removeprefix("```json").removesuffix("```").strip()
        parsed = json.loads(content)
        return parsed
    except Exception as e:
        logging.warning("AI analysis failed; heuristic fallback: %s", e)
        return heuristic_analysis(post)

def make_url(post):
    username = post.get("user", {}).get("username", "i")
    return f"https://x.com/{username}/status/{post['id']}"

def send_telegram(message):
    if not TG_TOKEN or not TG_CHAT:
        logging.info("Telegram not configured. Alert:\n%s", message)
        return
    r = requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        json={"chat_id": TG_CHAT, "text": message, "disable_web_page_preview": False},
        timeout=20)
    r.raise_for_status()

def format_alert(post, analysis):
    score = int(analysis.get("score", 0))
    text = post.get("text", "").replace("<", "&lt;").replace(">", "&gt;")
    tickers = TOKEN_RE.findall(text)
    cas = CA_RE.findall(text)
    flags = analysis.get("flags", [])
    flagtext = "\n".join(f"⚠️ {f}" for f in flags[:3]) or "No automated risk flags"
    return (f"🚨 MEME-COIN NEWS SIGNAL — {score}/100\n"
            f"Category: {analysis.get('category','Uncategorized')}\n"
            f"Summary: {analysis.get('summary', text[:350])}\n"
            f"Ticker mentions: {', '.join(tickers) if tickers else 'None detected'}\n"
            f"Possible contract(s): {', '.join(cas[:2]) if cas else 'None detected'}\n"
            f"{flagtext}\n\n"
            f"Source: @{post.get('user',{}).get('username','unknown')}\n"
            f"Post: {make_url(post)}\n\n"
            f"Original: {text[:700]}")

def main():
    conn = db()
    logging.info("Scanner starting. Poll=%ss, minimum alert score=%s", POLL_SECONDS, MIN_SCORE)
    while True:
        try:
            for query in QUERIES:
                for post in fetch_posts(query):
                    post_id = post["id"]
                    if conn.execute("SELECT 1 FROM seen WHERE post_id=?", (post_id,)).fetchone():
                        continue
                    analysis = ai_analyze(post)
                    score = int(analysis.get("score", 0))
                    url = make_url(post)
                    conn.execute("INSERT OR IGNORE INTO seen VALUES(?,?,?,?,?)",
                        (post_id, post.get("created_at"), score, post.get("text",""), url))
                    conn.execute("INSERT INTO signals(timestamp,post_id,score,category,summary,text,url) VALUES(?,?,?,?,?,?,?)",
                        (datetime.now(timezone.utc).isoformat(), post_id, score,
                         analysis.get("category",""), analysis.get("summary",""),
                         post.get("text",""), url))
                    conn.commit()
                    if score >= MIN_SCORE:
                        send_telegram(format_alert(post, analysis))
                        logging.info("Alert sent score=%s post=%s", score, post_id)
            time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            logging.info("Stopped.")
            break
        except Exception:
            logging.exception("Loop error; retrying in 30 seconds")
            time.sleep(30)
    conn.close()

if __name__ == "__main__":
    main()
