import asyncio

from dotenv import load_dotenv
from openai import AsyncOpenAI
from tqdm.asyncio import tqdm

from sync_db import create_con, get_collection

load_dotenv()

async def create_embedding(client, id, text):
    response = await client.embeddings.create(
        input=text,
        model="text-embedding-3-small"
    )
    embedding = response.data[0].embedding
    return (id, embedding)

async def get_embeddings():
    con, cur = create_con()
    col = get_collection(con, cur)
    client = AsyncOpenAI()
    coroutines = [create_embedding(client, *record) for record in col]
    embeddings = await tqdm.gather(*coroutines)
    return embeddings

if __name__ == "__main__":
    embeddings = asyncio.run(get_embeddings())
    print(embeddings)
