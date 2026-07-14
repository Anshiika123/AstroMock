"""astromock-mcp — MCP server exposing Vedic astrology calculation tools.

Runs over stdio by default, so it can be plugged directly into Claude
Desktop or any other MCP client. Pass --http to instead serve the
Streamable HTTP transport (e.g. for the ASTRO-MOCK Flask app to call
remotely).
"""

import argparse
import asyncio
import json
from contextlib import asynccontextmanager

import mcp.types as types
import uvicorn
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Mount

# single source of truth for the interpretation prompt: packages/core
from interpretation_engine import PROMPT_PATH as INTERPRETATION_PROMPT_PATH

from tools import (
    calculate_dasha,
    calculate_kundali,
    calculate_navamsa,
    generate_horoscope_tool,
    get_current_transits,
    get_question_context,
)
from tools.horoscope_tool import build_guidance_instructions

server = Server("astromock-mcp")

BIRTH_DATA_SCHEMA = {
    "type": "object",
    "properties": {
        "date_of_birth": {
            "type": "string",
            "description": "Date of birth in YYYY-MM-DD format, e.g. '1995-08-21'",
        },
        "time_of_birth": {
            "type": "string",
            "description": "Local time of birth in 24-hour HH:MM format, e.g. '14:35'",
        },
        "latitude": {
            "type": "number",
            "description": "Birthplace latitude in decimal degrees (north positive), e.g. 28.6139 for Delhi",
        },
        "longitude": {
            "type": "number",
            "description": "Birthplace longitude in decimal degrees (east positive), e.g. 77.2090 for Delhi",
        },
        "timezone_str": {
            "type": "string",
            "description": "IANA timezone of the birthplace, e.g. 'Asia/Kolkata'",
        },
        "unknown_time": {
            "type": "boolean",
            "description": (
                "Set true if the birth time is uncertain/unknown. The "
                "ascendant (lagna) and house placements are then omitted, "
                "since they cannot be computed reliably. Default false."
            ),
        },
    },
    "required": [
        "date_of_birth",
        "time_of_birth",
        "latitude",
        "longitude",
        "timezone_str",
    ],
}


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="calculate_kundali",
            description=(
                "Calculate a Vedic astrology birth chart (D-1 / Rashi kundali) "
                "from birth date, time and place. Uses the sidereal zodiac with "
                "Lahiri ayanamsha, Whole Sign houses and mean lunar nodes. "
                "Returns the ascendant (lagna) and all nine grahas (Sun through "
                "Saturn plus Rahu/Ketu) with their sign, degree, nakshatra, "
                "pada, house placement and retrograde status. Use this whenever "
                "a user asks about their kundali, birth chart, lagna, planetary "
                "positions or nakshatras."
            ),
            inputSchema=BIRTH_DATA_SCHEMA,
        ),
        types.Tool(
            name="calculate_navamsa",
            description=(
                "Calculate the Vedic D-9 (Navamsa) divisional chart from birth "
                "date, time and place. Same calculation basis as "
                "calculate_kundali (sidereal, Lahiri ayanamsha). Returns each "
                "planet's navamsa sign and house from the navamsa lagna. Use "
                "this for questions about marriage, spouse, inner strength of "
                "planets, or whenever a navamsa/D-9 chart is requested."
            ),
            inputSchema=BIRTH_DATA_SCHEMA,
        ),
        types.Tool(
            name="calculate_dasha",
            description=(
                "Calculate the Vimshottari Dasha timeline (Mahadashas covering "
                "120 years from birth, with calendar dates) from birth data. "
                "Includes the birth-time dasha balance, and for the current "
                "Mahadasha (as of today or an optional as_of date) the full "
                "Antardasha breakdown with the active one marked. Use this for "
                "ANY timing question — when will something happen, which "
                "planetary period is running, dasha/antardasha queries."
            ),
            inputSchema={
                **BIRTH_DATA_SCHEMA,
                "properties": {
                    **BIRTH_DATA_SCHEMA["properties"],
                    "as_of": {
                        "type": "string",
                        "description": ("Optional reference date YYYY-MM-DD for "
                                        "'current' periods; defaults to today."),
                    },
                },
            },
        ),
        types.Tool(
            name="get_current_transits",
            description=(
                "Current (or given date's) sidereal transit signs of all 9 "
                "grahas — the Gochar. If the native's Moon sign (rashi) is "
                "provided, also returns each planet's house counted from the "
                "Moon and whether Sade Sati is active (Saturn in 12th/1st/2nd "
                "from the Moon). Use for today's horoscope, gochar, Sade Sati "
                "and transit questions. No birth data needed — pass moon_sign "
                "from a previous calculate_kundali result (rashi.sign)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "moon_sign": {
                        "type": "string",
                        "description": ("Natal Moon sign (rashi), e.g. "
                                        "'Scorpio'. Optional but needed for "
                                        "house-from-Moon and Sade Sati."),
                    },
                    "target_date": {
                        "type": "string",
                        "description": ("Date YYYY-MM-DD for the transits; "
                                        "defaults to today."),
                    },
                },
            },
        ),
        types.Tool(
            name="get_question_context",
            description=(
                "Route a life-area question (English or Hinglish: career/"
                "naukri, marriage/shaadi, wealth/paisa, health/sehat, "
                "education/padhai, children/santan, family/parivar, "
                "personality/swabhav) to its Vedic houses, analyze those "
                "houses in the native's chart (sign, occupant planets, house "
                "lord and the lord's placement), and retrieve the most "
                "relevant classical passages from BPHS (with page numbers). "
                "Call this FIRST for any 'how is my X' / 'will I get Y' "
                "question, then interpret using the vedic-interpretation "
                "prompt rules."
            ),
            inputSchema={
                **BIRTH_DATA_SCHEMA,
                "properties": {
                    **BIRTH_DATA_SCHEMA["properties"],
                    "question": {
                        "type": "string",
                        "description": "The user's question, verbatim.",
                    },
                },
                "required": BIRTH_DATA_SCHEMA["required"] + ["question"],
            },
        ),
        types.Tool(
            name="generate_horoscope",
            description=(
                "Build everything needed to write a transit-based horoscope "
                "(daily / 2-week / 6-month) for a natal Moon sign: the "
                "timeframe's focus-planet transit facts (today: Moon + Sun "
                "aspect; 2weeks: Sun/Mercury/Venus with upcoming sign "
                "changes; 6months: Jupiter/Saturn/Rahu/Ketu with Sade Sati), "
                "relevant classical BPHS passages, and a ready-to-use "
                "system_prompt + suggested_prompt. This tool does NOT write "
                "the horoscope text — after calling it, YOU write the "
                "horoscope by following the returned prompts (warm "
                "astrologer tone, the given word target, grounded in the "
                "returned facts only). Only moon_sign and timeframe are "
                "required; transits and Sade Sati are computed automatically "
                "if not supplied."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "moon_sign": {
                        "type": "string",
                        "description": ("Natal Moon sign (rashi), e.g. "
                                        "'Scorpio' — rashi.sign from "
                                        "calculate_kundali."),
                    },
                    "timeframe": {
                        "type": "string",
                        "enum": ["today", "2weeks", "6months"],
                        "description": ("Horoscope window: 'today' (~100 "
                                        "words), '2weeks' (~200), "
                                        "'6months' (~300)."),
                    },
                    "transit_data": {
                        "type": "object",
                        "description": ("Optional: a get_current_transits "
                                        "result to reuse. Omit to compute "
                                        "today's transits automatically."),
                    },
                    "sade_sati_status": {
                        "type": "boolean",
                        "description": ("Optional: whether Sade Sati is "
                                        "active. Omit to compute it from "
                                        "moon_sign automatically."),
                    },
                },
                "required": ["moon_sign", "timeframe"],
            },
        ),
    ]


def _birth_kwargs(arguments: dict) -> dict:
    return {
        "date_of_birth": arguments["date_of_birth"],
        "time_of_birth": arguments["time_of_birth"],
        "latitude": float(arguments["latitude"]),
        "longitude": float(arguments["longitude"]),
        "timezone_str": arguments["timezone_str"],
        "unknown_time": bool(arguments.get("unknown_time", False)),
    }


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "calculate_kundali":
        result = calculate_kundali(**_birth_kwargs(arguments))
    elif name == "calculate_navamsa":
        result = calculate_navamsa(**_birth_kwargs(arguments))
    elif name == "calculate_dasha":
        result = calculate_dasha(**_birth_kwargs(arguments),
                                 as_of=arguments.get("as_of"))
    elif name == "get_current_transits":
        result = get_current_transits(
            moon_sign=arguments.get("moon_sign"),
            target_date=arguments.get("target_date"),
        )
    elif name == "get_question_context":
        result = get_question_context(question=arguments["question"],
                                      **_birth_kwargs(arguments))
    elif name == "generate_horoscope":
        transit_data = arguments.get("transit_data")
        sade_sati = arguments.get("sade_sati_status")
        if transit_data is None or sade_sati is None:
            computed = get_current_transits(moon_sign=arguments["moon_sign"])
            transit_data = transit_data or computed
            if sade_sati is None:
                sade_sati = computed["sade_sati_status"]
        result = generate_horoscope_tool(
            moon_sign=arguments["moon_sign"],
            sade_sati_status=bool(sade_sati),
            transit_data=transit_data,
            timeframe=arguments["timeframe"],
        )
    else:
        raise ValueError(f"Unknown tool: {name}")

    return [types.TextContent(type="text", text=json.dumps(result, indent=2))]


@server.list_prompts()
async def list_prompts() -> list[types.Prompt]:
    return [
        types.Prompt(
            name="vedic-interpretation",
            description=(
                "Interpretation rules for answering astrology questions from "
                "calculated chart data: never invent placements, cite "
                "reasoning, use non-deterministic language, structured "
                "Summary/Factors/Interpretation/References/Confidence format."
            ),
        ),
        types.Prompt(
            name="horoscope-guidance",
            description=(
                'Reader-friendly "Your Guidance" horoscope workflow: fetch '
                "grounded transit facts via the generate_horoscope tool, "
                "then write four short sections (How your period looks / "
                "What to lean into / What to avoid / Helpful note) — no "
                "technical planet tables, no scary wording, one uplifting "
                "thread, one kind caution, one practical suggestion."
            ),
            arguments=[
                types.PromptArgument(
                    name="timeframe",
                    description="today | 2weeks | 6months",
                    required=True,
                ),
                types.PromptArgument(
                    name="sign",
                    description="Natal Moon sign (rashi), e.g. 'Scorpio'",
                    required=True,
                ),
                types.PromptArgument(
                    name="tone",
                    description=("gentle | practical | motivational "
                                 "(default gentle)"),
                    required=False,
                ),
                types.PromptArgument(
                    name="focus",
                    description=("overall | career | love | health "
                                 "(default overall)"),
                    required=False,
                ),
            ],
        ),
    ]


@server.get_prompt()
async def get_prompt(name: str, arguments: dict | None) -> types.GetPromptResult:
    if name == "vedic-interpretation":
        text = INTERPRETATION_PROMPT_PATH.read_text(encoding="utf-8")
    elif name == "horoscope-guidance":
        args = arguments or {}
        for required in ("timeframe", "sign"):
            if not args.get(required):
                raise ValueError(
                    f"horoscope-guidance needs the '{required}' argument")
        text = build_guidance_instructions(
            sign=args["sign"].strip().capitalize(),
            timeframe=args["timeframe"].strip(),
            tone=(args.get("tone") or "gentle").strip().lower(),
            focus=(args.get("focus") or "overall").strip().lower(),
        )
    else:
        raise ValueError(f"Unknown prompt: {name}")

    return types.GetPromptResult(
        messages=[
            types.PromptMessage(
                role="user",
                content=types.TextContent(type="text", text=text),
            )
        ]
    )


def build_http_app() -> Starlette:
    session_manager = StreamableHTTPSessionManager(app=server, stateless=True)

    @asynccontextmanager
    async def lifespan(app: Starlette):
        async with session_manager.run():
            yield

    return Starlette(
        routes=[Mount("/mcp", app=session_manager.handle_request)],
        lifespan=lifespan,
    )


async def main_stdio() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream, server.create_initialization_options()
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="astromock-mcp server")
    parser.add_argument("--http", action="store_true",
                        help="Serve Streamable HTTP instead of stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if args.http:
        uvicorn.run(build_http_app(), host=args.host, port=args.port)
    else:
        asyncio.run(main_stdio())


if __name__ == "__main__":
    main()
