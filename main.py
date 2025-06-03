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

# Import arxiv agent tools
from multi_tool_agent.arxiv_agent import (
    search_arxiv_papers,
    summarize_arxiv_paper,
    answer_paper_question,
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

# --- ArXiv Agent Definition ---
root_agent = Agent(
    name="arxiv_agent",
    model="gemini-2.0-flash",  # Consistent with previous agent's model choice
    description="Agent specialized in searching arXiv, summarizing papers, and answering questions about them.",
    instruction="""
        You are an AI assistant specializing in interacting with the arXiv repository.
        Users can ask you to:
        1. Search for papers on arXiv based on a query. Use the `search_arxiv_papers` tool.
        2. Summarize a specific arXiv paper when given its URL or arXiv ID. Use the `summarize_arxiv_paper` tool. The summary will be the paper's abstract.
        3. Answer questions about a specific arXiv paper. Use the `answer_paper_question` tool. This tool will try to find relevant information in the paper's abstract.

        When a user provides an arXiv link or ID and asks for a summary, use `summarize_arxiv_paper`.
        When a user provides an arXiv link or ID and asks a specific question about it, use `answer_paper_question`.
        When a user provides a general query for papers, use `search_arxiv_papers`.

        Provide clear and concise answers. If a tool returns an error or no information, inform the user politely.
        When providing paper details, always try to include title, authors, summary/abstract, and arXiv ID.

        Reply in zh-TW.
    """,
    tools=[
        search_arxiv_papers,
        summarize_arxiv_paper,
        answer_paper_question,
    ],
)
print(f"Agent '{root_agent.name}' created.")

APP_NAME = "linebot_adk_app"

# Key Concept: Runner orchestrates the agent execution loop.
runner = Runner(
    agent=root_agent,  # The agent we want to run
    app_name=APP_NAME,  # Associates runs with our app
    session_service=session_service,  # Uses our session manager
)
print(f"Runner created for agent '{runner.agent.name}'.")


async def get_or_create_session(user_id):
    if user_id not in active_sessions:
        # Create a new session for this user
        session_id = f"session_{user_id}"
        session = await session_service.create_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id
        )
        active_sessions[user_id] = session_id
        print(
            f"New session created: App='{APP_NAME}', User='{user_id}', Session='{session.id}'"
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

            # --- Hugging Face paper URL auto-convert to arXiv ---
            import re

            hf_paper_pattern = r"https://huggingface.co/papers/(\\d{4}\\.\\d{5})"
            match = re.search(hf_paper_pattern, msg)
            if match:
                arxiv_id = match.group(1)
                msg = f"arXiv:{arxiv_id}"
                print(
                    f"Detected Hugging Face paper URL. Converted to arXiv ID: {arxiv_id}"
                )
            # ---------------------------------------------------

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
    session_id = await get_or_create_session(user_id)

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
        if "Session not found" in str(e):
            print(
                f"Initial 'Session not found' error: {str(e)}. Attempting to recreate session and retry."
            )
            active_sessions.pop(user_id, None)
            new_session_id = await get_or_create_session(
                user_id
            )  # Renamed to avoid confusion
            print(f"Retrying with new session: {new_session_id}")
            try:
                # Initialize final_response_text for the retry attempt
                retry_final_response_text = (
                    "Agent did not produce a final response on retry."
                )
                async for event in runner.run_async(
                    user_id=user_id, session_id=new_session_id, new_message=content
                ):
                    if event.is_final_response():
                        if event.content and event.content.parts:
                            retry_final_response_text = event.content.parts[0].text
                        elif event.actions and event.actions.escalate:
                            retry_final_response_text = f"Agent escalated on retry: {event.error_message or 'No specific message.'}"
                        break
                final_response_text = (
                    retry_final_response_text  # Assign retry result here
                )
            except Exception as e2:
                print(f"Error during retry attempt: {str(e2)}")
                final_response_text = (
                    f"Sorry, I encountered an error after a session issue: {str(e2)}"
                )
        else:
            # This is for ValueErrors not related to "Session not found"
            print(
                f"Error processing request (non-session related ValueError): {str(e)}"
            )
            final_response_text = f"Sorry, I encountered an error: {str(e)}"
    except Exception as ex:
        # Catch any other unexpected errors
        print(f"An unexpected error occurred: {str(ex)}")
        final_response_text = f"Sorry, an unexpected error occurred: {str(ex)}"

    print(f"<<< Agent Response: {final_response_text}")
    return final_response_text
