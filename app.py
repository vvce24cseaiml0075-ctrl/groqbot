import os
import sys
import json
import socket
from pathlib import Path

# Ensure UTF-8 output encoding on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

from flask import Flask, render_template, request, Response, jsonify, stream_with_context
from dotenv import load_dotenv
from groq import Groq, APIError, AuthenticationError, RateLimitError

# Load environment variables from .env
env_path = Path(__file__).resolve().parent / '.env'
load_dotenv(dotenv_path=env_path, override=True)

app = Flask(__name__)

def get_lan_ip():
    """Detect local LAN IP for multi-user network sharing."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

# Available curated Groq models
AVAILABLE_MODELS = [
    {
        "id": "qwen/qwen3.8-27b",
        "name": "Qwen 3.8 27B",
        "description": "State of the art reasoning, coding, and general knowledge",
        "context": "32k tokens",
        "recommended": True,
        "badge": "Flagship"
    },
    {
        "id": "groq/compound",
        "name": "Groq Compound",
        "description": "Groq advanced compound intelligence model",
        "context": "32k tokens",
        "recommended": False,
        "badge": "Advanced"
    },
    {
        "id": "groq/compound-mini",
        "name": "Groq Compound Mini",
        "description": "Ultra-fast response latency optimized for efficiency",
        "context": "16k tokens",
        "recommended": False,
        "badge": "Fastest"
    },
    {
        "id": "openai/gpt-oss-120b",
        "name": "GPT-OSS 120B",
        "description": "Large parameter open model for in-depth tasks",
        "context": "32k tokens",
        "recommended": False,
        "badge": "High Capacity"
    },
    {
        "id": "allam-2-7b",
        "name": "Allam 2 7B",
        "description": "Fast and responsive multilingual model",
        "context": "8k tokens",
        "recommended": False,
        "badge": "Efficient"
    }
]

def get_api_key():
    """Retrieve Groq API key from environment."""
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key or key == "your_groq_api_key_here":
        return None
    return key

def get_groq_client():
    """Instantiate Groq client using configured API key."""
    api_key = get_api_key()
    if not api_key:
        raise ValueError("GROQ_API_KEY is not configured in .env file.")
    return Groq(api_key=api_key)

@app.route("/")
def index():
    """Serve the main chat application interface."""
    return render_template("index.html")

@app.route("/api/status", methods=["GET"])
def get_status():
    """Check if Groq API key is configured and return app info."""
    api_key = get_api_key()
    has_key = bool(api_key)
    masked_key = ""
    if has_key and len(api_key) > 8:
        masked_key = f"{api_key[:4]}...{api_key[-4:]}"
    elif has_key:
        masked_key = "****"

    default_model = os.environ.get("DEFAULT_MODEL", "qwen/qwen3.8-27b")
    allow_key_edit = os.environ.get("ALLOW_KEY_EDIT", "false").lower() in ("true", "1", "yes")
    lan_ip = get_lan_ip()
    port = int(os.environ.get("PORT", 5000))

    return jsonify({
        "configured": has_key,
        "masked_key": masked_key,
        "default_model": default_model,
        "status": "ready" if has_key else "missing_key",
        "allow_key_edit": allow_key_edit,
        "network_url": f"http://{lan_ip}:{port}",
        "local_url": f"http://localhost:{port}",
        "lan_ip": lan_ip
    })

@app.route("/api/network-info", methods=["GET"])
def network_info():
    """Return LAN network address for multi-user sharing."""
    port = int(os.environ.get("PORT", 5000))
    lan_ip = get_lan_ip()
    allow_key_edit = os.environ.get("ALLOW_KEY_EDIT", "false").lower() in ("true", "1", "yes")
    return jsonify({
        "local_url": f"http://localhost:{port}",
        "network_url": f"http://{lan_ip}:{port}",
        "ip": lan_ip,
        "lan_ip": lan_ip,
        "port": port,
        "hostname": socket.gethostname(),
        "allow_key_edit": allow_key_edit
    })


@app.route("/api/config/key", methods=["POST"])
def update_api_key():
    """Optionally update or save the Groq API key to .env directly from the UI."""
    allow_key_edit = os.environ.get("ALLOW_KEY_EDIT", "false").lower() in ("true", "1", "yes")
    if not allow_key_edit and get_api_key():
        return jsonify({
            "error": "API Key is managed by the host administrator and cannot be modified by guest users."
        }), 403

    data = request.get_json() or {}
    new_key = data.get("api_key", "").strip()

    if not new_key:
        return jsonify({"error": "API key cannot be empty"}), 400

    if not new_key.startswith("gsk_"):
        return jsonify({"error": "Invalid format. Groq API keys typically begin with 'gsk_'"}), 400

    try:
        # Verify key with test call
        test_client = Groq(api_key=new_key)
        # Fast lightweight ping
        test_client.models.list()
    except AuthenticationError:
        return jsonify({"error": "Invalid API key. Groq rejected this key."}), 401
    except Exception as e:
        return jsonify({"error": f"Error validating key with Groq: {str(e)}"}), 400

    # Save to .env
    lines = []
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    key_found = False
    new_lines = []
    for line in lines:
        if line.startswith("GROQ_API_KEY="):
            new_lines.append(f"GROQ_API_KEY={new_key}\n")
            key_found = True
        else:
            new_lines.append(line)

    if not key_found:
        new_lines.append(f"\nGROQ_API_KEY={new_key}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    os.environ["GROQ_API_KEY"] = new_key

    return jsonify({
        "success": True,
        "message": "Groq API key saved successfully and verified with Groq!",
        "masked_key": f"{new_key[:4]}...{new_key[-4:]}"
    })

@app.route("/api/models", methods=["GET"])
def list_models():
    """Return the list of curated supported Groq models."""
    return jsonify({
        "models": AVAILABLE_MODELS,
        "default": os.environ.get("DEFAULT_MODEL", "qwen/qwen3.8-27b")
    })

@app.route("/api/chat", methods=["POST"])
def chat():
    """Handle chat completion requests with real-time SSE streaming or standard JSON."""
    data = request.get_json()
    if not data or "messages" not in data:
        return jsonify({"error": "Invalid payload. 'messages' array is required."}), 400

    messages = data.get("messages", [])
    model = data.get("model", os.environ.get("DEFAULT_MODEL", "qwen/qwen3.8-27b"))
    temperature = float(data.get("temperature", 0.7))
    max_tokens = int(data.get("max_tokens", 4096))
    stream = data.get("stream", True)

    try:
        client = get_groq_client()
    except ValueError as e:
        return jsonify({
            "error": "API Key Not Found",
            "message": "Please configure your GROQ_API_KEY in the .env file or via the settings dialog.",
            "code": "MISSING_API_KEY"
        }), 401

    if stream:
        def generate():
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=True
                )
                for chunk in response:
                    content = chunk.choices[0].delta.content or ""
                    if content:
                        payload = json.dumps({"token": content})
                        yield f"data: {payload}\n\n"
                    
                    if chunk.choices[0].finish_reason:
                        payload = json.dumps({
                            "done": True,
                            "finish_reason": chunk.choices[0].finish_reason
                        })
                        yield f"data: {payload}\n\n"
                        break
            except AuthenticationError:
                err = json.dumps({"error": "Authentication failed. Please verify your GROQ_API_KEY in .env."})
                yield f"data: {err}\n\n"
            except RateLimitError:
                err = json.dumps({"error": "Groq rate limit exceeded. Please wait a moment and try again."})
                yield f"data: {err}\n\n"
            except APIError as e:
                err = json.dumps({"error": f"Groq API error: {str(e)}"})
                yield f"data: {err}\n\n"
            except Exception as e:
                err = json.dumps({"error": f"Unexpected error: {str(e)}"})
                yield f"data: {err}\n\n"

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no"
            }
        )
    else:
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=False
            )
            reply = response.choices[0].message.content
            usage = {
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                "total_tokens": response.usage.total_tokens if response.usage else 0,
            }
            return jsonify({
                "message": {
                    "role": "assistant",
                    "content": reply
                },
                "usage": usage,
                "model": model
            })
        except AuthenticationError:
            return jsonify({"error": "Authentication failed. Invalid GROQ_API_KEY in .env."}), 401
        except RateLimitError:
            return jsonify({"error": "Groq rate limit reached. Please wait a few seconds."}), 429
        except APIError as e:
            return jsonify({"error": f"Groq API error: {str(e)}"}), 500
        except Exception as e:
            return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV", "development") == "development"
    lan_ip = get_lan_ip()
    print(f"\n🕷️  Spidy Bot — Multi-User Server Running:")
    print(f"   🏠 Local:   http://localhost:{port}")
    print(f"   🌐 Network: http://{lan_ip}:{port} (Share with others on Wi-Fi/LAN!)")
    print(f"🔑 Groq API Key: {'Configured ✅' if get_api_key() else 'Missing ⚠️  (Configure in .env)'}\n")
    app.run(host="0.0.0.0", port=port, debug=debug, threaded=True)
