from notion_client import Client
from dateutil.parser import parse
from collections import defaultdict
import requests
import logging
from pathlib import Path
from dotenv import load_dotenv

import os
import json

logger = logging.getLogger(__name__)
import calendar
import datetime
from datetime import datetime, timedelta

# Load system.env and set environment variables
load_dotenv("system.env")

# Notion connection info
notion_version = os.getenv("NOTION_VERSION")
notion_token = os.getenv("NOTION_TOKEN")
notion_headers = {
    "Accept": "application/json",
    "Authorization": f"Bearer {notion_token}",
    "Content-Type": "application/json",
    "Notion-Version": notion_version
}
#notion_client = Client(auth=notion_token)

# Convert circled numbers (1-20) to bullets
def circlenum_to_dots(text):
    # Detect codepoints from 1 to 20 (circled) and replace each with a bullet
    for i in range(1, 21):
        text = text.replace(chr(0x245F + i), "・")
    return text

# Fetch a page by Notion page ID
def get_page(page_id):
    notion_client = Client(auth=notion_token)
    page = notion_client.pages.retrieve(page_id=page_id)
    return page

# Fetch the title field for a page ID
def get_title_by_id(pages, page_id, item):
    for page in pages:
        if page['id'] == page_id:
            prop = page.get('properties', {}).get(item) or {}
            title_arr = prop.get('title') or []
            if not title_arr:
                return ""
            first = title_arr[0] or {}
            text_obj = first.get('text') or {}
            content = text_obj.get('content')
            if content is not None:
                return content
            return first.get('plain_text', "") or ""
    return ""

# Fetch a number field for a page ID
def get_num_by_id(pages, page_id, item):
    for page in pages:
        if page['id'] == page_id:
            return page["properties"][item]["number"]

# Fetch a date field for a page ID
def get_date_by_id(pages, page_id, item):
    date = ""
    for page in pages:
        if page['id'] == page_id and item in page['properties'] and page['properties'][item]['date']:
            date = page['properties'][item]['date']['start'][:10]
            return date

# Fetch a rich-text field for a page ID
def get_rich_text_by_id(pages, page_id, item):
    for page in pages:
        if page['id'] == page_id:
            return page['properties'][item]['rich_text']

# Fetch a rich-text field as a plain string (stripping font settings and similar)
def get_rich_text_item_by_id(pages, page_id, item):
    rich_texts = get_rich_text_by_id(pages, page_id, item)
    content = ''.join([text['text']['content'] for text in rich_texts])
    return content

# Fetch a checkbox field for a page ID
def get_chk_by_id(pages, page_id, item):
    for page in pages:
        if page['id'] == page_id:
            return page["properties"][item]["checkbox"]

# Fetch the select (rating) field for a page ID
def get_select_by_id(pages, page_id, item):
    for page in pages:
        if page['id'] == page_id:
            sel = page['properties'][item].get('select')
            return sel['name'] if sel else None

# Fetch a multi-select field for a page ID (returns a list of names)
def get_multi_select_by_id(pages, page_id, item):
    for page in pages:
        if page['id'] == page_id:
            multi = page['properties'][item].get('multi_select', []) or []
            return [m.get('name') for m in multi if m.get('name')]
    return []

# Fetch the URL field for a page ID
def get_url_by_id(pages, page_id, item):
    for page in pages:
        if page['id'] == page_id:
            if page["properties"][item]["url"]:
                url = page["properties"][item]["url"]
            else:
                url = ""
            return url

# Fetch a field value dispatched by its data type
def get_notion_item_by_id(pages, page_id, item, item_type):
    item_data = ""
    if item_type == "title":
        item_data = get_title_by_id(pages, page_id, item)
    elif item_type == "number":
        item_data = get_num_by_id(pages, page_id, item)
    elif item_type == "date":
        item_data = get_date_by_id(pages, page_id, item)
    elif item_type == "rich_text":
        item_data = get_rich_text_item_by_id(pages, page_id, item)
    elif item_type == "chk":
        item_data = get_chk_by_id(pages, page_id, item)
    elif item_type == "select":
        item_data = get_select_by_id(pages, page_id, item)
    elif item_type == "multi_select":
        item_data = get_multi_select_by_id(pages, page_id, item)
    elif item_type == "url":
        item_data = get_url_by_id(pages, page_id, item)
    else:
        item_data = "item_type_error"  # For fixed values not in the Notion DB, the string from the Setting file is used
    if isinstance(item_data, str):
        item_data = circlenum_to_dots(item_data)
    return item_data

# Fetch all page IDs from a Notion database
def get_all_page_ids(database_id):
    has_more = True
    next_cursor = None
    all_results = []

    while has_more:
        payload = {}
        if next_cursor:
            payload["start_cursor"] = next_cursor

        response = requests.post(f"https://api.notion.com/v1/databases/{database_id}/query", headers=notion_headers, json=payload)
        response_json = response.json()

        if response.status_code != 200:
            logger.error(f"Error fetching page IDs. Response: {response_json}")
            return []

        all_results.extend(response_json["results"])
        has_more = response_json.get("has_more", False)
        next_cursor = response_json.get("next_cursor")

    return [result["id"] for result in all_results]

# Fetch all page IDs from a Notion database
def get_all_pages(database_id):
    has_more = True
    next_cursor = None
    all_results = []

    while has_more:
        payload = {}
        if next_cursor:
            payload["start_cursor"] = next_cursor

        response = requests.post(f"https://api.notion.com/v1/databases/{database_id}/query", headers=notion_headers, json=payload)
        response_json = response.json()

        if response.status_code != 200:
            logger.error(f"Error fetching page IDs. Response: {response_json}")
            return []

        all_results.extend(response_json["results"])
        has_more = response_json.get("has_more", False)
        next_cursor = response_json.get("next_cursor")

    return all_results

# Fetch confirmed pages from a Notion database
def get_pages_done(database_id, chk_dict=None, date_dict=None, category_dict=None):
    has_more = True
    next_cursor = None
    all_results = []

    while has_more:
        payload = {}
        if chk_dict is not None or date_dict is not None or category_dict is not None:
            payload = {"filter": {"and": []}}
            if chk_dict is not None:
                for chk_item, chk in chk_dict.items():
                    if isinstance(chk, bool):
                        payload["filter"]["and"].append({
                            "property": chk_item,
                            "checkbox": {
                                "equals": chk
                            }
                        })
                    elif isinstance(chk, str):
                        payload["filter"]["and"].append({
                            "property": chk_item,
                            "select": {
                                "equals": chk
                            }
                        })
            if date_dict is not None:
                for date_item, set_date in date_dict.items():
                    start_date = datetime.strptime(set_date[0], "%Y-%m-%d") if set_date[0] else datetime.strptime("1000-01-01", "%Y-%m-%d")
                    end_date = datetime.strptime(set_date[1], "%Y-%m-%d") if set_date[1] else datetime.strptime("9999-12-31", "%Y-%m-%d")
                    payload["filter"]["and"].append({
                        "and": [
                            {
                                "property": date_item,
                                "date": {
                                    "on_or_after": start_date.isoformat()
                                }
                            },
                            {
                                "property": date_item,
                                "date": {
                                    "on_or_before": end_date.isoformat()
                                }
                            }
                        ]
                    })
            ### [Under development] ###
            if category_dict is not None:
                for category_item, set_category in category_dict.items():
                    payload["filter"]["and"].append({
                        "property": category_item,
                        "select": {
                            "equals": set_category
                        }
                    })
        if next_cursor:
            payload["start_cursor"] = next_cursor
        response = requests.post(f"https://api.notion.com/v1/databases/{database_id}/query", headers=notion_headers, json=payload)
        response_json = response.json()
        if response.status_code != 200:
            logger.error(f"Error fetching page IDs. Response: {response_json}")
            return []
        all_results.extend(response_json["results"])
        has_more = response_json.get("has_more", False)
        next_cursor = response_json.get("next_cursor")
    return all_results

# Overwrite a Notion page property (rich text)
def update_notion_rich_text(page_id, property_name, new_value):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    data = {
        "properties": {
            property_name: {
                "rich_text":  new_value
            }
        }
    }
    response = requests.patch(url, headers=notion_headers, json=data)
    if response.status_code == 200:
        return "Updated successfully"
    else:
        return f"Failed to update. Reason: {response.text}"

# Overwrite a Notion page property (rich-text content)
def update_notion_rich_text_content(page_id, property_name, new_value):
    url = f"https://api.notion.com/v1/pages/{page_id}"

    # Split the string into 2000-character chunks and convert to rich_text blocks
    max_length = 2000
    chunks = [new_value[i:i + max_length] for i in range(0, len(new_value), max_length)]
    rich_text_blocks = [{"text": {"content": chunk}} for chunk in chunks]

    # Payload sent to the Notion API
    data = {
        "properties": {
            property_name: {
                "rich_text": rich_text_blocks
            }
        }
    }
    response = requests.patch(url, headers=notion_headers, json=data)
    if response.status_code == 200:
        return "Updated successfully"
    else:
        return f"Failed to update. Reason: {response.text}"

# Overwrite a Notion page property (number)
def update_notion_num(page_id, property_name, new_value):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    data = {
        "properties": {
            property_name: {
                "number": new_value
            }
        }
    }
    response = requests.patch(url, headers=notion_headers, json=data)
    if response.status_code == 200:
        return "Updated successfully"
    else:
        return f"Failed to update. Reason: {response.text}"

# Overwrite a Notion page property (select)
def update_notion_select(page_id, property_name, new_value):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    data = {
        "properties": {
            property_name: {
                "select": {
                    "name": new_value
                }
            }
        }
    }
    response = requests.patch(url, headers=notion_headers, json=data)
    if response.status_code == 200:
        return "Updated successfully"
    else:
        return f"Failed to update. Reason: {response.text}"

# Overwrite a Notion page property (date)
def update_notion_date(page_id, date_name, date):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    data = {
        "properties": {
            date_name: {
                "date": {
                    "start": date,
                    "end": None,
                    "time_zone": None
                }
            }
        }
    }
    response = requests.patch(url, headers=notion_headers, json=data)
    if response.status_code == 200:
        return "Updated successfully"
    else:
        return f"Failed to update. Reason: {response.text}"

# Update the URL field on a Notion page
def update_notion_url(page_id, property_name, item):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    data = {
        "properties": {
            property_name: {
                "url": item,
            }
        }
    }
    response = requests.patch(url, headers=notion_headers, json=data)
    if response.status_code == 200:
        return "Updated successfully"
    else:
        return f"Failed to update. Reason: {response.text}"

# Set an arbitrary checkbox field on a Notion page
def update_notion_chk(page_id, chk_item, chk=True):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    data = {
        "properties": {
            chk_item: {
                "checkbox": chk
            }
        }
    }
    response = requests.patch(url, headers=notion_headers, json=data)
    if response.status_code == 200:
        return "Updated successfully"
    else:
        return f"Failed to update. Reason: {response.text}"

# Overwrite a Notion page (block)
def update_notion_block(page_id, text):
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    data = {
        "children": [{
            "paragraph": {
                "rich_text": [{
                    "text": {
                        "content": f"{text}"
                        }
                    }]
                }
            },]
        }
    response = requests.patch(url, headers=notion_headers, json=data)
    if response.status_code != 200:
        logger.error(f"Failed to update. Reason: {response.text}")

# Overwrite a Notion page (block)
def update_notion_block_bold(page_id, text):
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    data = {
        "children": [{
            "paragraph": {
                "rich_text": [{
                    "text": {
                        "content": f"{text}"
                        },"annotations": {"bold": True,"italic": False, "strikethrough": False, "underline": False, "code": False, "color": "default"},
                    }]
                }
            },]
        }
    response = requests.patch(url, headers=notion_headers, json=data)
    if response.status_code != 200:
        logger.error(f"Failed to update. Reason: {response.text}")

# Archive a Notion page by ID
def archive_page(page_id):
    update_payload = {
        "archived": True
    }
    response = requests.patch(f"https://api.notion.com/v1/pages/{page_id}", headers=notion_headers, json=update_payload)
    if response.status_code != 200:
        logger.error(f"Error archiving page {page_id}. Response: {response.json()}")

# Convert a rich-text array to a plain string
def _rich_text_to_plain(rich_text_array):
    return "".join([rt.get("plain_text", "") for rt in (rich_text_array or [])])

# Convert a Notion block array to Markdown-like text (recursive)
def _blocks_to_text(blocks, indent=0):
    lines = []
    prefix = "  " * indent
    for block in blocks:
        bt = block.get("type")
        content = block.get(bt, {}) if bt else {}
        rich = content.get("rich_text", []) if isinstance(content, dict) else []
        text = _rich_text_to_plain(rich)
        if bt == "paragraph":
            lines.append(prefix + text)
        elif bt == "heading_1":
            lines.append(prefix + "# " + text)
        elif bt == "heading_2":
            lines.append(prefix + "## " + text)
        elif bt == "heading_3":
            lines.append(prefix + "### " + text)
        elif bt == "bulleted_list_item":
            lines.append(prefix + "- " + text)
        elif bt == "numbered_list_item":
            lines.append(prefix + "1. " + text)
        elif bt == "to_do":
            mark = "[x]" if content.get("checked") else "[ ]"
            lines.append(f"{prefix}- {mark} {text}")
        elif bt == "quote" or bt == "callout":
            lines.append(prefix + "> " + text)
        elif bt == "toggle":
            lines.append(prefix + text)
        elif bt == "code":
            language = content.get("language", "") if isinstance(content, dict) else ""
            lines.append(f"{prefix}```{language}\n{text}\n{prefix}```")
        elif bt == "divider":
            lines.append(prefix + "---")
        elif text:
            lines.append(prefix + text)

        if block.get("has_children"):
            child_blocks = _get_children_blocks(block["id"])
            child_text = _blocks_to_text(child_blocks, indent + 1)
            if child_text:
                lines.append(child_text)
    return "\n".join(lines)

# Fetch children blocks under the specified block ID (with pagination)
def _get_children_blocks(block_id):
    all_blocks = []
    has_more = True
    next_cursor = None
    while has_more:
        url = f"https://api.notion.com/v1/blocks/{block_id}/children"
        params = {"page_size": 100}
        if next_cursor:
            params["start_cursor"] = next_cursor
        response = requests.get(url, headers=notion_headers, params=params)
        if response.status_code != 200:
            logger.error(f"Error fetching children for {block_id}: {response.text}")
            return all_blocks
        response_json = response.json()
        all_blocks.extend(response_json.get("results", []))
        has_more = response_json.get("has_more", False)
        next_cursor = response_json.get("next_cursor")
    return all_blocks

# Fetch a Notion page body as Markdown-like text
def get_page_body_text(page_id):
    blocks = _get_children_blocks(page_id)
    return _blocks_to_text(blocks)

# Create a Notion page
def create_page(db_id, page_title, title_item="名前"):  # title_item is the Notion property name (default "名前"=Name)
    page_content = []

    # Archive entries whose title duplicates the new one
    #page_ids = get_all_page_ids(db_id)
    pages = get_all_pages(db_id)
    if pages:
        for page in pages:
            entry_title = get_title_by_id(pages, page["id"], title_item)
            if entry_title == page_title:
                archive_page(page["id"])
                logger.info(f"Archived: {entry_title}")

    # Append entry detail
    page_content.append({
        "object": 'block',
        "type": 'paragraph',
        "paragraph": {
            "rich_text": [{
                "text": {
                    "content": " "
                    },"annotations": {"bold": True,"italic": False, "strikethrough": False, "underline": False, "code": False, "color": "default"},
                }],
            }
        },)

    # Create a new page in Notion
    payload = {
        "parent": {"database_id": db_id},
        "properties": {
            title_item: {
                "title": [{
                    "text": {
                        "content": page_title
                        },
                    }],
                },
            },
        "children": page_content,
        }
    response = requests.post("https://api.notion.com/v1/pages", headers=notion_headers, json=payload)
    response_json = response.json()
    logger.info(f"Created: {page_title}")

    if response.status_code != 200:
        logger.error(f"Error creating {page_title}: {response_json}")
    return response_json
