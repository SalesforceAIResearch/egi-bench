from .functions import *

TOOLS = [
    get_agents_with_max_cases,
    get_agents_with_min_cases,
    calculate_average_handle_time,
    get_start_date,
    get_period,
    get_agent_handled_cases_by_period,
    get_qualified_agent_ids_by_case_count,
    get_cases,
    get_non_transferred_case_ids,
    get_agent_transferred_cases_by_period,
    get_shipping_state,
    calculate_region_average_closure_times,
    get_order_item_ids_by_product,
    get_issue_counts,
    find_id_with_max_value,
    find_id_with_min_value,
    get_account_id_by_contact_id,
    get_purchase_history,
    get_month_to_case_count,
    search_knowledge_articles,
    search_products,
    get_issues,
    respond,
    get_livechat_transcript_by_case_id,
    get_email_messages_by_case_id
]

TOOLS_FULL = TOOLS + [issue_soql_query, issue_sosl_query]
print(len(TOOLS_FULL))
assert all(tool.__info__ for tool in TOOLS)
assert all(tool.__info__ for tool in TOOLS_FULL)