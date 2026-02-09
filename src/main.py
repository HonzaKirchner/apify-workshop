"""Module defines the main entry point for the Apify Actor.

Feel free to modify this file to suit your specific needs.

To build Apify Actors, utilize the Apify SDK toolkit, read more at the official documentation:
https://docs.apify.com/sdk/python
"""

from __future__ import annotations

import asyncio

from math import ceil
from apify import Actor, Event
from crawlee.crawlers import BeautifulSoupCrawler, BeautifulSoupCrawlingContext
from crawlee import Glob
from openai import OpenAI

async def main() -> None:
    """Define a main entry point for the Apify Actor.

    This coroutine is executed using `asyncio.run()`, so it must remain an asynchronous function for proper execution.
    Asynchronous execution is required for communication with Apify platform, and it also enhances performance in
    the field of web scraping significantly.
    """
    # Enter the context of the Actor.
    async with Actor:
        client = OpenAI()

        # Handle graceful abort - Actor is being stopped by user or platform
        async def on_aborting() -> None:
            # Persist any state, do any cleanup you need, and terminate the Actor using
            # `await Actor.exit()` explicitly as soon as possible. This will help ensure that
            # the Actor is doing best effort to honor any potential limits on costs of a
            # single run set by the user.
            # Wait 1 second to allow Crawlee/SDK state persistence operations to complete
            # This is a temporary workaround until SDK implements proper state persistence in the aborting event
            await asyncio.sleep(1)
            await Actor.exit()

        Actor.on(Event.ABORTING, on_aborting)

        
        ARTICLES_PER_PAGE = 24
        actor_input = await Actor.get_input() or {}
        max_articles = actor_input.get("maxArticles", ARTICLES_PER_PAGE)
        total_pages = ceil(max_articles / ARTICLES_PER_PAGE)


        base_url = "https://www.wired.com/tag/programming"

        start_urls = [
            base_url if page == 1 else f"{base_url}/?page={page}"
            for page in range(1, total_pages + 1)
        ]

        crawler = BeautifulSoupCrawler(max_requests_per_crawl=max_articles + total_pages)

        # Define a request handler, which will be called for every request.
        @crawler.router.default_handler
        async def request_handler(context: BeautifulSoupCrawlingContext) -> None:
            """Default handler for processing the article list page."""
            url = context.request.url
            Actor.log.info(f'Scraping {url}...')

            # Enqueue additional links found on the current page.
            await context.enqueue_links(
                include=[Glob("https://www.wired.com/story/**"), ],
                label="ARTICLE",
                ) 
            
        @crawler.router.handler(label="ARTICLE")
        async def request_handler(context: BeautifulSoupCrawlingContext) -> None:
            """Handler for processing the article page."""
            context.log.info(f'Processing article {context.request.url} ...')

            title_el = context.soup.select_one('h1[data-testid="ContentHeaderHed"]')
            content_el = context.soup.select_one('div[data-testid="ArticlePageChunks"]')

            title = title_el.get_text(strip=True) if title_el else None
            content = content_el.get_text(strip=True) if content_el else None

            prompt = f"""
Your task is to summarize the content of the article in 3 sentences.
The original content of the article is:
{content}

Keep the answer simple and concise. Focus on the main points of the article, and avoid unnecessary details.
"""
            summary = (
                client.responses.create(
                    model="gpt-4.1-mini",
                    input=prompt
                )
                if content
                else None
            )

            data = {
                'title': title,
                'content': content,
                'url': context.request.url,
                'summary': summary.output_text if summary else None,
            }

            await context.push_data(data)

            if content:
                await Actor.charge(event_name="article_summary")


        await crawler.run(start_urls)


# TODO: AsyncOpenAI
# TODO: The content selector is not right
# TODO: Check the max_requests_per_crawl

