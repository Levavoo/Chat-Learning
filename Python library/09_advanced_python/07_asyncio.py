"""
Topic: Asyncio
Goal: Asynchronous programming
"""

import asyncio

async def task():
    print("Start")
    await asyncio.sleep(1)
    print("End")

async def main():
    await task()

asyncio.run(main())