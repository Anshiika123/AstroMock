"""Quick verification client: spawns server.py over stdio, lists the
registered tools, and calls both with sample birth data."""

import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# ASTRO-MOCK's verified test case: Saharanpur, 2004-09-21 05:30 IST
# -> Leo Ascendant, Scorpio Moon in Jyeshtha nakshatra
SAMPLE_ARGS = {
    "date_of_birth": "2004-09-21",
    "time_of_birth": "05:30",
    "latitude": 29.9680,
    "longitude": 77.5552,
    "timezone_str": "Asia/Kolkata",
}


async def main() -> None:
    params = StdioServerParameters(command=sys.executable, args=["server.py"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print(f"Connected to: {init.serverInfo.name} v{init.serverInfo.version}\n")

            tools = await session.list_tools()
            print(f"Registered tools ({len(tools.tools)}):")
            for tool in tools.tools:
                print(f"  - {tool.name}: {tool.description[:80]}...")

            prompts = await session.list_prompts()
            print(f"\nRegistered prompts ({len(prompts.prompts)}):")
            for prompt in prompts.prompts:
                print(f"  - {prompt.name}: {prompt.description[:80]}...")

            for name in ("calculate_kundali", "calculate_navamsa",
                         "calculate_dasha"):
                print(f"\n--- {name}({SAMPLE_ARGS['date_of_birth']} "
                      f"{SAMPLE_ARGS['time_of_birth']} Saharanpur) ---")
                result = await session.call_tool(name, SAMPLE_ARGS)
                print(result.content[0].text[:1200])

            print("\n--- get_current_transits(moon_sign='Scorpio') ---")
            result = await session.call_tool(
                "get_current_transits", {"moon_sign": "Scorpio"})
            print(result.content[0].text[:1200])

            print("\n--- get_question_context('kya mera career acha hoga') ---")
            result = await session.call_tool(
                "get_question_context",
                {**SAMPLE_ARGS, "question": "kya mera career acha hoga"})
            print(result.content[0].text[:1500])

            print("\n--- generate_horoscope(Scorpio, 6months) ---")
            result = await session.call_tool(
                "generate_horoscope",
                {"moon_sign": "Scorpio", "timeframe": "6months"})
            print(result.content[0].text[:800])

            print("\n--- prompt: vedic-interpretation (first 200 chars) ---")
            p = await session.get_prompt("vedic-interpretation", {})
            print(p.messages[0].content.text[:200])

            print("\n--- prompt: horoscope-guidance (first 300 chars) ---")
            p = await session.get_prompt(
                "horoscope-guidance",
                {"timeframe": "today", "sign": "Scorpio"})
            print(p.messages[0].content.text[:300])


if __name__ == "__main__":
    asyncio.run(main())
