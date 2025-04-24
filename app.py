from flask import Flask, request, jsonify
from flask_cors import CORS
import wikipedia
import requests
from duckduckgo_search import DDGS
import re
from textwrap import wrap
import html

app = Flask(__name__)
CORS(app)

# ========== HELPER FUNCTIONS ==========
import html

def format_text(text, max_line_length=8000):
    """Format text with proper line wrapping while preserving complete paragraphs."""
    text = html.escape(text)  # Escape HTML special characters
    paragraphs = text.split('\n')
    formatted_paragraphs = []
    
    for para in paragraphs:
        if para.strip():
            formatted_paragraphs.append(para)
    
    return '\n\n'.join(formatted_paragraphs)


def format_wikipedia_content(content):
    """Format Wikipedia content to preserve complete paragraphs only."""
    paragraphs = content.split('\n\n')
    main_content = []
    char_count = 0
    max_chars = 10000  # You can increase this if you want longer output

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        para_length = len(para)
        if char_count + para_length <= max_chars:
            main_content.append(para)
            char_count += para_length
        else:
            # Stop before adding any partial paragraph
            break

    # Ensure no truncation unless necessary
    formatted_content = '\n\n'.join(main_content)
    
    # If the content is too long, add a note
    if len(formatted_content) >= max_chars:
        formatted_content = formatted_content[:max_chars] + "\n\n[Content truncated]"

    return format_text(formatted_content)



def format_search_results(results):
    """Format search results from DuckDuckGo with complete information."""
    if not results:
        return "No results found."
    
    formatted = []
    for i, result in enumerate(results[:50], 1):  # Limit to 5 results
        title = result.get('title', 'No title')
        body = result.get('body', 'No description')
        url = result.get('href', '#')
        
        # Use HTML format with clickable title as link
        formatted.append(
            f"<b>{i}. <a href='{html.escape(url)}' target='_blank'>{html.escape(title)}</a></b><br>"
            f"{html.escape(body)}<br><br>"
        )

    return ''.join(formatted)

# ========== API INTEGRATIONS ==========
def query_gemini(prompt):
    try:
        api_key = "AIzaSyDfSvbxY1kVrlxYOz43ZBE-oyBmQu2RqXA"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}
        data = {
            "contents": [{
                "parts": [{"text": prompt}]
            }]
        }
        response = requests.post(url, headers=headers, json=data)
        result = response.json()

        if "candidates" in result and result["candidates"]:
            return f"🔮 NAF AI Response:\n\n{format_text(result['candidates'][0]['content']['parts'][0]['text'])}"
        return "❌ NAF couldn't generate a response."
    except Exception as e:
        return f"⚠️ NAF error: {str(e)}"

def query_wolfram(query):
    try:
        app_id = "A2J4RE-Q82P4TTV5A"
        url = f"https://api.wolframalpha.com/v1/result?i={requests.utils.quote(query)}&appid={app_id}"
        response = requests.get(url)
        return f"🧮 NAF Answer:\n\n{format_text(response.text)}" if response.status_code == 200 else "❌ NAF couldn't solve this."
    except Exception as e:
        return f"⚠️ Wolfram error: {str(e)}"

def search_wikipedia(query):
    try:
        wikipedia.set_lang("en")
        search_results = wikipedia.search(query)
        if not search_results:
            return "❌ Nothing found for this topic."
            
        page = wikipedia.page(search_results[0])
        formatted_content = format_wikipedia_content(page.content)
        return f"📚 NAF: {page.title}\n\n{formatted_content}\n\nRead more: {page.url}"
    except wikipedia.exceptions.DisambiguationError as e:
        options = '\n'.join([f"• {opt}" for opt in e.options[:50]])
        return f"🔍 Multiple options found:\n\n{options}\n\nPlease refine your query."
    except Exception as e:
        return f"⚠️ NAF error: {str(e)}"

def search_duckduckgo(query):
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=500))
            if not results:
                return "🔍 No search results found for your query."
                
            formatted_results = []
            for i, result in enumerate(results, 1):
                title = result.get('title', 'Untitled')
                url = result.get('href', '#')
                snippet = result.get('body', 'No description available.')
                
                # Clean up the snippet
                snippet = snippet.replace('\n', ' ').strip()
                if len(snippet) > 200:  # Truncate long snippets
                    snippet = snippet[:200] + '...'
                
                formatted_results.append(
                    f"{i}. {title}\n"
                    f"   {snippet}\n"
                    f"   🔗 {url}\n"
                )
            
            return (
                f"🔍 Search Results for '{query}':\n\n"
                + '\n'.join(formatted_results)
                + "\n\nℹ️ These are the most relevant results I found. "
                "Let me know if you'd like more details about any specific result."
            )
    except Exception as e:
        return f"⚠️ Search error: {str(e)}"

def get_weather(query):
    try:
        api_key = "23f85f9cf5138098bf3f0e723b9c115e"
        city = re.sub(r'[^a-zA-Z\s]', '', query.split("in")[-1]).strip()
        url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}&units=metric"
        response = requests.get(url)
        data = response.json()
        
        if response.status_code == 200:
            weather_info = (
                f"⛅ Weather in {city}:\n"
                f"• Temperature: {data['main']['temp']}°C (Feels like {data['main']['feels_like']}°C)\n"
                f"• Conditions: {data['weather'][0]['description'].capitalize()}\n"
                f"• Humidity: {data['main']['humidity']}%\n"
                f"• Wind: {data['wind']['speed']} m/s"
            )
            return weather_info
        return f"❌ Couldn't retrieve weather for {city}."
    except Exception as e:
        return f"⚠️ Weather error: {str(e)}"

def get_news(query):
    try:
        api_key = "dcb39081dee74468b442aab74be18043"
        url = f"https://newsapi.org/v2/everything?q={query}&pageSize=5&sortBy=relevancy&apiKey={api_key}"
        response = requests.get(url).json()
        
        if response["status"] == "ok" and response["articles"]:
            news_items = []
            for article in response["articles"][:5]:
                title = article['title'] or "No title"
                source = article['source']['name'] or "Unknown source"
                description = article['description'] or "No description available"
                news_items.append(f"📰 {title} ({source})\n{description}\n")
            return "🗞️ Latest News:\n\n" + '\n'.join(news_items)
        return "❌ No news articles found."
    except Exception as e:
        return f"⚠️ News error: {str(e)}"

def get_definition(word):
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
            lexical_entries = data["results"][0]["lexicalEntries"]
            definitions = []
            
            for entry in lexical_entries[:2]:  # Limit to first 2 entries
                category = entry["lexicalCategory"]["text"]
                for sense in entry["entries"][0]["senses"][:2]:  # First 2 senses
                    if "definitions" in sense:
                        definitions.append(f"• [{category}] {sense['definitions'][0]}")
            
            return f"📖 Definitions of {word}:\n\n" + '\n'.join(definitions[:4])  # Max 4 definitions
        return f"❌ No definition found for '{word}'."
    except Exception as e:
        return f"⚠️ Dictionary error: {str(e)}"

# ========== MASTER FUNCTION ==========
def get_answer(query):
    query_lower = query.lower().strip()

    if not query_lower:
        return "Please enter a valid query."

    # Command-based routing
    if query_lower.startswith("ai"):
        return query_gemini(query[len("ai"):].strip())
    elif query_lower.startswith(("solve", "calculate", "compute")):
        return query_wolfram(query.split(maxsplit=1)[1] if len(query.split()) > 1 else query)
    elif "weather" in query_lower:
        return get_weather(query)
    elif "news" in query_lower:
        topic = query_lower.replace("news", "").strip() or "current events"
        return get_news(topic)
    elif query_lower.startswith(("define", "what is", "meaning of")):
        word = re.sub(r'^(define|what is|meaning of)\s+', '', query_lower)
        return get_definition(word)
    elif any(word in query_lower for word in ["history", "medical", "war", "disease", "president", "empire", "science", "biology"]):
        return search_wikipedia(query)
    else:
        # Fallback to search with a more conversational response
        search_results = search_duckduckgo(query)
        if "No results" in search_results:
            return f"I couldn't find specific information about '{query}'. Would you like to try rephrasing your question?"
        return search_results

# ========== Flask Routes ==========
@app.route('/ask', methods=['POST'])
def ask():
    try:
        data = request.get_json()
        query = data.get('query', '').strip()
        
        if not query:
            return jsonify({"error": "Query cannot be empty."}), 400
        
        answer = get_answer(query)
        return jsonify({"response": answer})
    
    except Exception as e:
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500

@app.route('/suggest', methods=['POST'])
def suggest():
    """Endpoint for query suggestions"""
    try:
        data = request.get_json()
        partial_query = data.get('query', '').lower().strip()
        
        if not partial_query:
            return jsonify({"suggestions": []})
            
        # Simple suggestion logic - can be enhanced with a real suggestion engine
        suggestions = []
        if partial_query.startswith('wh'):
            suggestions = ["what is", "when is", "where is", "who is"]
        elif partial_query.startswith('how'):
            suggestions = ["how to", "how does", "how can"]
        
        return jsonify({"suggestions": [s for s in suggestions if s.startswith(partial_query)][:3]})
    except Exception as e:
        return jsonify({"suggestions": []})

if __name__ == "__main__":
    app.run(debug=True)
