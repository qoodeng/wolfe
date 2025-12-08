#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Hotel Reservation Agent - Pipecat Voice Agent

A secure, agentic AI for hotel bookings with authentication flow.

Uses:
- Deepgram (Speech-to-Text)
- OpenAI GPT-4o (LLM with Function Calling)
- Cartesia (Text-to-Speech)
"""

import os
import sys

# Add parent directory to path to import from app/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv
from loguru import logger
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.runner.types import DailyRunnerArguments, RunnerArguments, WebSocketRunnerArguments
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.base_transport import BaseTransport
from pipecat.transports.daily.transport import DailyParams, DailyTransport

# Import our hotel reservation tools
from app.tools import (
    check_account_status,
    get_guest_reservation,
    cancel_guest_reservation,
    make_new_reservation,
    edit_guest_reservation
)


# Load .env from project root
root_env = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env")
load_dotenv(root_env, override=True)


# === PIPECAT TOOL DECORATOR ===
def pipecat_tool(func):
    """
    Decorator that wraps tool functions for Pipecat compatibility.
    Pipecat passes FunctionCallParams; this extracts .arguments and calls result_callback with the result.
    """
    async def wrapper(params):
        logger.info(f"Tool called: {func.__name__} with args: {params.arguments}")
        try:
            result = await func(**params.arguments)
            logger.info(f"Tool {func.__name__} returned: {result}")
            
            # Format result as differently typed dicts for LLM
            if isinstance(result, bool):
                formatted = {"success": result}
            elif isinstance(result, str):
                formatted = {"result": result}
            elif isinstance(result, dict):
                formatted = result
            else:
                formatted = {"result": str(result)}
            
            # Call the result callback
            await params.result_callback(formatted)

        # Catch tool caused/related errors    
        except Exception as e:
            logger.error(f"Tool {func.__name__} error: {e}")
            await params.result_callback({"error": str(e)})
            
    return wrapper

# === SYSTEM PROMPT ===
SYSTEM_PROMPT = """You are a friendly and professional hotel reservation assistant. You work for a lovely boutique hotel and genuinely enjoy helping guests with their bookings.

## Your Personality
- Warm, patient, and conversational - like a real hotel concierge
- Use natural language, not robotic responses
- Express empathy ("I understand", "Of course", "I'd be happy to help")
- Keep responses concise but friendly - this is a phone call, not an email
- Use the guest's name when appropriate after you learn it

## Conversation Flow

**Step 1: Verify the Guest**
Before accessing any reservation details, you need their 5-digit account number. Ask for it naturally:
- "I'd be happy to help with that! Could I get your account number, please?"
- "Sure thing! What's the account number on your reservation?"

When they give it, use the `check_account_status` tool to verify it. If invalid, kindly ask them to double-check.

**Step 2: Help with Their Request**
Once verified, you can:
- Look up reservations with `get_guest_reservation`
- Make new bookings with `make_new_reservation`
- Cancel bookings with `cancel_guest_reservation`  
- Modify dates or room types with `edit_guest_reservation`

**Step 3: Confirm & Close**
Always confirm what you've done and ask if there's anything else. End warmly:
- "Is there anything else I can help you with today?"
- "You're all set! Have a wonderful stay with us."

## Important Guidelines
- Never skip the account verification step
- If something goes wrong, apologize and offer to try again
- If you don't understand, ask for clarification politely
- Keep the conversation flowing naturally - avoid long silences
"""


# === TOOL DEFINITIONS ===
tools = [
    {
        "type": "function",
        "function": {
            "name": "check_account_status",
            "description": "Checks if the provided 5-digit account is active and valid. MUST be called before any other tool.",
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {"type": "string", "description": "The 5-digit account number."}
                },
                "required": ["account_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_guest_reservation",
            "description": "Retrieves booking details for a verified account.",
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {"type": "string", "description": "The verified 5-digit account number."},
                    "search_name": {"type": "string", "description": "The name of the guest to search for."}
                },
                "required": ["account_id", "search_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_guest_reservation",
            "description": "Marks a booking as canceled.",
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {"type": "string", "description": "The verified 5-digit account number."},
                    "reservation_id": {"type": "integer", "description": "The ID of the reservation to cancel."}
                },
                "required": ["account_id", "reservation_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "make_new_reservation",
            "description": "Creates a new reservation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {"type": "string", "description": "The verified 5-digit account number."},
                    "guest_name": {"type": "string", "description": "Name of the guest."},
                    "check_in_date": {"type": "string", "description": "Check-in date (YYYY-MM-DD)."},
                    "room_type": {"type": "string", "description": "Type of room (e.g., King, Queen, Suite)."}
                },
                "required": ["account_id", "guest_name", "check_in_date", "room_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_guest_reservation",
            "description": "Edits an existing reservation's check-in date and/or room type. Only provide the fields you want to change.",
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {"type": "string", "description": "The verified 5-digit account number."},
                    "reservation_id": {"type": "integer", "description": "The ID of the reservation to edit."},
                    "new_check_in_date": {"type": "string", "description": "New check-in date (YYYY-MM-DD). Optional."},
                    "new_room_type": {"type": "string", "description": "New room type (e.g., King, Queen, Suite). Optional."}
                },
                "required": ["account_id", "reservation_id"]
            }
        }
    }
]


async def run_bot(transport: BaseTransport):
    """Main bot logic."""
    logger.info("Starting Hotel Reservation Agent")

    # Set up Speech-to-Text service
    stt = DeepgramSTTService(api_key=os.getenv("DEEPGRAM_API_KEY"))

    # Set up Text-to-Speech service
    tts = CartesiaTTSService(
        api_key=os.getenv("CARTESIA_API_KEY"), 
        voice_id=os.getenv("CARTESIA_VOICE_ID")
    )

    # LLM service (OpenAI)
    llm = OpenAILLMService(
        api_key=os.getenv("OPENAI_API_KEY"), 
        model=os.getenv("OPENAI_MODEL", "gpt-4o")
    )
    
    # Register tool callbacks (wrapped with the pipecat_tool decorator)
    llm.register_function("check_account_status", pipecat_tool(check_account_status))
    llm.register_function("get_guest_reservation", pipecat_tool(get_guest_reservation))
    llm.register_function("cancel_guest_reservation", pipecat_tool(cancel_guest_reservation))
    llm.register_function("make_new_reservation", pipecat_tool(make_new_reservation))
    llm.register_function("edit_guest_reservation", pipecat_tool(edit_guest_reservation))

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
    ]

    context = OpenAILLMContext(messages, tools)
    context_aggregator = llm.create_context_aggregator(context)

    # Pipeline
    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            context_aggregator.user(),
            llm,
            tts,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Client connected")
        # Greet the user upon connection
        messages.append({"role": "system", "content": "Greet the caller warmly as a Hotel Reservation Agent and ask how you can help with their hotel reservation today."})
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Client disconnected")
        await task.cancel()

    runner = PipelineRunner(handle_sigint=False)
    await runner.run(task)


async def bot(runner_args: RunnerArguments):
    """Main bot entry point."""
    transport = None

    match runner_args:
        case DailyRunnerArguments():
            transport = DailyTransport(
                runner_args.room_url,
                runner_args.token,
                "Hotel Agent 47",
                params=DailyParams(
                    audio_in_enabled=True,
                    audio_out_enabled=True,
                    vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2)),
                    turn_analyzer=LocalSmartTurnAnalyzerV3(),
                ),
            )
        case WebSocketRunnerArguments():
            # Twilio phone call support via WebSocket
            from pipecat.transports.websocket.fastapi import FastAPIWebsocketTransport, FastAPIWebsocketParams
            from pipecat.serializers.twilio import TwilioFrameSerializer
            from pipecat.runner.utils import parse_telephony_websocket
            
            # Parse Twilio's initial WebSocket message to extract stream_sid
            transport_type, call_data = await parse_telephony_websocket(runner_args.websocket)
            stream_sid = call_data.get("stream_id", "")
            call_sid = call_data.get("call_id")
            
            transport = FastAPIWebsocketTransport(
                websocket=runner_args.websocket,
                params=FastAPIWebsocketParams(
                    audio_in_enabled=True,
                    audio_out_enabled=True,
                    serializer=TwilioFrameSerializer(
                        stream_sid=stream_sid,
                        call_sid=call_sid,
                        account_sid=os.getenv("TWILIO_ACCOUNT_SID"),
                        auth_token=os.getenv("TWILIO_AUTH_TOKEN"),
                    ),
                    vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2)),
                    turn_analyzer=LocalSmartTurnAnalyzerV3(),
                ),
            )
        case _:
            logger.error(f"Unsupported runner arguments type: {type(runner_args)}")
            return

    await run_bot(transport)


if __name__ == "__main__":
    from pipecat.runner.run import main
    main()
