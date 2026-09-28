# agent.py
import asyncio
import os
import random
import time

import httpx
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from google import genai
from google.genai import errors, types

load_dotenv()
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
MAX_STEPS = 8   # loop guard: stop runaway investigations
MAX_ATTEMPTS = 5   # per model call, for transient errors

SYSTEM_PROMPT = """You are a git-history investigator for one repository.
Rules:
- Use the FEWEST tool calls that answer the question. Most questions need 2-4.
- Once you have identified the relevant commit(s) and seen what changed, STOP
  investigating and write your answer.
- Do not search for extra background unless the question asks for it.
- If a tool returns nothing useful, do not retry with near-synonyms; use a
  different tool or answer with what you have.
- Always finish with a written answer. Keep it concise.
- Only mention something you could NOT verify if something was actually left
  unverified. Do not write a "could not verify" section otherwise.
- Never invent commit hashes, authors or dates; only report what tool results show."""


def mcp_tools_to_gemini(mcp_tools):
    return [
        types.FunctionDeclaration(
            name=t.name,
            description=t.description or "",
            parameters=t.inputSchema,
        )
        for t in mcp_tools
    ]


def generate_with_retry(**kwargs):
    """Call Gemini, retrying network errors and transient API errors.

    Daily-quota errors are NOT retried: waiting seconds can't fix them.
    """
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return client.models.generate_content(**kwargs)

        except httpx.TransportError as e:
            # network hiccup: server disconnected, timeout, connection reset
            if attempt < MAX_ATTEMPTS:
                wait = 5 * attempt + random.uniform(0, 3)
                print(f"  [retry] network error ({type(e).__name__}), "
                      f"waiting {wait:.0f}s (attempt {attempt}/{MAX_ATTEMPTS})")
                time.sleep(wait)
            else:
                raise

        except errors.APIError as e:
            text = str(e) + str(getattr(e, "details", ""))
            daily_cap = "PerDay" in text   # waiting seconds won't fix a daily cap
            transient = e.code in (429, 500, 502, 503, 504) and not daily_cap
            if transient and attempt < MAX_ATTEMPTS:
                wait = min(15 * attempt, 60) + random.uniform(0, 5)
                print(f"  [retry] Gemini error {e.code}, "
                      f"waiting {wait:.0f}s (attempt {attempt}/{MAX_ATTEMPTS})")
                time.sleep(wait)
            else:
                raise


async def run_agent(question: str, verbose: bool = True) -> dict:
    tools_called = []
    tool_results = []   # raw text of every tool result, used for the grounding check
    final_answer = ""
    steps_used = 0

    if verbose:
        print(f"[model] {MODEL}")

    server_params = StdioServerParameters(command="python", args=["server.py"])
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            mcp_tools = (await session.list_tools()).tools
            gemini_tool = types.Tool(function_declarations=mcp_tools_to_gemini(mcp_tools))

            contents = [types.Content(role="user", parts=[types.Part(text=question)])]

            for step in range(MAX_STEPS):
                steps_used += 1
                last_step = step == MAX_STEPS - 1

                config = types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    tools=[gemini_tool],
                    thinking_config=types.ThinkingConfig(thinking_level="medium"),
                    # on the final step, forbid tool calls so the model MUST answer
                    tool_config=(
                        types.ToolConfig(
                            function_calling_config=types.FunctionCallingConfig(mode="NONE")
                        )
                        if last_step else None
                    ),
                )

                response = generate_with_retry(
                    model=MODEL,
                    contents=contents,
                    config=config,
                )

                candidate = response.candidates[0]

                # guard: the model can return nothing (e.g. blocked response)
                if not candidate.content or not candidate.content.parts:
                    final_answer = "Model returned no content."
                    break

                # append the model's turn exactly as returned (keeps any thought
                # signatures that newer Gemini models need for tool calling)
                contents.append(candidate.content)

                calls = [p.function_call for p in candidate.content.parts if p.function_call]
                if not calls:
                    final_answer = response.text or ""
                    if verbose:
                        print("\n=== FINAL ANSWER ===\n", final_answer)
                    break

                for fc in calls:
                    args = dict(fc.args)
                    tools_called.append({"tool": fc.name, "args": args})
                    result = await session.call_tool(fc.name, args)
                    result_text = result.content[0].text if result.content else ""
                    tool_results.append(result_text)
                    if verbose:
                        print(f"[investigating] {fc.name}({args})")
                        print(f"    -> {result_text[:120]!r}")
                    contents.append(types.Content(
                        role="user",
                        parts=[types.Part(function_response=types.FunctionResponse(
                            name=fc.name,
                            response={"result": result_text},
                        ))],
                    ))
            else:
                # for/else: runs only if the loop finished without `break`
                final_answer = "Stopped: reached the maximum number of investigation steps."
                if verbose:
                    print("\n=== STOPPED ===\n", final_answer)

    return {
        "question": question,
        "tools_called": tools_called,
        "tool_results": tool_results,
        "answer": final_answer,
        "steps": steps_used,
        "hit_step_cap": steps_used == MAX_STEPS,
    }


if __name__ == "__main__":
    question = (
        "Find the commit that introduced a significant change to setup.py "
        "and show what changed."
    )
    asyncio.run(run_agent(question))