from fastapi import Request, FastAPI, HTTPException
import os
import sys
import aiohttp

from linebot.models import MessageEvent, TextSendMessage
from linebot.exceptions import InvalidSignatureError
from linebot.aiohttp_async_http_client import AiohttpAsyncHttpClient
from linebot import AsyncLineBotApi, WebhookParser

# ADK and GenAI imports
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.genai import types
from google.adk.sessions import InMemorySessionService  # Add this import
import secrets  # For generating unique session ID parts

# Import stock agent tools
from multi_tool_agent.stock_agent import (
    get_stock_price,
    get_price_change_percent,
    get_best_performing,
)

# OpenAI Agent configuration (Note: GOOGLE_API_KEY is used, not OpenAI)
USE_VERTEX = os.getenv("GOOGLE_GENAI_USE_VERTEXAI") or "False"
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") or ""

# LINE Bot configuration
channel_secret = os.getenv("ChannelSecret", None)
channel_access_token = os.getenv("ChannelAccessToken", None)

# Validate environment variables
if channel_secret is None:
    print("Specify ChannelSecret as environment variable.")
    sys.exit(1)
if channel_access_token is None:
    print("Specify ChannelAccessToken as environment variable.")
    sys.exit(1)
if USE_VERTEX == "True":  # Check if USE_VERTEX is true as a string
    GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT")
    GOOGLE_CLOUD_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION")
    if not GOOGLE_CLOUD_PROJECT:
        raise ValueError(
            "Please set GOOGLE_CLOUD_PROJECT via env var or code when USE_VERTEX is true."
        )
    if not GOOGLE_CLOUD_LOCATION:
        raise ValueError(
            "Please set GOOGLE_CLOUD_LOCATION via env var or code when USE_VERTEX is true."
        )
elif not GOOGLE_API_KEY:
    raise ValueError("Please set GOOGLE_API_KEY via env var or code.")

# Initialize InMemorySessionService
session_service = InMemorySessionService()
active_sessions = {}  # Cache for active session IDs per user

# Initialize the FastAPI app for LINEBot
app = FastAPI()
client_session = aiohttp.ClientSession()
async_http_client = AiohttpAsyncHttpClient(client_session)
line_bot_api = AsyncLineBotApi(channel_access_token, async_http_client)
parser = WebhookParser(channel_secret)

# --- Stock Agent Definition ---
stock_agent = Agent(
    name="stock_agent",
    model="gemini-2.0-flash",  # Or your preferred model
    description="Agent specialized in providing stock market information and analysis.",
    instruction="""
        You are an AI assistant specializing in stock market data.
        Users will ask for stock prices, price changes, or the best performing stock from a list.
        Use the provided tools to answer these questions accurately.
        - For current price, use `get_stock_price`.
        - For price change percentage over a period, use `get_price_change_percent`.
        - For finding the best performing stock in a list over a period, use `get_best_performing`.
        Always state the symbol and the period clearly in your response if applicable.
        If a stock symbol is invalid or data is unavailable, inform the user clearly.
    """,
    tools=[
        get_stock_price,
        get_price_change_percent,
        get_best_performing,
    ],
)
print(f"Agent '{stock_agent.name}' created.")

APP_NAME = "linebot_adk_app"
stock_runner = Runner(
    agent=stock_agent,
    app_name=APP_NAME,
    session_service=session_service,  # Add session_service
)
print(f"Runner created for agent '{stock_runner.agent.name}'.")


def get_or_create_session(user_id):
    if user_id not in active_sessions:
        # Create a new session for this user
        session_id = f"session_{user_id}"
        session = session_service.create_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id
        )
        active_sessions[user_id] = session_id
        print(
            f"New session created: App='{APP_NAME}', User='{user_id}', Session='{session_id}'"
        )
    else:
        # Use existing session
        session_id = active_sessions[user_id]
        print(
            f"Using existing session: App='{APP_NAME}', User='{user_id}', Session='{session_id}'"
        )

    return session_id


@app.post("/")
async def handle_callback(request: Request):
    signature = request.headers["X-Line-Signature"]
    body = await request.body()
    body = body.decode()

    try:
        events = parser.parse(body, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    for event in events:
        if not isinstance(event, MessageEvent):
            continue

        if event.message.type == "text":
            # Process text message
            msg = event.message.text
            user_id = event.source.user_id
            print(f"Received message: {msg} from user: {user_id}")

            # Use the user's prompt directly with the agent
            response = await call_agent_async(msg, user_id)
            reply_msg = TextSendMessage(text=response)
            await line_bot_api.reply_message(event.reply_token, reply_msg)
        elif event.message.type == "image":
            # return "OK" # Original line, can be pass if no specific OK is needed
            pass  # Explicitly pass if no action
        # else: # This else continue is redundant if the outer loop continues
        # continue

    return "OK"


async def call_agent_async(query: str, user_id: str) -> str:
    """Sends a query to the agent and returns the final response."""
    print(f"\n>>> User Query: {query}")
    content = types.Content(role="user", parts=[types.Part(text=query)])
    final_response_text = "Agent did not produce a final response."

    chosen_agent_runner = stock_runner
    session_id = get_or_create_session(user_id)
    max_retries = 1

    for attempt in range(max_retries + 1):
        try:
            async for event in chosen_agent_runner.run_async(
                user_id=user_id, session_id=session_id, new_message=content
            ):
                if event.is_final_response():
                    if event.content and event.content.parts:
                        final_response_text = "".join(
                            part.text
                            for part in event.content.parts
                            if hasattr(part, "text")
                        )
                    elif event.actions and event.actions.escalate:
                        final_response_text = (
                            f"Escalation from agent: {event.actions.escalate.message}"
                        )
                    break  # Break from async for loop once final response is processed
            break  # Break from retry loop if successful
        except ValueError as e:
            if "Session not found" in str(e) and attempt < max_retries:
                print(
                    f"Attempt {attempt + 1}: Session {session_id} not found. Recreating session."
                )
                if user_id in active_sessions:
                    del active_sessions[user_id]  # Clear stale session ID

                # Attempt to create a new session, letting ADK generate the ID
                try:
                    new_session_context = session_service.create_session(
                        app_name=APP_NAME, user_id=user_id
                    )
                    session_id = new_session_context.session_id
                    active_sessions[user_id] = session_id
                    print(f"New session created for retry: {session_id}")
                    # Continue to the next iteration of the retry loop
                except Exception as creation_error:
                    print(f"Error creating new session during retry: {creation_error}")
                    final_response_text = f"Sorry, there was an issue creating a new session: {creation_error}"
                    break  # Break from retry loop if session creation fails
            else:
                print(f"An error occurred during agent execution: {e}")
                final_response_text = f"Sorry, an error occurred: {e}"
                break  # Break from retry loop for other errors or max retries
        except Exception as e:
            print(f"An unexpected error occurred during agent execution: {e}")
            final_response_text = f"Sorry, an unexpected error occurred: {e}"
            break  # Break from retry loop

    print(f"<<< Agent Response: {final_response_text}")
    return final_response_text


# Add lifespan event for session cleanup
@app.on_event("shutdown")
async def shutdown_event():
    await client_session.close()
    print("Client session closed.")
