from openai import OpenAI
import chainlit as cl
from dotenv import load_dotenv

load_dotenv()
model = "gpt-4o"  # or "gpt-4o", "gpt-4o-mini", "gpt-4o-mini-preview", etc.

client = OpenAI()

prompt = ""

with open("PROMPT.md", "r") as f:
    prompt = f.read()

@cl.on_chat_start
async def start():
    cl.user_session.set("history", [
        {"role": "system", "content": prompt}
    ])

@cl.on_message
async def main(message: cl.Message):
    history = cl.user_session.get("history")
    history.append({"role": "user", "content": message.content})

    response = client.responses.create(
        model=model,
        input=history,
    )

    history.append({
        "role": "assistant",
        "content": response.output_text,
    })

    await cl.Message(response.output_text).send()