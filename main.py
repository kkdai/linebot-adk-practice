import os
import sys
import asyncio
from io import BytesIO

import aiohttp
from fastapi import Request, FastAPI, HTTPException
from zoneinfo import ZoneInfo

from linebot.models import MessageEvent, TextSendMessage
from linebot.exceptions import InvalidSignatureError
from linebot.aiohttp_async_http_client import AiohttpAsyncHttpClient
from linebot import AsyncLineBotApi, WebhookParser
from multi_tool_agent.agent import (
    get_weather,
    get_current_time,
)
from google.adk.agents import Agent
from google.adk.tools import google_search

# Import necessary session components
from google.adk.sessions import InMemorySessionService
from google.adk.runners import Runner
from google.genai import types

# OpenAI Agent configuration
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
elif not GOOGLE_API_KEY:  # Original check for GOOGLE_API_KEY when USE_VERTEX is false
    raise ValueError("Please set GOOGLE_API_KEY via env var or code.")

# Initialize the FastAPI app for LINEBot
app = FastAPI()
session = aiohttp.ClientSession()
async_http_client = AiohttpAsyncHttpClient(session)
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

# --- Session Management ---
# Key Concept: SessionService stores conversation history & state.
# InMemorySessionService is simple, non-persistent storage for this tutorial.
session_service = InMemorySessionService()

# Define constants for identifying the interaction context
APP_NAME = "linebot_adk_app"
# Instead of fixed user_id and session_id, we'll now manage them dynamically

# Dictionary to track active sessions
active_sessions = {}

# Create a function to get or create a session for a user


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


# Key Concept: Runner orchestrates the agent execution loop.
runner = Runner(
    agent=root_agent,  # The agent we want to run
    app_name=APP_NAME,  # Associates runs with our app
    session_service=session_service,  # Uses our session manager
)
print(f"Runner created for agent '{runner.agent.name}'.")


@app.post("/")
async def handle_callback(request: Request):
    signature = request.headers["X-Line-Signature"]

    # get request body as text
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
            return "OK"
        else:
            continue

    return "OK"


async def call_agent_async(query: str, user_id: str) -> str:
    """Sends a query to the agent and prints the final response."""
    print(f"\n>>> User Query: {query}")

    # Get or create a session for this user
    session_id = get_or_create_session(user_id)

    # Prepare the user's message in ADK format
    content = types.Content(role="user", parts=[types.Part(text=query)])

    final_response_text = "Agent did not produce a final response."  # Default

    try:
        # Key Concept: run_async executes the agent logic and yields Events.
        # We iterate through events to find the final answer.
        async for event in runner.run_async(
            user_id=user_id, session_id=session_id, new_message=content
        ):
            # You can uncomment the line below to see *all* events during execution
            # print(f"  [Event] Author: {event.author}, Type: {type(event).__name__}, Final: {event.is_final_response()}, Content: {event.content}")

            # Key Concept: is_final_response() marks the concluding message for the turn.
            if event.is_final_response():
                if event.content and event.content.parts:
                    # Assuming text response in the first part
                    final_response_text = event.content.parts[0].text
                elif (
                    event.actions and event.actions.escalate
                ):  # Handle potential errors/escalations
                    final_response_text = f"Agent escalated: {event.error_message or 'No specific message.'}"
                # Add more checks here if needed (e.g., specific error codes)
                break  # Stop processing events once the final response is found
    except ValueError as e:
        # Handle errors, especially session not found
        print(f"Error processing request: {str(e)}")
        # Recreate session if it was lost
        if "Session not found" in str(e):
            active_sessions.pop(user_id, None)  # Remove the invalid session
            session_id = get_or_create_session(user_id)  # Create a new one
            # Try again with the new session
            try:
                async for event in runner.run_async(
                    user_id=user_id, session_id=session_id, new_message=content
                ):
                    # Same event handling code as above
                    if event.is_final_response():
                        if event.content and event.content.parts:
                            final_response_text = event.content.parts[0].text
                        elif event.actions and event.actions.escalate:
                            final_response_text = f"Agent escalated: {event.error_message or 'No specific message.'}"
                        break
            except Exception as e2:
                final_response_text = f"Sorry, I encountered an error: {str(e2)}"
        else:
            final_response_text = f"Sorry, I encountered an error: {str(e)}"

    print(f"<<< Agent Response: {final_response_text}")
    return final_response_text
