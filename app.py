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
    """Optimized text formatting with caching."""
    cache_key = f"format_{hash(text)}"
    cached_result = cache.get(cache_key)
    if cached_result:
        return cached_result

    text = html.escape(text)
    paragraphs = text.split('\n')
    formatted_paragraphs = [p for p in paragraphs if p.strip()]
    result = '\n\n'.join(formatted_paragraphs)
    
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
    """Format Wikipedia content to preserve complete paragraphs only."""
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
            main_content.append(para)
            char_count += para_length
        else:
            break

    formatted_content = '\n\n'.join(main_content)
    
    if len(formatted_content) >= max_chars:
        formatted_content = formatted_content[:max_chars] + "\n\n[Content truncated]"

    return format_text(formatted_content)

def format_search_results(results):
    """Format search results from DuckDuckGo with complete information."""
    if not results:
        return "No results found."
    
    formatted = []
    for i, result in enumerate(results[:5], 1):
        title = result.get('title', 'No title')
        body = result.get('body', 'No description')
        url = result.get('href', '#')
        
        formatted.append(
            f"<b>{i}. <a href='{html.escape(url)}' target='_blank'>{html.escape(title)}</a></b><br>"
            f"{html.escape(body)}<br><br>"
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
                f"⛅ Weather in {city}:\n"
                f"• Temperature: {data['main']['temp']}°C (Feels like {data['main']['feels_like']}°C)\n"
                f"• Conditions: {data['weather'][0]['description'].capitalize()}\n"
                f"• Humidity: {data['main']['humidity']}%\n"
                f"• Wind: {data['wind']['speed']} m/s"
            )
            
            # Add to search history
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
                news_items.append(f"📰 {title} ({source})\n{description}\n")
            
            # Generate summary from headlines
            headlines = "\n".join([article['title'] for article in response["articles"][:3]])
            summary = generate_summary(f"News headlines about {query}:\n{headlines}")
            
            result = "🗞️ Latest News:\n\n" + f"📌 Summary:\n{summary}\n\n" + '\n'.join(news_items)
            
            # Add to search history
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
                        definitions.append(f"• [{category}] {sense['definitions'][0]}")

            if not definitions:
                return f"❌ No definitions found for '{word}'."

            definition_text = '\n'.join(definitions[:4])
            summary = generate_summary(f"Definitions of {word}:\n{definition_text}")

            result = (
                f"📖 Definitions of {word}:\n\n"
                f"📌 Summary:\n{summary}\n\n"
                f"📖 Full Definitions:\n{definition_text}"
            )

            # Add to search history
            if user_id:
                add_to_search_history(user_id, word, result, "dictionary")

            return result

        return f"❌ No definition found for '{word}'."
    except Exception as e:
        return f"⚠️ Dictionary error: {str(e)}"

# ========== MASTER FUNCTION ==========
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
        elif query_lower.startswith(("solve", "calculate", "compute")):
            math_query = query.split(maxsplit=1)[1] if len(query.split()) > 1 else query
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
def summarize_response(text, max_length=200):
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
