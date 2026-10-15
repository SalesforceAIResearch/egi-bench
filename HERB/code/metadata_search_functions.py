import time
from collections import defaultdict
from llama_index.core.tools import FunctionTool
from pydantic import Field
from typing import List, Annotated
import json
import os
from utils import get_gpt4_response


with open("../data/metadata/employee.json", "r") as f:
    employee_data = json.load(f)

all_ids, all_roles = set(), set()
role2id = defaultdict(list)
id2role, id2name = dict(), dict()
name2id = defaultdict(list)

for idx in employee_data:
    element = employee_data[idx]
    all_ids.add(element["employee_id"])
    all_roles.add(element["role"])
    role2id[element["role"].lower()].append(element["employee_id"])
    id2role[element["employee_id"]] = element["role"]
    id2name[element["employee_id"]] = element["name"]
    name2id[element["name"].lower()].append(element["employee_id"])
    sub_names = element["name"].split()
    for sub_name in sub_names:
        name2id[sub_name.lower()].append(element["employee_id"])

pr_metadata = {}
url_metadata = {}

data_folder = "../data/products"
for filename in os.listdir(data_folder):
    if filename.endswith(".json"):
        file_path = os.path.join(data_folder, filename)
        with open(file_path, "r") as f:
            data = json.load(f)
            
            if 'prs' in data:
                for pr in data['prs']:
                    pr_metadata[pr['link'].lower()] = pr
                    
            if 'urls' in data:
                for url in data['urls']:
                    url_metadata[url['link'].lower()] = url
                    
            if 'documents' in data:
                for doc in data['documents']:
                    url_metadata[doc['document_link'].lower()] = doc

with open("../data/metadata/customers_data.json", "r") as f:
    customer_data = json.load(f)

cust2id = defaultdict(list)
id2cust = dict()

for element in customer_data:
    cust2id[element["company"].lower()].append(element["id"])
    id2cust[element["id"].lower()] = element["company"]


def role_to_id_search(
    text: str = Field(
        description="A text containing some role names such as 'Engineer Lead'."
    ),
) -> Annotated[
    List[str],
    Field(
        description="A list of employee IDs corresponding to the roles in the question."
    ),
]:
    prompt = (
        "Extract role names (e.g., ['Engineer Lead', 'UX Designer']) from the given text. "
        "If no roles are mentioned, return []."
        "\n\nAvailable roles: Marketing Manager, Engineering Lead, VP of Engineering, Software Engineer, QA Specialist, Product Manager, Technical Architect, UX Researcher, Marketing Research Analyst, Chief Product Officer"
        "\n\nText: {text}"
        "\n\nRespond in json format: {{'roles': ['list of roles']}}"
    ).format(roles=list(all_roles), question=text)
    messages = [
        {
            'role': 'user',
            'content': prompt
        }
    ]
    role_names = get_gpt4_response(messages, response_format="json")
    res = {}
    try:
        for role in role_names.get("roles", []):
            role_key = role.lower()
            ids = role2id.get(role_key, [])
            if ids:
                res[role_key] = ids
    except (AttributeError, TypeError) as e:
        print(f"[role_to_id_search] Failed to extract roles from response: {role_names} (Error: {e})")
    if not res:
        print(f"No roles found: {role_names}")
    return res


role_id_search_tool = FunctionTool.from_defaults(
    fn=role_to_id_search,
    name="role_to_id_search",
    description='Given a text snippet, this tool extracts any role names (e.g., "Product Manager") mentioned and returns the employee IDs associated with those roles.',
)


def name_to_id_search(
    content: str = Field(
        description="A text snippet containing some employee names such as 'Xiangyu Peng'."
    ),
) -> Annotated[
    List[str],
    Field(
        description="A list of employee IDs corresponding to the name mentioned in the text."
    ),
]:
    prompt = (
        "Extract employee names (e.g., 'Becky Peng') from the given text. "
        "If no names are mentioned, return []."
        "\n\nText: {content}"
        "\n\nRespond in json format: {{'names': ['list of employee names']}}"
    ).format(content=content)

    messages = [
        {
            'role': 'user',
            'content': prompt
        }
    ]
    employee_names = get_gpt4_response(messages, response_format="json")

    res = {}
    try:
        for name in employee_names.get("names", []):
            name_key = name.lower()
            ids = name2id.get(name_key, [])
            if ids:
                res[name_key] = ids
    except (AttributeError, TypeError) as e:
        print(f"[name_to_id_search] Failed to extract employee names from response: {employee_names} (Error: {e})")

    if not res:
        print(f"No IDs found: {employee_names}")
    return res

name_id_search_tool = FunctionTool.from_defaults(
    fn=name_to_id_search,
    name="name_to_id_search",
    description="Given a text snippet that contains employee names, this tool returns a list of the corresponding employee IDs for those names.",
)


def id_to_name_search(
    content: str = Field(
        description="A text snippet containing some employee IDs such as eid_123456."
    ),
) -> Annotated[
    str,
    Field(
        description="Employee names corresponding to the employee IDs mentioned in the text."
    ),
]:
    prompt = (
        "Extract employee Ids from the given text. "
        "If no IDs are mentioned, return []."
        "\n\nText: {content}"
        "\n\nRespond in json format: {{'ids': ['list of employee IDs']}}"
    ).format(content=content)

    messages = [
        {
            'role': 'user',
            'content': prompt
        }
    ]
    employee_ids = get_gpt4_response(messages, response_format="json")

    res = {}
    try:
        for emp_id in employee_ids.get("ids", []):
            name = id2name.get(emp_id, None)
            if name:
                res[emp_id] = name
    except (AttributeError, TypeError) as e:
        print(f"[id_to_name_search] Failed to extract employee names from response: {employee_ids} (Error: {e})")

    if not res:
        print(f"No names found: {employee_ids}")
    return res

id_name_search_tool = FunctionTool.from_defaults(
    fn=id_to_name_search,
    name="id_to_name_search",
    description="Given a text snippet that contains employee IDs, this tool returns the corresponding employee's names.",
)


def id_to_role_search(
    content: str = Field(
        description="A text snippet containing some employee IDs such as 'eid_qwehjweh'."
    ),
) -> Annotated[
    str,
    Field(
        description="Employee roles corresponding to the employee IDs mentioned in the text."
    ),
]:
    prompt = (
        "Extract employee Ids from the given text. "
        "If no IDs are mentioned, return []."
        "\n\nText: {content}"
        "\n\nRespond in json format: {{'ids': ['list of employee names']}}"
    ).format(content=content)

    messages = [
        {
            'role': 'user',
            'content': prompt
        }
    ]
    employee_ids = get_gpt4_response(messages, response_format="json")

    res = {}
    try:
        for emp_id in employee_ids.get("ids", []):
            role = id2role.get(emp_id, None)
            if role:
                res[emp_id] = role
    except (AttributeError, TypeError) as e:
        print(f"[id_to_role_search] Failed to extract roles from response: {employee_ids} (Error: {e})")

    if not res:
        print(f"No roles found: {employee_ids}")
    return list(set(res))

id_role_search_tool = FunctionTool.from_defaults(
    fn=id_to_role_search,
    name="id_to_role_search",
    description="Given a text snippet that contains employee IDs, this tool returns the corresponding employee's role, e.g., 'Product Manager'.",
)

def pr_search(
    content: str = Field(
        description="A text snippet containing one or more GitHub PR links."
    ),
) -> Annotated[
    List[str],
    Field(
        description="List of Github PR details corresponding to the PR links found in the text."
    ),
]:
    prompt = (
        "Extract GitHub PR links from the given text. "
        "If no PR links are found, return []."
        "\n\nText: {content}"
        "\n\nRespond in json format: {{'links': ['list of PR links']}}"
    ).format(content=content)

    messages = [
        {
            'role': 'user',
            'content': prompt
        }
    ]
    pr_links = get_gpt4_response(messages, response_format="json")

    res = []
    try:
        for link in pr_links.get("links", []):
            pr_details = pr_metadata.get(link.lower())
            if pr_details:
                res.append(pr_details)
    except (AttributeError, TypeError) as e:
        print(f"[pr_search] Failed to extract PR links from response: {pr_links} (Error: {e})")

    if not res:
        print(f"No PR details found: {pr_links}")
    return res


pr_search_tool = FunctionTool.from_defaults(
    fn=pr_search,
    name="pr_search",
    description="Given a text snippet containing one or more GitHub PR links, this tool returns metadata such as the PR status and other relevant details for each found PR.",
)

def url_search(
    content: str = Field(
        description="A text snippet containing one or more URLs."
    ),
) -> Annotated[
    List[str],
    Field(
        description="List of content descriptions and other relevant information from the pages corresponding to the URLs found in the text."
    ),
]:
    prompt = (
        "Extract URLs from the given text. "
        "If no URLs are found, return []."
        "\n\nText: {content}"
        "\n\nRespond in json format: {{'links': ['list of URLs']}}"
    ).format(content=content)

    messages = [
        {
            'role': 'user',
            'content': prompt
        }
    ]
    url_links = get_gpt4_response(messages, response_format="json")

    res = []
    try:
        for link in url_links.get("links", []):
            url_details = url_metadata.get(link.lower())
            if url_details:
                res.append(url_details)
    except (AttributeError, TypeError) as e:
        print(f"[url_search] Failed to extract URLs from response: {url_links} (Error: {e})")

    if not res:
        print(f"No URL details found: {url_links}")
    return res


url_search_tool = FunctionTool.from_defaults(
    fn=url_search,
    name="url_search",
    description="Given a text snippet containing one or more URLs, this tool returns metadata such as the content description and other relevant information from each found URL.",
)


def company_to_id_search(
    content: str = Field(
        description="A text snippet containing some company names such as 'Google'."
    ),
) -> Annotated[
    List[str],
    Field(
        description="A list of customer IDs corresponding to the company name mentioned in the text."
    ),
]:
    prompt = (
        "Extract company names (e.g., 'Google') from the given text. "
        "If no names are mentioned, return []."
        "\n\nText: {content}"
        "\n\nRespond in json format: {{'names': ['list of company names']}}"
    ).format(content=content)

    messages = [
        {
            'role': 'user',
            'content': prompt
        }
    ]
    comp_names = get_gpt4_response(messages, response_format="json")

    res = {}
    try:
        for name in comp_names.get("names", []):
            name_key = name.lower()
            ids = cust2id.get(name_key, [])
            if ids:
                res[name_key] = ids
    except (AttributeError, TypeError) as e:
        print(f"[company_to_id_search] Failed to extract company names from response: {comp_names} (Error: {e})")

    if not res:
        print(f"No IDs found: {comp_names}")
    return res

company_id_search_tool = FunctionTool.from_defaults(
    fn=company_to_id_search,
    name="company_to_id_search",
    description="Given a text chunk that contains customer company names, this tool returns a list of the corresponding customer IDs for those names.",
)


def id_to_company_search(
    content: str = Field(
        description="A text snippet containing some customer IDs such as 'CUST-0012567'."
    ),
) -> Annotated[
    str,
    Field(
        description="Company names corresponding to the customer IDs mentioned in the text."
    ),
]:
    prompt = (
        "Extract customer Ids from the given text. "
        "If no IDs are mentioned, return []."
        "\n\nText: {content}"
        "\n\nRespond in json format: {{'ids': ['list of customer IDs']}}"
    ).format(content=content)

    messages = [
        {
            'role': 'user',
            'content': prompt
        }
    ]
    cust_ids = get_gpt4_response(messages, response_format="json")

    res = {}
    try:
        for cust_id in cust_ids.get("ids", []):
            name = id2cust.get(cust_id.lower(), None)
            if name:
                res[cust_id] = name
    except (AttributeError, TypeError) as e:
        print(f"[id_to_company_search] Failed to extract company names from response: {cust_ids} (Error: {e})")

    if not res:
        print(f"No companies found: {cust_ids}")
    return res

id_company_search_tool = FunctionTool.from_defaults(
    fn=id_to_company_search,
    name="id_to_company_search",
    description="Given a text snippet that contains customer IDs, this tool returns the corresponding company's names.",
)


def finish_agent(question, answer):
    prompt = """Given the question and answer, determine whether the given answer successfully answers the given question.
Reply "Yes" if the answer sufficiently addresses the given question with detailed information.  
Reply "No" if the answer fails to address the question due to insufficient context."""
    prompt += (
        f'\n\nQuestion: {question}\n\nAnswer: {answer}\n\nRespond using the below json format:\n{{"done": "yes/no", "reason": "justification for the decision"}}'
    )
    messages = [
        {
            'role': 'user',
            'content': prompt
        }
    ]
    verification = get_gpt4_response(messages, response_format="json")
    if verification["done"].lower() == "no":
        return False
    return True

