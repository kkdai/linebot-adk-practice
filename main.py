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
from google.adk.tools import google_search
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

root_agent = Agent(
    name="location_search_agent",
    model="gemini-2.0-flash",
    description="Agent tasked with generating creative and fun dating plan suggestions",
    instruction="""

        You are a specialized AI assistant tasked with generating creative and fun plan suggestions.

        **Request:**
        For the upcoming weekend, specifically from **[START_DATE_YYYY-MM-DD]** to **[END_DATE_YYYY-MM-DD]**, in the location specified as **[TARGET_LOCATION_NAME_OR_CITY_STATE]** (if latitude/longitude are provided, use these: Lat: **[TARGET_LATITUDE]**, Lon: **[TARGET_LONGITUDE]**), please generate **[NUMBER_OF_PLANS_TO_GENERATE, e.g., 3]** distinct dating plan suggestions.

        **Constraints and Guidelines for Suggestions:**
        1.  **Creativity & Fun:** Plans should be engaging, memorable, and offer a good experience for a date.
        2.  **Budget:** All generated plans should aim for a moderate budget (conceptually "$$"), meaning they should be affordable yet offer good value, without being overly cheap or extravagant. This budget level should be *reflected in the choice of activities and venues*, but **do not** explicitly state "Budget: $$" in the `plan_description`.
        3.  **Interest Alignment:**
            *   Consider the following user interests: **[COMMA_SEPARATED_LIST_OF_INTERESTS, e.g., outdoors, arts & culture, foodie, nightlife, unique local events, live music, active/sports]**. Tailor suggestions specifically to these where possible. The plan should *embody* these interests.
            *   **Fallback:** If specific events or venues perfectly matching all listed user interests cannot be found for the specified weekend, you should create a creative and fun generic dating plan that is still appealing, suitable for the location, and adheres to the moderate budget. This plan should still sound exciting and fun, even if it's more general.
        4.  **Current & Specific:** Prioritize finding specific, current events, festivals, pop-ups, or unique local venues operating or happening during the specified weekend dates. If exact current events cannot be found, suggest appealing evergreen options or implement the fallback generic plan.
        5.  **Location Details:** For each place or event mentioned within a plan, you MUST provide its name, precise latitude, precise longitude, and a brief, helpful description.

        **Output Format:**
        RETURN PLAN

    """,
    tools=[google_search],
)
print(f"Agent '{root_agent.name}' created.")

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

# Define Runners globally after agents are defined
runner = Runner(
    agent=root_agent,
    app_name=APP_NAME,
    session_service=session_service,  # Add session_service
)
print(f"Runner created for agent '{runner.agent.name}'.")

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
    """Sends a query to the agent and prints the final response."""
    print(f"\n>>> User Query: {query}")
    content = types.Content(role="user", parts=[types.Part(text=query)])
    final_response_text = "Agent did not produce a final response."

    chosen_agent_runner = runner
    stock_keywords = [
        "stock",
        "price of",
        "perform",
        "ticker",
        "symbol",
        "shares",
        "market",
        "漲跌",
        "股價",
    ]
    if any(keyword in query.lower() for keyword in stock_keywords):
        print(f"Routing to stock_agent for query: {query}")
        chosen_agent_runner = stock_runner
    else:
        print(f"Routing to root_agent for query: {query}")

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
                    break
            break  # Break from retry loop if successful
        except ValueError as e:
            if "Session not found" in str(e) and attempt < max_retries:
                print(
                    f"Attempt {attempt + 1}: Session {session_id} not found. Recreating session and retrying."
                )
                if user_id in active_sessions:  # Clean up potentially stale cache
                    del active_sessions[user_id]
                session_id = get_or_create_session(user_id)  # Get a new session_id
            else:
                print(f"An error occurred during agent execution: {str(e)}")
                final_response_text = f"Sorry, an error occurred: {str(e)}"
                break  # Break from retry loop on other errors or max retries exceeded
        except Exception as e:
            print(f"An unexpected error occurred during agent execution: {str(e)}")
            final_response_text = f"Sorry, an unexpected error occurred: {str(e)}"
            break  # Break from retry loop

    print(f"<<< Agent Response: {final_response_text}")
    return final_response_text


# Add lifespan event for session cleanup
@app.on_event("shutdown")
async def shutdown_event():
    await client_session.close()
    print("Client session closed.")
