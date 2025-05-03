from flask import Flask, request, jsonify, session
from flask_cors import CORS
from flask_socketio import SocketIO
import wikipedia
import requests
from duckduckgo_search import DDGS
import re
from textwrap import wrap
import html
import json
import os
from datetime import datetime
from flask_caching import Cache
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_compress import Compress

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.urandom(24)  # Set a secret key for session management

# Add caching configuration
cache = Cache(app, config={
    'CACHE_TYPE': 'simple',
    'CACHE_DEFAULT_TIMEOUT': 300  # Cache for 5 minutes
})

# Apply CORS with optimized settings
CORS(app, resources={
    r"/": {
        "origins": "*",
        "methods": ["POST", "OPTIONS"],
        "allow_headers": ["Content-Type"],
        "max_age": 3600  # Cache preflight requests for 1 hour
    },
    r"/ask": {
        "origins": "*",
        "methods": ["POST", "OPTIONS"],
        "allow_headers": ["Content-Type"],
        "max_age": 3600
    },
    r"/suggest": {
        "origins": "*",
        "methods": ["POST", "OPTIONS"],
        "allow_headers": ["Content-Type"],
        "max_age": 3600
    },
    r"/*": {
        "origins": "*"
    }
}, supports_credentials=True)

# Setup SocketIO with optimized settings
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet', ping_timeout=60)

# Add rate limiting
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

# Active user counter with optimized storage
active_users = 9
user_sessions = {}

@socketio.on('connect')
def handle_connect():
    global active_users
    active_users += 1
    user_sessions[request.sid] = datetime.now()
    socketio.emit('active_users', active_users)

@socketio.on('disconnect')
def handle_disconnect():
    global active_users
    active_users -= 1
    if request.sid in user_sessions:
        del user_sessions[request.sid]
    socketio.emit('active_users', active_users)

# Add response compression
Compress(app)

# Global dictionary to store search history if session isn't available
user_history = {}

# ========== HELPER FUNCTIONS ==========
def format_text(text, max_line_length=500):
    """Enhanced text formatting with styling and emojis."""
    cache_key = f"format_{hash(text)}"
    cached_result = cache.get(cache_key)
    if cached_result:
        return cached_result

    # Extended emoji map for different types of content
    emoji_map = {
        # Basic indicators
        "important": "❗",
        "note": "📝",
        "info": "ℹ️",
        "warning": "⚠️",
        "success": "✅",
        "error": "❌",
        "question": "❓",
        "answer": "💡",
        "link": "🔗",
        
        # Time and date
        "time": "⏰",
        "date": "📅",
        "schedule": "📆",
        "deadline": "⏳",
        "reminder": "🔔",
        
        # Location and travel
        "location": "📍",
        "map": "🗺️",
        "travel": "✈️",
        "direction": "🧭",
        "destination": "🎯",
        
        # People and communication
        "person": "👤",
        "organization": "🏢",
        "team": "👥",
        "message": "💬",
        "email": "📧",
        "phone": "📱",
        "contact": "📞",
        
        # Events and activities
        "event": "🎉",
        "meeting": "🤝",
        "party": "🎊",
        "celebration": "🎈",
        "activity": "🎯",
        
        # Ideas and concepts
        "idea": "💭",
        "thought": "🤔",
        "concept": "💡",
        "plan": "📋",
        "strategy": "🎯",
        
        # Information and knowledge
        "fact": "📚",
        "knowledge": "🧠",
        "learning": "📖",
        "education": "🎓",
        "research": "🔬",
        
        # Tips and advice
        "tip": "💡",
        "advice": "💭",
        "suggestion": "💡",
        "recommendation": "👍",
        "hint": "💡",
        
        # Examples and samples
        "example": "📋",
        "sample": "📄",
        "template": "📑",
        "pattern": "📊",
        "model": "📐",
        
        # Summary and overview
        "summary": "📌",
        "overview": "📋",
        "review": "📝",
        "analysis": "📊",
        "report": "📑",
        
        # Status and progress
        "status": "📊",
        "progress": "📈",
        "complete": "✅",
        "pending": "⏳",
        "in progress": "🔄",
        
        # Categories and types
        "category": "📑",
        "type": "🏷️",
        "label": "🏷️",
        "tag": "🏷️",
        "group": "📦",
        
        # Actions and operations
        "action": "⚡",
        "operation": "⚙️",
        "process": "🔄",
        "function": "⚡",
        "task": "📋"
    }

    # Add styling to text
    text = html.escape(text)
    
    # Format headings with emojis
    text = re.sub(r'^(#+)\s+(.+)$', lambda m: f'<h{len(m.group(1))}>📌 {m.group(2)}</h{len(m.group(1))}>', text, flags=re.MULTILINE)
    
    # Format bold and italic with enhanced styling
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>💪 \1</b>', text)  # Bold with strength emoji
    text = re.sub(r'\*(.+?)\*', r'<i>✨ \1</i>', text)  # Italic with sparkle emoji
    
    # Format lists with bullet points
    text = re.sub(r'^\s*[-•]\s+(.+)$', r'<li>• \1</li>', text, flags=re.MULTILINE)
    
    # Format numbered lists
    text = re.sub(r'^\s*(\d+)\.\s+(.+)$', r'<li>🔢 \1. \2</li>', text, flags=re.MULTILINE)
    
    # Add emojis based on content
    for keyword, emoji in emoji_map.items():
        if keyword in text.lower():
            text = text.replace(keyword, f"{emoji} {keyword}")
    
    # Format paragraphs with enhanced styling
    paragraphs = text.split('\n')
    formatted_paragraphs = []
    for p in paragraphs:
        if p.strip():
            if p.startswith('<h') or p.startswith('<li'):
                formatted_paragraphs.append(p)
            else:
                # Add different paragraph styles based on content
                if '?' in p:
                    formatted_paragraphs.append(f'<p>❓ {p}</p>')  # Questions
                elif '!' in p:
                    formatted_paragraphs.append(f'<p>❗ {p}</p>')  # Exclamations
                elif len(p) > 100:
                    formatted_paragraphs.append(f'<p>📝 {p}</p>')  # Long paragraphs
                else:
                    formatted_paragraphs.append(f'<p>💭 {p}</p>')  # Regular paragraphs
    
    result = '\n'.join(formatted_paragraphs)
    
    # Add special formatting for specific patterns
    result = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', 
                   lambda m: f'<a href="{m.group(0)}" target="_blank">🔗 {m.group(0)}</a>', result)
    
    # Add emphasis to important numbers
    result = re.sub(r'\b(\d+)\b', r'<b>\1</b>', result)
    
    cache.set(cache_key, result)
    return result

def generate_summary(text):
    """Generate a concise summary of the given text using Gemini."""
    try:
        prompt = f"Please provide a concise 10-12 sentence summary of the following text:\n\n{text[:3000]}\n\nSummary:"
        response = query_gemini(prompt, use_history=False)
        return response.replace("🔮 NAF AI Response:\n\n", "")
    except Exception:
        return text[:1000] + "..." if len(text) > 1000 else text

def format_wikipedia_content(content):
    """Enhanced Wikipedia content formatting."""
    paragraphs = content.split('\n\n')
    main_content = []
    char_count = 0
    max_chars = 10000

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        para_length = len(para)
        if char_count + para_length <= max_chars:
            # Add styling to paragraphs
            if para.startswith('='):  # Headings
                level = len(re.match(r'^=+', para).group())
                text = para.strip('=')
                main_content.append(f"<h{level}>📚 {text}</h{level}>")
            else:
                main_content.append(f"<p>📝 {para}</p>")
            char_count += para_length
        else:
            break

    formatted_content = '\n'.join(main_content)
    
    if len(formatted_content) >= max_chars:
        formatted_content += "\n\n⚠️ <i>Content truncated</i>"

    return format_text(formatted_content)

def format_search_results(results):
    """Enhanced search results formatting with better styling."""
    if not results:
        return "❌ No results found."
    
    formatted = []
    for i, result in enumerate(results[:5], 1):
        title = result.get('title', 'No title')
        body = result.get('body', 'No description')
        url = result.get('href', '#')
        
        formatted.append(
            f"<div class='search-result'>"
            f"<h3>🔍 {i}. <a href='{html.escape(url)}' target='_blank'>{html.escape(title)}</a></h3>"
            f"<p><i>{html.escape(body)}</i></p>"
            f"<p><small>🔗 <a href='{html.escape(url)}' target='_blank'>Read more</a></small></p>"
            f"</div>"
        )

    return ''.join(formatted)

def get_user_session_id():
    """Get a unique user session ID"""
    if 'user_id' not in session:
        session['user_id'] = str(os.urandom(16).hex())
    return session['user_id']

def get_user_history(user_id):
    """Get user's search history"""
    if user_id not in user_history:
        user_history[user_id] = {
            'search_history': [],
            'gemini_history': []
        }
    return user_history[user_id]

def add_to_search_history(user_id, query, response, source):
    """Add a query to the user's search history"""
    history = get_user_history(user_id)
    history['search_history'].append({
        'query': query,
        'response': response,
        'source': source,
        'timestamp': datetime.now().isoformat()
    })
    # Keep only the most recent 10 searches
    if len(history['search_history']) > 50:
        history['search_history'] = history['search_history'][-50:]

def add_to_gemini_history(user_id, query, response):
    """Add a conversation to the Gemini history"""
    history = get_user_history(user_id)
    history['gemini_history'].append({
        'user': query,
        'assistant': response.replace("🔮 NAF AI Response:\n\n", "")
    })
    # Keep only the most recent 5 exchanges for context
    if len(history['gemini_history']) > 7:
        history['gemini_history'] = history['gemini_history'][-7:]

def get_related_history(user_id, query):
    """Get relevant history entries based on similarity to current query"""
    history = get_user_history(user_id)
    related = []
    
    # Simple keyword matching for now (could be improved with embedding similarity)
    query_words = set(query.lower().split())
    
    for entry in history['search_history']:
        hist_words = set(entry['query'].lower().split())
        # Check if there are any matching keywords
        if query_words.intersection(hist_words):
            related.append(entry)
    
    # Return the 3 most recent related entries
    return related[-7:] if related else []

# ========== API INTEGRATIONS ==========
def query_gemini(prompt, use_history=True, user_id=None):
    try:
        api_key = "AIzaSyDfSvbxY1kVrlxYOz43ZBE-oyBmQu2RqXA"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
        
        # Build context from conversation history if available and requested
        context = []
        if use_history and user_id:
            history = get_user_history(user_id)
            for exchange in history['gemini_history']:
                context.append(f"Human: {exchange['user']}")
                context.append(f"Assistant: {exchange['assistant']}")
        
        full_prompt = ("Context:\n" + "\n".join(context) + "\n\nQuestion: " + prompt) if context else prompt
        
        response = requests.post(
            url,
            json={
                "contents": [{
                    "parts": [{"text": full_prompt}]
                }]
            },
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        response.raise_for_status()
        result = response.json()
        
        if "candidates" in result and result["candidates"]:
            response_text = result['candidates'][0]['content']['parts'][0]['text']
            formatted_response = f"🔮 NAF AI Response:\n\n{format_text(response_text)}"
            
            # Add to history if using history
            if use_history and user_id:
                add_to_gemini_history(user_id, prompt, formatted_response)
                
            return formatted_response
        return "❌ NAF couldn't generate a response."
    except Exception as e:
        return f"⚠️ NAF error: {str(e)}"

def query_wolfram(query, user_id=None):
    try:
        app_id = "A2J4RE-Q82P4TTV5A"
        url = f"https://api.wolframalpha.com/v1/result?i={requests.utils.quote(query)}&appid={app_id}"
        response = requests.get(url)
        result = f"🧮 NAF Answer:\n\n{format_text(response.text)}" if response.status_code == 200 else "❌ NAF couldn't solve this."
        
        # Add to search history
        if user_id:
            add_to_search_history(user_id, query, result, "wolfram")
            
        return result
    except Exception as e:
        return f"⚠️ NAF Math error: {str(e)}"

def search_wikipedia(query, user_id=None):
    try:
        wikipedia.set_lang("en")
        search_results = wikipedia.search(query)
        if not search_results:
            return "❌ Nothing found for this topic."
            
        page = wikipedia.page(search_results[0])
        formatted_content = format_wikipedia_content(page.content)
        summary = generate_summary(formatted_content)
        
        response = (
            f"📚 NAF: {page.title}\n\n"
            f"🔍 Summary:\n{summary}\n\n"
            f"📖 Full Information:\n{formatted_content}\n\n"
            f"Read more: {page.url}"
        )
        
        # Add to search history
        if user_id:
            add_to_search_history(user_id, query, response, "wikipedia")
            
        return response
    except wikipedia.exceptions.DisambiguationError as e:
        options = '\n'.join([f"• {opt}" for opt in e.options[:10]])
        return f"🔍 Multiple options found:\n\n{options}\n\nPlease refine your query."
    except Exception as e:
        return f"⚠️ NAF error: {str(e)}"

def search_duckduckgo(query, user_id=None):
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=10))
            if not results:
                return "🔍 No search results found for your query."
                
            # Generate summary from the first 3 results
            combined_content = "\n".join([
                f"{res.get('title', '')}: {res.get('body', '')}"
                for res in results[:10]
            ])
            summary = generate_summary(combined_content)
            
            formatted_results = []
            for i, result in enumerate(results, 1):
                title = result.get('title', 'Untitled')
                url = result.get('href', '#')
                snippet = result.get('body', 'No description available.')
                snippet = snippet.replace('\n', ' ').strip()
                if len(snippet) > 400:
                    snippet = snippet[:400] + '.'
                
                formatted_results.append(
                    f"{i}. {title}\n"
                    f"   {snippet}\n"
                    f"   🔗 {url}\n"
                )
            
            response = (
                f"🔍 Search Results for '{query}':\n\n"
                f"📌 Summary:\n{summary}\n\n"
                "🔎 Detailed Results:\n"
                + '\n'.join(formatted_results)
                + "\n\nℹ️ These are the most relevant results I found."
            )
            
            # Add to search history
            if user_id:
                add_to_search_history(user_id, query, response, "duckduckgo")
                
            return response
    except Exception as e:
        return f"⚠️ Search error: {str(e)}"

def get_weather(query, user_id=None):
    try:
        api_key = "23f85f9cf5138098bf3f0e723b9c115e"
        city = re.sub(r'[^a-zA-Z\s]', '', query.split("in")[-1]).strip()
        url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}&units=metric"
        response = requests.get(url)
        data = response.json()
        
        if response.status_code == 200:
            result = (
                f"<h2>⛅ Weather in {city}</h2>\n"
                f"<div class='weather-info'>\n"
                f"<p>🌡️ <b>Temperature:</b> {data['main']['temp']}°C (Feels like {data['main']['feels_like']}°C)</p>\n"
                f"<p>🌤️ <b>Conditions:</b> {data['weather'][0]['description'].capitalize()}</p>\n"
                f"<p>💧 <b>Humidity:</b> {data['main']['humidity']}%</p>\n"
                f"<p>💨 <b>Wind:</b> {data['wind']['speed']} m/s</p>\n"
                f"</div>"
            )
            
            if user_id:
                add_to_search_history(user_id, query, result, "weather")
                
            return result
        return f"❌ Couldn't retrieve weather for {city}."
    except Exception as e:
        return f"⚠️ Weather error: {str(e)}"

def get_news(query, user_id=None):
    try:
        api_key = "dcb39081dee74468b442aab74be18043"
        url = f"https://newsapi.org/v2/everything?q={query}&pageSize=5&sortBy=relevancy&apiKey={api_key}"
        response = requests.get(url).json()
        
        if response["status"] == "ok" and response["articles"]:
            news_items = []
            for article in response["articles"][:30]:
                title = article['title'] or "No title"
                source = article['source']['name'] or "Unknown source"
                description = article['description'] or "No description available"
                news_items.append(
                    f"<div class='news-item'>\n"
                    f"<h3>📰 {title}</h3>\n"
                    f"<p><i>Source: {source}</i></p>\n"
                    f"<p>{description}</p>\n"
                    f"</div>"
                )
            
            headlines = "\n".join([article['title'] for article in response["articles"][:3]])
            summary = generate_summary(f"News headlines about {query}:\n{headlines}")
            
            result = (
                f"<h2>🗞️ Latest News</h2>\n"
                f"<div class='news-summary'>\n"
                f"<h3>📌 Summary</h3>\n"
                f"<p>{summary}</p>\n"
                f"</div>\n"
                f"<div class='news-list'>\n"
                + '\n'.join(news_items) +
                f"\n</div>"
            )
            
            if user_id:
                add_to_search_history(user_id, query, result, "news")
                
            return result
        return "❌ No news articles found."
    except Exception as e:
        return f"⚠️ News error: {str(e)}"

def get_definition(word, user_id=None):
    try:
        app_id = "ae5dc989"
        app_key = "73760fe15cb02a28fc764bce231e62cc"
        url = f"https://od-api-sandbox.oxforddictionaries.com/api/v2/entries/en-us/{word.lower()}"
        headers = {"app_id": app_id, "app_key": app_key}

        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            return f"❌ Dictionary API error: {response.status_code}"

        data = response.json()
        if "results" in data and data["results"]:
            lexical_entries = data["results"][0].get("lexicalEntries", [])
            definitions = []

            for entry in lexical_entries[:10]:
                category = entry.get("lexicalCategory", {}).get("text", "Unknown")
                senses = entry.get("entries", [{}])[0].get("senses", [])
                for sense in senses[:10]:
                    if "definitions" in sense:
                        definitions.append(f"<li>📖 <b>[{category}]</b> {sense['definitions'][0]}</li>")

            if not definitions:
                return f"❌ No definitions found for '{word}'."

            definition_text = '\n'.join(definitions[:4])
            summary = generate_summary(f"Definitions of {word}:\n{definition_text}")

            result = (
                f"<h2>📚 Definitions of {word}</h2>\n"
                f"<div class='definition-summary'>\n"
                f"<h3>📌 Summary</h3>\n"
                f"<p>{summary}</p>\n"
                f"</div>\n"
                f"<div class='definition-list'>\n"
                f"<ul>\n{definition_text}\n</ul>\n"
                f"</div>"
            )

            if user_id:
                add_to_search_history(user_id, word, result, "dictionary")

            return result

        return f"❌ No definition found for '{word}'."
    except Exception as e:
        return f"⚠️ Dictionary error: {str(e)}"

# ========== MASTER FUNCTION ==========
def get_short_answer(query: str) -> str:
    """Handle short, direct answers for simple questions."""
    query_lower = query.lower().strip()
    
    # Check for brief/short answer requests
    brief_indicators = ["briefly", "in brief", "short", "in short", "in 3 lines", "in 3 sentences", "summarize"]
    is_brief_request = any(indicator in query_lower for indicator in brief_indicators)
    
    # Remove brief indicators from query for processing
    clean_query = query_lower
    for indicator in brief_indicators:
        clean_query = clean_query.replace(indicator, "").strip()
    
    # Greetings
    greetings = {
        "hi": "Hello! How can I help you today?",
        "hello": "Hi there! What can I do for you?",
        "hey": "Hey! How can I assist you?",
        "hlw": "Hello! How can I help you?",
        "hlo": "Hi! What can I do for you?",
        "hii": "Hello! How can I help you today?",
        "hiii": "Hi there! What can I do for you?",
        "yo": "Hey! How can I help?",
        "sup": "Hey! What's up? How can I help?",
        "greetings": "Hello! How can I assist you today?"
    }
    
    # Farewells
    farewells = {
        "bye": "Goodbye! Have a great day!",
        "goodbye": "Bye! Take care!",
        "see you": "See you later! Take care!",
        "cya": "See you! Have a good one!",
        "good night": "Good night! Sleep well!",
        "gn": "Good night! Sweet dreams!",
        "good morning": "Good morning! Have a great day!",
        "gm": "Good morning! How can I help you today?",
        "good afternoon": "Good afternoon! How can I assist you?",
        "ga": "Good afternoon! What can I do for you?"
    }
    
    # Thanks
    thanks = {
        "thanks": "You're welcome!",
        "thank you": "You're welcome!",
        "thx": "You're welcome!",
        "ty": "You're welcome!",
        "thank": "You're welcome!",
        "appreciate it": "You're welcome!",
        "thanks a lot": "You're welcome! Happy to help!",
        "thank you so much": "You're very welcome!",
        "thnx": "You're welcome!",
        "tnx": "You're welcome!"
    }
    
    # Affirmations
    affirmations = {
        "ok": "Alright!",
        "okay": "Alright!",
        "sure": "Great!",
        "yes": "Perfect!",
        "yeah": "Great!",
        "yep": "Alright!",
        "fine": "Good!",
        "good": "Great!",
        "great": "Excellent!",
        "awesome": "Fantastic!"
    }
    
    # Help related
    help_queries = {
        "help": "I can help you with information, calculations, weather, news, and more. What would you like to know?",
        "help me": "I'm here to help! What do you need?",
        "can you help": "Of course! What can I help you with?",
        "do you help": "Yes, I can help! What do you need?",
        "how do you work": "I can search information, calculate, check weather, get news, and more. What would you like to try?",
        "what can you do": "I can search information, calculate, check weather, get news, and more. What would you like to try?",
        "your capabilities": "I can search information, calculate, check weather, get news, and more. What would you like to try?",
        "your features": "I can search information, calculate, check weather, get news, and more. What would you like to try?",
        "your functions": "I can search information, calculate, check weather, get news, and more. What would you like to try?",
        "your abilities": "I can search information, calculate, check weather, get news, and more. What would you like to try?"
    }
    
    # Check all dictionaries
    if query_lower in greetings:
        return greetings[query_lower]
    if query_lower in farewells:
        return farewells[query_lower]
    if query_lower in thanks:
        return thanks[query_lower]
    if query_lower in affirmations:
        return affirmations[query_lower]
    if query_lower in help_queries:
        return help_queries[query_lower]
    
    # Time related
    if "time" in query_lower:
        return datetime.now().strftime("%I:%M %p")
    
    # Date related
    if "date" in query_lower:
        return datetime.now().strftime("%B %d, %Y")
    
    # Yes/No questions using Gemini
    if query_lower.startswith(("is ", "are ", "do ", "does ", "did ", "can ", "will ", "should ", "would ", "could ")):
        if "?" in query_lower:
            try:
                # Use Gemini to analyze the question with a more specific prompt
                prompt = f"""You are a factual assistant. Answer this yes/no question with a clear yes or no followed by a brief explanation.
                Question: {query}
                Rules:
                1. Your response MUST start with either "Yes:" or "No:"
                2. Provide a brief, factual explanation after the yes/no
                3. Keep the explanation under 2 sentences
                4. Be direct and clear
                5. Base your answer on scientific facts and common knowledge
                
                Example format:
                Yes: [brief explanation]
                or
                No: [brief explanation]
                
                Your response:"""
                
                response = query_gemini(prompt, use_history=False)
                
                # Clean up the response
                response = response.replace("🔮 NAF AI Response:\n\n", "").strip()
                
                # Extract yes/no from response
                response_lower = response.lower()
                if response_lower.startswith("yes:"):
                    return response[4:].strip()
                elif response_lower.startswith("no:"):
                    return response[3:].strip()
                elif "yes" in response_lower[:10]:
                    return "Yes: " + response
                elif "no" in response_lower[:10]:
                    return "No: " + response
                else:
                    # If we can't parse the response, try to determine yes/no from content
                    if any(word in response_lower for word in ["yes", "correct", "true", "right", "indeed"]):
                        return "Yes: " + response
                    elif any(word in response_lower for word in ["no", "incorrect", "false", "wrong", "not"]):
                        return "No: " + response
                    else:
                        return "Yes: " + response  # Default to yes if we can't determine
                    
            except Exception as e:
                print(f"Gemini error in yes/no question: {str(e)}")
                # Fallback to simple keyword matching if Gemini fails
                return "Yes" if any(word in query_lower for word in ["good", "right", "correct", "true", "possible", "available"]) else "No"
    
    # Handle brief/short answer requests
    if is_brief_request:
        try:
            prompt = f"""Provide a very brief summary about {clean_query} in exactly 3 lines or less.
            Rules:
            1. Keep it extremely concise
            2. Focus on the most important information
            3. Use simple, clear language
            4. Maximum 3 lines
            5. No unnecessary details
            
            Your response:"""
            
            response = query_gemini(prompt, use_history=False)
            response = response.replace("🔮 NAF AI Response:\n\n", "").strip()
            
            # Ensure response is not too long
            lines = response.split('\n')
            if len(lines) > 3:
                response = '\n'.join(lines[:3])
            
            return response
            
        except Exception as e:
            print(f"Gemini error in brief answer: {str(e)}")
            return None
    
    return None

@limiter.limit("10 per minute")
def get_answer(query, user_id):
    query_lower = query.lower().strip()
    if not query_lower:
        return "Please enter a valid query."

    try:
        # Check cache first
        cache_key = f"answer_{hash(query_lower)}"
        cached_answer = cache.get(cache_key)
        if cached_answer:
            return cached_answer

        # Try to get a short answer first
        short_answer = get_short_answer(query)
        if short_answer:
            return short_answer

        # Check related history with optimized matching
        related_history = get_related_history(user_id, query)
        history_prompt = ""
        
        if related_history:
            history_items = []
            for item in related_history:
                history_items.append(f"- Previous query: {item['query']}")
                response_preview = summarize_response(item['response'])
                history_items.append(f"  Response: {response_preview}")
            
            history_prompt = (
                "📚 I found similar previous searches:\n" + 
                "\n".join(history_items) + 
                "\n\nHere's the new answer:\n\n"
            )

        # Process query with optimized routing
        response = None
        if query_lower.startswith("."):
            response = query_gemini(query[len("."):].strip(), use_history=True, user_id=user_id)
        # Check for mathematical queries
        elif (query_lower.startswith(("solve", "calculate", "compute")) or
              any(op in query_lower for op in ["+", "-", "*", "/", "=", "^", "√", "square root", "power", "exponent"]) or
              any(word in query_lower for word in ["plus", "minus", "times", "divided by", "multiply", "divide", "sum", "difference", "product", "quotient"]) or
              any(word in query_lower for word in ["equation", "formula", "function", "derivative", "integral", "limit", "matrix", "vector", "probability", "statistics"])):
            math_query = query.split(maxsplit=1)[1] if len(query.split()) > 1 and query_lower.startswith(("solve", "calculate", "compute")) else query
            response = query_wolfram(math_query, user_id)
        elif "weather" in query_lower:
            response = get_weather(query, user_id)
        elif "news" in query_lower:
            topic = query_lower.replace("news", "").strip() or "current events"
            response = get_news(topic, user_id)
        elif query_lower.startswith(("define", "meaning of")):
            word = re.sub(r'^(define|what is|meaning of)\s+', '', query_lower)
            response = get_definition(word, user_id)
        elif any(word in query_lower for word in ["history", "medical", "war", "disease", "president", "empire","about","born","birth"]):
            response = cached_search(query, 'wikipedia')
        else:
            response = cached_search(query, 'duckduckgo')
            if "No results" in response:
                response = f"I couldn't find specific information about '{query}'. Would you like to try rephrasing your question?"

        # Add history context if available
        if history_prompt and not query_lower.startswith("."):
            response = history_prompt + response

        # Cache the response
        cache.set(cache_key, response, timeout=300)
        return response

    except Exception as e:
        return f"⚠️ Error processing your request: {str(e)}"

# ========== Flask Routes ==========
@app.route('/ask', methods=['POST', 'OPTIONS'])
@limiter.limit("10 per minute")
def ask():
    if request.method == 'OPTIONS':
        return _build_cors_preflight_response()
        
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Invalid request data"}), 400
            
        query = data.get('query', '').strip()
        if not query:
            return jsonify({"error": "Query cannot be empty"}), 400
        
        # Get or create user ID with optimized session handling
        user_id = data.get('user_id', None)
        try:
            user_id = get_user_session_id()
        except Exception:
            if not user_id:
                user_id = str(os.urandom(16).hex())
        
        # Get answer with caching
        answer = get_answer(query, user_id)
        
        # Add performance metrics
        response_time = datetime.now().isoformat()
        
        return jsonify({
            "status": "success",
            "response": answer,
            "query": query,
            "user_id": user_id,
            "timestamp": response_time,
            "has_history": len(get_user_history(user_id)['search_history']) > 0,
            "active_users": active_users
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": f"An error occurred: {str(e)}"
        }), 500

@app.route('/history', methods=['POST', 'OPTIONS'])
def get_history():
    if request.method == 'OPTIONS':
        return _build_cors_preflight_response()
    
    try:
        data = request.get_json()
        
        # Get user ID (preferably from session, fallback to request)
        user_id = data.get('user_id', None)
        try:
            user_id = get_user_session_id()
        except Exception:
            if not user_id:
                return jsonify({"status": "error", "error": "No user ID provided"}), 400
        
        history = get_user_history(user_id)
        
        return jsonify({
            "status": "success",
            "history": history['search_history']
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": f"An error occurred: {str(e)}"
        }), 500

@app.route('/clear_history', methods=['POST', 'OPTIONS'])
def clear_history():
    if request.method == 'OPTIONS':
        return _build_cors_preflight_response()
    
    try:
        data = request.get_json()
        user_id = data.get('user_id', None)
        try:
            user_id = get_user_session_id()
        except Exception:
            if not user_id:
                return jsonify({"status": "error", "error": "No user ID provided"}), 400
        
        user_history[user_id] = {
            'search_history': [],
            'gemini_history': []
        }
        
        return jsonify({
            "status": "success",
            "message": "History cleared successfully"
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": f"An error occurred: {str(e)}"
        }), 500

@app.route('/suggest', methods=['POST', 'OPTIONS'])
def suggest():
    if request.method == 'OPTIONS':
        return _build_cors_preflight_response()
        
    try:
        data = request.get_json()
        partial_query = (data.get('query', '') or '').lower().strip()
        
        suggestions = []
        if partial_query.startswith('wh'):
            suggestions = ["what is", "when is", "where is", "who is"]
        elif partial_query.startswith('how'):
            suggestions = ["how to", "how does", "how can"]
        
        return jsonify({
            "status": "success",
            "suggestions": [s for s in suggestions if s.startswith(partial_query)][:3]
        })
    except Exception:
        return jsonify({"status": "success", "suggestions": []})

def _build_cors_preflight_response():
    response = jsonify({"status": "preflight"})
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add("Access-Control-Allow-Headers", "*")
    response.headers.add("Access-Control-Allow-Methods", "*")
    return response

def _corsify_actual_response(response):
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add("Access-Control-Allow-Headers", "*")
    response.headers.add("Access-Control-Allow-Methods", "*")
    return response

# Add new feature: Response summarization
def summarize_response(text, max_length=600):
    """Generate a concise summary of the response."""
    if len(text) <= max_length:
        return text
    
    sentences = text.split('.')
    summary = []
    current_length = 0
    
    for sentence in sentences:
        if current_length + len(sentence) <= max_length:
            summary.append(sentence)
            current_length += len(sentence)
        else:
            break
    
    return '.'.join(summary) + '...'

# Add new feature: Smart caching for search results
@cache.memoize(timeout=300)
def cached_search(query, source):
    """Cache search results for frequently asked questions."""
    if source == 'wikipedia':
        return search_wikipedia(query)
    elif source == 'duckduckgo':
        return search_duckduckgo(query)
    return None

# Add new route for performance metrics
@app.route('/metrics', methods=['GET'])
def get_metrics():
    return jsonify({
        "active_users": active_users,
        "user_sessions": len(user_sessions),
        "cache_stats": cache.get_stats() if hasattr(cache, 'get_stats') else None
    })

# Run the app with optimized settings
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False, use_reloader=False)  
