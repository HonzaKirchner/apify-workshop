# Wired tech articles extractor

Example Actor to demonstrate how to use Crawlee on Apify platform. It scrapes the latest articles from [Wired about programming](https://www.wired.com/tag/programming/), generate their summary using OpenAI and charges users for each result.

#### Prerequisites
- Python (3.10 or higher)
- Apify CLI [installed](https://docs.apify.com/cli/docs/installation)
- [Apify account](https://console.apify.com/sign-in)

### Create an Actor from template

`$ apify create`
- give the Actor a name (`wired-tech-news-extractor`)
- select `Python` programming language
- select `Crawlee + BeautifulSoup` template
- `cd wired-tech-news-extractor` to newly created dictionary


> Actor file structure 
> ```text
> .actor/
> ├── actor.json # Actor config: name, version, env vars, runtime settings
> ├── dataset_schena.json # Structure and representation of data produced by an Actor
> ├── input_schema.json # Input validation & Console form definition
> └── output_schema.json # Specifies where an Actor stores its output
> src/
> └── main.py # Actor entry point and orchestrator
> storage/ # Local storage (mirrors Cloud during development)
> ├── datasets/ # Output items (JSON objects)
> ├── key_value_stores/ # Files, config, INPUT
> └── request_queues/ # Pending crawl requests
> Dockerfile # Container image definition
> ```
> For more information, see the [Actor definition](https://docs.apify.com/platform/actors/development/actor-definition) documentation.


### Analyze the page

Before writing any scraping code, analyzing the target website's structure is crucial for successful web scraping. Understanding how the page is built allows you to identify the correct CSS selectors, detect patterns, and ensure your scraper works reliably across multiple pages.

**Why page analysis matters:**
- Identifies repeating patterns and data structures across pages
- Helps you find the most stable selectors (avoiding dynamic class names)
- Reveals pagination mechanisms and navigation patterns
- Allows you to spot potential anti-scraping measures early

**How to analyze a page:**
1. **Open Developer Tools** (F12 or right-click → Inspect)
2. **Use the Element Picker** (Ctrl+Shift+C / Cmd+Shift+C) to hover over elements you want to scrape
3. **Examine the HTML structure** - look for semantic tags, data attributes, and unique identifiers
4. **Check multiple pages** - verify that the structure is consistent across different articles/products
5. **Look for static attributes** - attributes like `id` or `data-testid` are more stable than generated class names
6. **Test CSS selectors in Console** - use `document.querySelector()` to verify your selectors work
7. **Inspect Network tab** - sometimes data comes from API calls rather than rendered HTML

#### Article detail page

On individual article pages, we need to extract two key pieces of information:

1. **Article title** - Located in an `<h1>` tag with `data-testid="ContentHeaderHed"` attribute

![Article title](img/article_detail_title.png)

2. **Article content** - Found in a `<div>` with `data-testid="ArticlePageChunks"` attribute

![Article content](img/article_detail_content.png)

Notice how both elements use `data-testid` attributes - these are stable identifiers that are less likely to change than CSS classes, making our scraper more reliable.

#### Article list page

On the article listing page, we don't need to scrape any content directly. Instead, our goal is to collect all the article URLs so we can visit them later. 

Key observations:
- All article URLs follow the same pattern: `https://www.wired.com/story/**`
- This consistent URL structure allows us to use glob patterns to filter and enqueue only article links using the Crawlee's `enqueue_links()` method

![Article list links](img/article_list_links.png)

## Implementation

Now that we've analyzed the page structure and identified the data we need, let's translate this into working code. We'll build two route handlers: one to collect article URLs from listing pages, and another to extract content from individual articles.

### Extracting article links from listing pages

The default handler processes listing pages and discovers all article URLs. We use Crawlee's `enqueue_links()` method to automatically find and queue matching links:

```python
@crawler.router.default_handler
async def request_handler(context: BeautifulSoupCrawlingContext) -> None:
    await context.enqueue_links(
        include=[Glob("https://www.wired.com/story/**")],
        label="ARTICLE"
    )
```

**What's happening here:**
- `include=[Glob(...)]` - Filters links to match only URLs following the pattern `https://www.wired.com/story/**`
- `label="ARTICLE"` - Tags these requests so they'll be handled by our article detail handler
- Crawlee automatically discovers all matching links on the page and adds them to the request queue

### Extracting content from article pages

The article handler processes individual article pages. We use Beautiful Soup's CSS selectors to extract the data we identified during page analysis:

```python
@crawler.router.handler(label="ARTICLE")
async def article_handler(context: BeautifulSoupCrawlingContext) -> None:
    title_el = context.soup.select_one('h1[data-testid="ContentHeaderHed"]')
    content_el = context.soup.select_one('div[data-testid="ArticlePageChunks"]')

    # Extract text and handle missing elements gracefully
    data = {
        'title': title_el.get_text(strip=True) if title_el else None,
        'content': content_el.get_text(strip=True) if content_el else None,
        'url': context.request.url,
    }

    # Save the extracted data to the dataset
    await context.push_data(data)
```

**Key points:**
- `@crawler.router.handler(label="ARTICLE")` - Processes only requests labeled as "ARTICLE"
- `context.soup.select_one()` - Beautiful Soup method to find elements using CSS selectors
- `.get_text(strip=True)` - Extracts text content and removes leading/trailing whitespace
- `await context.push_data(data)` - Saves the extracted data to the default dataset

**Try it!** 
```bash
apify run
```

After running, check the `storage/datasets/default/` folder to see your scraped data!

## Making the Actor configurable

### Defining user input

Currently, the scraper only processes a single page of results. To make it flexible and allow users to specify how many articles to scrape, we'll add configurable input parameters.

**Step 1: Create the input schema**

Edit `.actor/input_schema.json` to define what parameters users can configure:

```json
{
    "title": "Wired Tech Articles Scraper Input",
    "type": "object",
    "schemaVersion": 1,
    "properties": {
        "maxArticles": {
            "title": "Maximum Articles",
            "type": "integer",
            "description": "Maximum number of articles to scrape (24 articles per page)",
            "default": 24,
            "minimum": 1,
            "maximum": 500
        }
    },
    "required": []
}
```

This schema:
- Creates a form field in the Apify Console UI
- Validates user input (must be between 1-500)
- Sets a sensible default value (24)

> **Note:** For local testing, update `storage/key_value_stores/default/INPUT.json` with your test input
> ```json
>{
>    "maxArticles": 48
>}
> ```
> This simulates the Apify Console's input form.

**Step 2: Handle pagination**

Wired displays 24 articles per page. When users click "More stories", the URL changes to include a page parameter:

![Pagination URL pattern](img/article_list_pagination.png)

We need to calculate how many pages to visit based on the user's `maxArticles` input. Add this code to `src/main.py`:

```python
    ARTICLES_PER_PAGE = 24

    # Retrieve user input
    actor_input = await Actor.get_input() or {}
    max_articles = actor_input.get("maxArticles", ARTICLES_PER_PAGE)

    # Calculate how many listing pages we need to visit
    total_pages = ceil(max_articles / ARTICLES_PER_PAGE)

    base_url = "https://www.wired.com/tag/programming"

    # Generate URLs for all required pages
    start_urls = [
        base_url if page == 1 else f"{base_url}/?page={page}"
        for page in range(1, total_pages + 1)
    ]

    # Limit total requests: listing pages + article detail pages
    crawler = BeautifulSoupCrawler(max_requests_per_crawl=max_articles + total_pages)
```

### Defining Actor output

Update `.actor/dataset_schema.json` so it describes the output expected by the Actor.

```json
{
    "actorSpecification": 1,
    "fields": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Article title"
            },
            "content": {
                "type": "string",
                "description": "Full article text"
            },
            "url": {
                "type": "string",
                "description": "Article URL"
            }
        }
    },
    "views": {
        "overview": {
            "title": "Overview",
            "transformation": {
                "fields": ["title", "url", "content"]
            },
            "display": {
                "component": "table",
                "properties": {
                    "title": {
                        "label": "Title",
                        "format": "text"
                    },
                    "content": {
                        "label": "Content",
                        "format": "text"
                    },
                    "url": {
                        "label": "URL",
                        "format": "link"
                    }
                }
            }
        }
    }
}
```

## Deploying to Apify Platform

Once your Actor works locally, it's time to deploy it to the cloud where it can run on Apify's infrastructure.

### Authentication and deployment

```bash
# Log in to your Apify account (one-time setup)
$ apify login

# Deploy your Actor to the platform
$ apify push
```

After deployment, your Actor will be available in the [Apify Console](https://console.apify.com/actors?tab=my) where you can:
- Run it with different input configurations
- Schedule periodic runs (daily, weekly, etc.)
- Monitor runs, logs, and performance metrics
- Set up webhooks and integrations
- Share it privately or publish it to the Apify Store

## Adding Premium Features

Let's enhance the Actor by adding AI-powered article summaries using OpenAI. We'll also implement event-based charging so users pay for the AI processing.

### Step 1: Install OpenAI SDK

Add the OpenAI package to your project:

```bash
$ python -m pip install openai
```

Update `requirements.txt` to include the dependency:
```
openai>=1.0.0
```

### Step 2: Configure API credentials

**For local development:**
```bash
$ export OPENAI_API_KEY='sk-your-api-key-here'
```

**For production (Apify Platform):**
1. Go to your Actor source tab in the Apify Console
2. Add a new variable to **Environment variables** section:
   - **Key:** `OPENAI_API_KEY`
   - **Value:** Your OpenAI API key
   - **Secret:** ✓ (checked - this encrypts the value)



### Step 4: Update dataset schema

Update `.actor/dataset_schema.json` so it includes the new `summary` field.

### Step 5: Modify the article handler

Update your article handler in `src/main.py` to generate summaries:

```python
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
        await Actor.charge('article_summary')
        
```

### Step 6: Sync the changes

`$ apify push`

### Step 7: Configure usage-based pricing

To charge users for AI summaries:

1. Go to your Actor in the Apify Console
2. Navigate to **Settings → Pricing**
3. Set pricing:


This allows transparent, usage-based billing where users only pay for summaries they request.

### Step 8: Test and publish the Actor